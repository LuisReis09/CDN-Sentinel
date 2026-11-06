from __future__ import annotations

import os
import hashlib
import subprocess
import sys
import time
import math
import re
from pathlib import Path
from typing import Any, Dict

from config import SimulationConfig
from models.entities import CDNServer, SimulationState
from models.entities import Client
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.topology_service import TopologyService
from services.city_lookup_service import CityLookupService
from services.capacity_service import capacity_limits, profile_for_tier, service_metrics


class SimulationController:
    def __init__(self, repository: SimulationRepository, http_client: CDNHttpClient) -> None:
        self._repository = repository
        self._http_client = http_client
        self._topology = TopologyService()
        self._processes: Dict[str, subprocess.Popen] = {}
        self._client_processes: Dict[str, subprocess.Popen] = {}
        self._secret_key = "local-development-secret"
        self._city_lookup = CityLookupService()

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def initialize(self, payload: dict) -> dict:
        config = SimulationConfig.from_payload(payload)
        self._secret_key = config.secret_key
        self._http_client.configure_secret(config.secret_key)
        self.shutdown_nodes()
        servers, clients = self._topology.build(config)
        state = SimulationState(initialized=True, started_at=time.time(), updated_at=time.time(), config=config.to_dict(), servers=servers, clients=clients, lifecycle="starting")
        self._repository.replace(state)
        self._repository.append_event({
            "type": "simulation_initialized",
            "at": time.time(),
            "config": config.to_dict(),
            "node_protocol": "HTTP/1.1",
            "routing_algorithm": "Haversine / nearest healthy CDN",
            "gossip_protocol": "HTTP gossip",
            "watermark_algorithm": "HMAC-SHA256",
        })

        for server in servers.values():
            self._start_node(server, config)
        for client in clients.values():
            self._start_client(client)
        self._configure_peers(state)
        self.refresh_servers()
        self._reconcile_blacklist(state)
        self.refresh_clients()
        state.lifecycle = "running" if any(server.status in {"healthy", "degraded"} for server in state.servers.values()) else "error"
        state.updated_at = time.time()
        self._repository.append_event({"type": "simulation_running" if state.lifecycle == "running" else "simulation_start_failed", "at": time.time(), "lifecycle": state.lifecycle})
        malicious_count = sum(1 for client in clients.values() if client.malicious)
        return {
            "initialized": True,
            "configuration": config.to_dict(),
            "malicious_clients": malicious_count,
            "servers": [server.to_dict() for server in servers.values()],
            "clients": [client.to_dict() for client in clients.values()],
        }

    def update(self, payload: dict) -> dict:
        state = self._repository.state_ref()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("A simulação ainda não foi inicializada")
        structural = {key for key in ("num_servers", "num_clients", "base_node_port", "base_client_port", "seed") if key in payload}
        merged = {**state.config, **payload, "secret_key": self._secret_key}
        config = SimulationConfig.from_payload(merged)
        if structural and any(int(payload[key]) != int(state.config[key]) for key in structural):
            return self.initialize(merged)
        state.config.update(config.to_dict())
        for client in state.clients.values():
            digest = hashlib.sha256(f"{client.client_id}:{config.malicious_probability}".encode()).digest()
            client.malicious = int.from_bytes(digest[:8], "big") / 2**64 < config.malicious_probability
        for server in state.servers.values():
            if server.status == "healthy":
                try:
                    self._http_client.configure(server, {"latency_factor": config.latency_factor})
                except Exception as exc:
                    server.last_error = str(exc)
        self._repository.update_config(config.to_dict())
        self._repository.append_event({"type": "simulation_config_updated", "at": time.time(), "changes": payload})
        return self.status()

    def pause(self) -> dict:
        state = self._repository.snapshot()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("não há simulação ativa para pausar")
        self._repository.set_paused(True)
        self._repository.append_event({"type": "simulation_paused", "at": time.time()})
        return self.status()

    def resume(self) -> dict:
        state = self._repository.snapshot()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("não há simulação encerrada para retomar")
        self._repository.set_paused(False)
        self._repository.append_event({"type": "simulation_resumed", "at": time.time()})
        return self.status()

    def status(self) -> dict:
        if self._repository.snapshot().lifecycle != "ended":
            self.refresh_clients()
        state = self._repository.snapshot()
        now = time.time()
        healthy_servers = sum(1 for server in state.servers.values() if server.health_status == "healthy" or server.status == "healthy")
        degraded_servers = sum(1 for server in state.servers.values() if server.health_status == "degraded" or server.status == "degraded")
        overloaded_servers = sum(1 for server in state.servers.values() if server.health_status == "overloaded" or server.status == "overloaded")
        available_servers = sum(1 for server in state.servers.values() if server.health_status in {"healthy", "degraded", "overloaded"} or server.status in {"healthy", "degraded", "overloaded"})
        online_clients = sum(1 for client in state.clients.values() if client.active and client.online)
        demand_rps = online_clients * float(state.config.get("demand_rps_per_client", 0.25))
        capacity_values = [float(server.capacity_rps) for server in state.servers.values() if server.server_id and (server.health_status in {"healthy", "degraded", "overloaded"} or server.status in {"healthy", "degraded", "overloaded"}) and server.capacity_rps > 0]
        if not capacity_values and available_servers:
            fallback_profile = profile_for_tier(str(state.config.get("node_tier", "basic")))
            capacity_values = [capacity_limits(fallback_profile)["capacity_rps"]] * available_servers
        capacity = sum(capacity_values)
        utilization = demand_rps / capacity if capacity else 0
        queue_depth = sum(server.queue_depth for server in state.servers.values())
        queue_rejected = sum(server.queue_rejected for server in state.servers.values())
        queue_wait_ms = round(sum(server.queue_wait_ms for server in state.servers.values()) / len(state.servers), 1) if state.servers else 0.0
        if not available_servers:
            profile = "indisponível"
            message = "Nenhum nó saudável para atender a demanda"
        elif not healthy_servers:
            profile = "degradada"
            message = "Todos os nós estão degradados, mas ainda podem atender com risco de latência"
        elif utilization >= 0.95 and (queue_depth or queue_rejected):
            profile = "gargalo"
            message = "Demanda efetiva próxima ou acima da capacidade: fila e rejeições observadas"
        elif healthy_servers >= max(1, online_clients * 2):
            profile = "sobredimensionada"
            message = "Muitos nós para poucos clientes: custo operacional elevado"
        else:
            profile = "equilibrada"
            message = "Capacidade compatível com a demanda observada"
        window_seconds = 60.0
        recent_traffic = [item for item in state.traffic if now - float(item.get("at", now)) <= window_seconds]
        latencies = [float(item.get("end_to_end_ms", item.get("http_rtt_ms", 0))) for item in recent_traffic]
        ordered_latencies = sorted(latencies)

        def percentile(values: list[float], fraction: float) -> float:
            if not values:
                return 0.0
            index = min(len(values) - 1, max(0, int(len(values) * fraction + 0.999) - 1))
            return round(values[index], 1)

        average_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
        p50_latency = percentile(ordered_latencies, 0.50)
        p95_latency = percentile(ordered_latencies, 0.95)
        p99_latency = percentile(ordered_latencies, 0.99)
        error_count = sum(int(server.errors_total) for server in state.servers.values())
        monthly_server_cost = sum(float(profile_for_tier(server.capacity_tier).cost_monthly_usd) for server in state.servers.values() if server.status != "stopped") or available_servers * float(state.config.get("monthly_server_cost_usd", state.config.get("monthly_server_cost_unit", 100.0)))
        monthly_fixed_cost = float(state.config.get("monthly_fixed_cost_usd", state.config.get("monthly_fixed_cost_unit", 150.0)))
        monthly_variable_cost = online_clients * 2.0
        monthly_cost = monthly_server_cost + monthly_fixed_cost + monthly_variable_cost
        paying_clients = max(1, len(state.clients)) if state.clients else 0
        configured_price = float(state.config.get("monthly_client_price_usd", state.config.get("monthly_client_price_unit", 25.0)))
        break_even_price = monthly_cost / paying_clients if paying_clients else 0
        minimum_price = break_even_price * 1.2 if paying_clients else 0
        revenue = sum(1 for client in state.clients.values() if client.active and client.online and not client.malicious) * configured_price
        observed_requests = len(recent_traffic)
        observed_rps = round(observed_requests / window_seconds, 3)
        total_requests = sum(int(server.requests_total) for server in state.servers.values())
        successful_requests = max(0, total_requests - error_count)
        success_rate_pct = round(100 * successful_requests / total_requests, 2) if total_requests else None
        slo_p95_ms = float(state.config.get("slo_p95_ms", 250.0))
        slo_success_rate_pct = float(state.config.get("slo_success_rate_pct", 99.0))
        slo_compliant = bool(observed_requests and p95_latency <= slo_p95_ms and (success_rate_pct is None or success_rate_pct >= slo_success_rate_pct))
        return {
            "initialized": state.initialized,
            "paused": state.paused,
            "lifecycle": state.lifecycle,
            "simulation_id": state.simulation_id,
            "ended_at": state.ended_at,
            "end_reason": state.end_reason,
            "started_at": state.started_at,
            "updated_at": state.updated_at,
            "configuration": state.config,
            "tick_interval_seconds": round(float(state.config.get("tick_interval_seconds", 2.5)), 2),
            "servers_total": len(state.servers),
            "clients_total": len(state.clients),
            "malicious_clients": sum(1 for client in state.clients.values() if client.malicious),
            "blacklisted_total": len(state.blacklist),
            "scalability": {
                "online_clients": online_clients,
                "healthy_servers": healthy_servers,
                "degraded_servers": degraded_servers,
                "available_servers": available_servers,
                "capacity_per_server": round(sum(capacity_values) / len(capacity_values), 3) if capacity_values else 0.0,
                "total_capacity": capacity,
                "capacity_rps": round(capacity, 3),
                "demand_rps": round(demand_rps, 3),
                "served_rps": observed_rps,
                "utilization": round(utilization, 3),
                "profile": profile,
                "message": message,
                "estimated_monthly_cost_usd": round(monthly_cost, 2),
                "estimated_queue_latency_ms": queue_wait_ms,
                "queue_depth": queue_depth,
                "queue_rejected": queue_rejected,
                "average_latency_ms": average_latency,
                "p50_latency_ms": p50_latency,
                "p95_latency_ms": p95_latency,
                "p99_latency_ms": p99_latency,
                "metrics_window_seconds": window_seconds,
                "observed_request_count": len(recent_traffic),
                "observed_rps": observed_rps,
                "observed_errors": error_count,
                "success_rate_pct": success_rate_pct,
                "slo_p95_ms": slo_p95_ms,
                "slo_success_rate_pct": slo_success_rate_pct,
                "slo_compliant": slo_compliant,
                "metrics_provenance": "demanda/capacidade são modelo virtual; fila, erros, RTT e E2E vêm dos nós HTTP",
                "latency_semantics": "end_to_end_ms de requisições concluídas na janela; artificial_latency_ms, http_rtt_ms e queue_wait_ms são separados",
                "cost_model": {
                    "currency": "USD/mês",
                    "server_cost_usd": round(monthly_server_cost, 2),
                    "fixed_cost_usd": round(monthly_fixed_cost, 2),
                    "variable_cost_usd": round(monthly_variable_cost, 2),
                    "total_monthly_cost_usd": round(monthly_cost, 2),
                    "configured_client_price_usd": round(configured_price, 2),
                    "break_even_price_per_client_usd": round(break_even_price, 2),
                    "minimum_price_with_margin_per_client_usd": round(minimum_price, 2),
                    "projected_revenue_usd": round(revenue, 2),
                    "projected_margin_usd": round(revenue - monthly_cost, 2),
                },
            },
        }

    def reset_metrics(self) -> dict:
        self._repository.reset_metrics()
        self._repository.append_event({"type": "metrics_reset", "at": time.time()})
        return self.status()

    def end(self, reason: str = "operator") -> dict:
        state = self._repository.state_ref()
        if not state.initialized:
            raise RuntimeError("A simulação ainda não foi inicializada")
        if state.lifecycle == "ended":
            history = self._repository.history(state.simulation_id)
            return {"simulation_id": state.simulation_id, "lifecycle": "ended", "history": history[-1] if history else None}
        state.lifecycle = "stopping"
        state.updated_at = time.time()
        self._repository.append_event({"type": "simulation_stopping", "at": time.time(), "reason": reason})
        self.shutdown_nodes()
        for server in state.servers.values():
            server.status = "stopped"
            server.load = 0
        for client in state.clients.values():
            client.online = False
            client.process_status = "stopped"
        state.paused = False
        state.lifecycle = "ended"
        state.ended_at = time.time()
        state.end_reason = reason
        state.updated_at = state.ended_at
        self._repository.append_event({"type": "simulation_ended", "at": state.ended_at, "reason": reason, "lifecycle": "ended"})
        history = self._repository.archive_current(state.ended_at, reason)
        return {"simulation_id": state.simulation_id, "lifecycle": "ended", "ended_at": state.ended_at, "history": history}

    def add_client(self, payload: dict) -> dict:
        state = self._repository.state_ref()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("A simulação ainda não foi inicializada")
        if len(state.clients) >= 1000:
            raise ValueError("A simulação já atingiu o limite de 1000 clientes")
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("latitude e longitude são obrigatórias e devem ser numéricas") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("coordenadas fora do intervalo terrestre")
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("coordenadas devem ser finitas")
        client_id = str(payload.get("client_id") or f"client-{len(state.clients) + 1:04d}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", client_id):
            raise ValueError("client_id inválido")
        raw_malicious = payload.get("malicious", False)
        if isinstance(raw_malicious, bool):
            malicious = raw_malicious
        elif isinstance(raw_malicious, str) and raw_malicious.lower() in {"true", "false"}:
            malicious = raw_malicious.lower() == "true"
        else:
            raise ValueError("malicious deve ser booleano")
        client = Client(
            client_id=client_id,
            latitude=latitude,
            longitude=longitude,
            city=str(payload.get("city") or self._city_lookup.lookup(latitude, longitude)),
            malicious=malicious,
        )
        self._repository.add_client(client)
        self._start_client(client)
        self._repository.update_config({"num_clients": len(state.clients)})
        self._repository.append_event({"type": "client_added", "at": time.time(), "client_id": client_id, "latitude": latitude, "longitude": longitude})
        return client.to_dict()

    def add_server(self, payload: dict) -> dict:
        state = self._repository.state_ref()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("A simulação ainda não foi inicializada")
        if len(state.servers) >= 20:
            raise ValueError("A simulação já atingiu o limite de 20 servidores")
        try:
            latitude = float(payload["latitude"])
            longitude = float(payload["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("latitude e longitude são obrigatórias e devem ser numéricas") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("coordenadas fora do intervalo terrestre")
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("coordenadas devem ser finitas")
        server_id = str(payload.get("server_id") or f"cdn-{len(state.servers) + 1:02d}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", server_id):
            raise ValueError("server_id inválido")
        requested_port = payload.get("port")
        port = int(requested_port) if requested_port is not None else max([server.port for server in state.servers.values()], default=int(state.config.get("base_node_port", 5101)) - 1) + 1
        if not 1024 <= port <= 64000:
            raise ValueError("A porta deve estar entre 1024 e 64000")
        server = CDNServer(
            server_id=server_id,
            host="127.0.0.1",
            port=port,
            latitude=latitude,
            longitude=longitude,
            city=str(payload.get("city") or self._city_lookup.lookup(latitude, longitude)),
        )
        self._repository.add_server(server)
        config = SimulationConfig.from_payload({**state.config, "secret_key": self._secret_key})
        self._start_node(server, config)
        self._configure_peers(state)
        self.refresh_servers()
        self._reconcile_blacklist(state)
        self._repository.update_config({"num_servers": len(state.servers)})
        self._repository.append_event({"type": "server_added", "at": time.time(), "server_id": server_id, "latitude": latitude, "longitude": longitude})
        return server.to_dict()

    def _start_node(self, server: CDNServer, config: SimulationConfig) -> None:
        root = Path(__file__).resolve().parents[1]
        command = [
            sys.executable,
            str(root / "node_app.py"),
            "--node",
            "--server-id",
            server.server_id,
            "--host",
            server.host,
            "--port",
            str(server.port),
            "--latitude",
            str(server.latitude),
            "--longitude",
            str(server.longitude),
            "--city",
            server.city,
            "--latency-factor",
            str(config.latency_factor),
            "--capacity-tier",
            server.capacity_tier or config.node_tier,
        ]
        environment = os.environ.copy()
        environment["CDN_NODE_SECRET"] = config.secret_key
        process = subprocess.Popen(
            command,
            cwd=str(root),
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server.process_id = process.pid
        self._processes[server.server_id] = process
        for _ in range(30):
            if process.poll() is not None:
                break
            try:
                self._http_client.health(server)
                server.status = "healthy"
                return
            except Exception as exc:  # startup race; keep trying briefly
                server.last_error = str(exc)
                time.sleep(0.1)
        server.status = "offline"

    def _start_client(self, client: Client) -> None:
        root = Path(__file__).resolve().parents[1]
        process = subprocess.Popen(
            [sys.executable, str(root / "client_app.py"), "--client-id", client.client_id, "--city", client.city],
            cwd=str(root),
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        client.process_id = process.pid
        client.process_status = "online" if process.poll() is None else "offline"
        self._client_processes[client.client_id] = process

    def refresh_clients(self) -> list[dict]:
        state = self._repository.state_ref()
        if state.lifecycle == "ended":
            return [client.to_dict() for client in state.clients.values()]
        result = []
        for client in state.clients.values():
            process = self._client_processes.get(client.client_id)
            if process is None:
                client.process_status = "offline"
            else:
                client.process_status = "online" if process.poll() is None else "offline"
                if client.process_status == "offline":
                    client.online = False
            result.append(client.to_dict())
        return result

    def _configure_peers(self, state: SimulationState) -> None:
        peers = [
            {
                "server_id": server.server_id,
                "url": server.url,
                "latitude": server.latitude,
                "longitude": server.longitude,
            }
            for server in state.servers.values()
        ]
        for server in state.servers.values():
            if server.status != "healthy":
                continue
            try:
                self._http_client.configure_peers(server, peers)
            except Exception as exc:
                server.last_error = str(exc)

    def refresh_servers(self) -> list[dict]:
        state = self._repository.state_ref()
        if state.lifecycle in {"ended", "idle"}:
            return [server.to_dict() for server in state.servers.values()]
        result = []
        for server in state.servers.values():
            try:
                status = self._http_client.status(server)
                server.status = status.get("status", "healthy")
                server.lifecycle_status = status.get("lifecycle_status", "running")
                server.health_status = status.get("health_status", server.status)
                server.capacity_tier = status.get("capacity_tier", server.capacity_tier)
                server.load = int(status.get("load", 0))
                server.blacklist_size = int(status.get("blacklist_size", 0))
                server.messages_received = int(status.get("messages_received", 0))
                server.uptime_seconds = float(status.get("uptime_seconds", server.uptime_seconds))
                server.requests_total = int(status.get("requests_total", server.requests_total))
                server.errors_total = int(status.get("errors_total", server.errors_total))
                server.requests_in_flight = int(status.get("requests_in_flight", server.requests_in_flight))
                server.last_request_at = status.get("last_request_at")
                capacity = status.get("capacity", {})
                server.capacity_rps = float(capacity.get("capacity_rps", server.capacity_rps))
                server.utilization = float(capacity.get("utilization", server.utilization))
                server.queue_depth = int(capacity.get("queue_depth", status.get("queue_depth", server.queue_depth)))
                server.queue_rejected = int(capacity.get("queue_rejected", status.get("queue_rejected", server.queue_rejected)))
                server.queue_wait_ms = float(status.get("queue_wait_ms", server.queue_wait_ms))
                server.capacity_pressure = float(capacity.get("pressure", server.capacity_pressure))
                server.slo_breached = bool(server.health_status in {"overloaded", "degraded", "offline"})
                server.fault = status.get("fault", server.fault)
                server.last_error = None
            except Exception as exc:
                server.status = "offline"
                server.last_error = str(exc)
            result.append(server.to_dict())
        return result

    def _reconcile_blacklist(self, state: SimulationState) -> None:
        entries = [entry.to_internal_dict() for entry in state.blacklist.values()]
        if not entries:
            return
        for server in state.servers.values():
            if server.status != "healthy":
                continue
            try:
                self._http_client.reconcile_blacklist(server, entries)
            except Exception as exc:
                server.last_error = str(exc)

    def inject_fault(self, server_id: str, payload: dict) -> dict:
        state = self._repository.state_ref()
        server = state.servers.get(server_id)
        if server is None:
            raise KeyError(f"Servidor {server_id} não encontrado")
        fault = payload.get("fault", payload)
        if not isinstance(fault, dict):
            raise ValueError("fault deve ser um objeto")
        allowed = {"offline", "extra_latency_ms", "drop_rate"}
        if set(fault) - allowed:
            raise ValueError("falha contém campos desconhecidos")
        result = self._http_client.configure(server, {"fault": fault})
        self.refresh_servers()
        self._configure_peers(state)
        self._repository.append_event({"type": "fault_injected", "at": time.time(), "server_id": server_id, "fault": fault, "reason": "laboratório local; nenhum serviço externo afetado"})
        return result

    def shutdown_nodes(self) -> None:
        for process in list(self._processes.values()):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
        self._processes.clear()
        for process in list(self._client_processes.values()):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
        self._client_processes.clear()


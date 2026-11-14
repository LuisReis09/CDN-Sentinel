from __future__ import annotations

import os
import hashlib
import subprocess
import sys
import time
import math
import re
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict

from config import MAX_CLIENTS, MAX_SERVERS, SimulationConfig
from models.entities import CDNServer, SimulationState
from models.entities import Client
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.topology_service import TopologyService
from services.city_lookup_service import CityLookupService
from services.capacity_service import capacity_limits, profile_for_tier, service_metrics
from services.content_provider import default_content_id
from utils.geo import city_with_jitter, haversine_km, load_global_cities


def effective_server_health(server: CDNServer, *, latency_p95_ms: float, slo_p95_ms: float) -> str:
    """Classify the service users observe, not only the process liveness."""
    current = str(server.health_status or server.status)
    if current in {"offline", "stopped", "error"} or server.status in {"offline", "stopped", "error"}:
        return "offline"
    fault = server.fault or {}
    if fault.get("offline"):
        return "offline"
    pressure = max(float(server.utilization or 0.0), float(server.capacity_pressure or 0.0))
    if (
        pressure >= 0.90
        # ``queue_rejected`` is a cumulative counter on real nodes, therefore
        # it is evidence for the dashboard but cannot by itself keep a node
        # red forever after it has recovered.
        or int(server.queue_depth or 0) >= 6
        or float(server.queue_wait_ms or 0.0) >= 150.0
        or latency_p95_ms > max(slo_p95_ms * 1.5, slo_p95_ms + 100.0)
    ):
        return "overloaded"
    if (
        current == "degraded"
        or bool(fault.get("extra_latency_ms") or fault.get("drop_rate"))
        or pressure >= 0.75
        or int(server.queue_depth or 0) > 0
        or float(server.queue_wait_ms or 0.0) >= 50.0
        or latency_p95_ms > slo_p95_ms
    ):
        return "degraded"
    return "healthy"


class SimulationController:
    def __init__(self, repository: SimulationRepository, http_client: CDNHttpClient) -> None:
        self._repository = repository
        self._http_client = http_client
        self._topology = TopologyService()
        self._processes: Dict[str, subprocess.Popen] = {}
        self._client_processes: Dict[str, subprocess.Popen] = {}
        self._secret_key = "local-development-secret"
        self._city_lookup = CityLookupService()
        self._initialization_lock = threading.RLock()
        self._initialization = {
            "in_progress": False,
            "progress_pct": 0,
            "phase": "idle",
            "detail": "Aguardando inicialização",
        }
        self._real_node_process_limit = max(0, int(os.getenv("CDN_REAL_NODE_LIMIT", "64")))
        self._real_client_process_limit = max(0, int(os.getenv("CDN_REAL_CLIENT_LIMIT", "32")))

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def initialize(self, payload: dict) -> dict:
        self._set_initialization_progress(True, 3, "validating", "Validando parâmetros da simulação")
        try:
            config = SimulationConfig.from_payload(payload)
        except Exception:
            self._set_initialization_progress(False, 0, "error", "Parâmetros inválidos")
            raise
        self._secret_key = config.secret_key
        self._http_client.configure_secret(config.secret_key)
        self._set_initialization_progress(True, 8, "stopping", "Encerrando processos da execução anterior")
        self.shutdown_nodes()
        self._set_initialization_progress(True, 16, "topology", f"Gerando {config.num_servers} servidores e {config.num_clients} clientes")
        servers, clients = self._topology.build(config)
        for index, server in enumerate(servers.values()):
            if index >= self._real_node_process_limit:
                server.process_mode = "virtual"
        state = SimulationState(initialized=True, started_at=time.time(), updated_at=time.time(), config=config.to_dict(), servers=servers, clients=clients, lifecycle="starting")
        self._repository.replace(state)
        self._repository.append_event({
            "type": "simulation_initialized",
            "at": time.time(),
            "config": config.to_dict(),
            "node_protocol": "HTTP/1.1",
            "routing_algorithm": "Haversine / nearest healthy CDN",
            "gossip_protocol": "hierarchical origin-regional-edge gossip",
            "internal_encryption": "AES-256-GCM envelope + HMAC-SHA256 signature",
            "watermark_algorithm": "AES-256-GCM + HMAC-SHA256",
        })

        self._set_initialization_progress(True, 28, "nodes", f"Preparando {min(len(servers), self._real_node_process_limit)} nós HTTP e {max(0, len(servers) - self._real_node_process_limit)} nós virtuais")
        if self._real_node_process_limit:
            node_workers = min(max(1, len(servers)), self._real_node_process_limit, 16)
            with ThreadPoolExecutor(max_workers=node_workers, thread_name_prefix="cdn-init") as executor:
                futures = [executor.submit(self._start_node, server, config) for server in servers.values()]
                completed = 0
                for future in as_completed(futures):
                    future.result()
                    completed += 1
                    self._set_initialization_progress(True, 28 + int(35 * completed / max(1, len(futures))), "nodes", f"Nós prontos: {completed}/{len(futures)}")
        else:
            for server in servers.values():
                self._start_node(server, config)
            self._set_initialization_progress(True, 63, "nodes", "Todos os nós foram registrados como capacidade virtual")
        self._set_initialization_progress(True, 68, "clients", f"Registrando {len(clients)} clientes virtuais")
        for index, client in enumerate(clients.values()):
            self._start_client(client, index)
            if len(clients) <= 5_000 and index % max(1, len(clients) // 10) == 0:
                self._set_initialization_progress(True, 68 + int(15 * (index + 1) / max(1, len(clients))), "clients", f"Clientes prontos: {index + 1}/{len(clients)}")
        self._set_initialization_progress(True, 84, "network", "Configurando vizinhança e capacidade da malha")
        self._configure_peers(state)
        self.refresh_servers()
        self._reconcile_blacklist(state)
        state.lifecycle = "running" if any(server.status in {"healthy", "degraded"} for server in state.servers.values()) else "error"
        state.updated_at = time.time()
        self._repository.append_event({"type": "simulation_running" if state.lifecycle == "running" else "simulation_start_failed", "at": time.time(), "lifecycle": state.lifecycle})
        self._set_initialization_progress(False, 100, "ready", "Simulação pronta")
        malicious_count = sum(1 for client in clients.values() if client.malicious)
        return {
            "initialized": True,
            "configuration": config.to_dict(),
            "malicious_clients": malicious_count,
            "servers": [server.to_dict() for server in servers.values()],
            "clients": [client.to_dict() for client in list(clients.values())[:2_000]],
            "clients_total": len(clients),
            "clients_truncated": len(clients) > 2_000,
        }

    def _set_initialization_progress(self, in_progress: bool, progress_pct: int, phase: str, detail: str) -> None:
        with self._initialization_lock:
            self._initialization = {
                "in_progress": in_progress,
                "progress_pct": max(0, min(100, int(progress_pct))),
                "phase": phase,
                "detail": detail,
            }

    def initialization_progress(self) -> dict:
        with self._initialization_lock:
            return dict(self._initialization)

    def update(self, payload: dict) -> dict:
        state = self._repository.state_ref()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("A simulação ainda não foi inicializada")
        merged = {**state.config, **payload, "secret_key": self._secret_key}
        config = SimulationConfig.from_payload(merged)
        rebuild_keys = ("base_node_port", "base_client_port", "seed")
        rebuild_changed = any(
            key in payload and payload[key] != state.config.get(key)
            for key in rebuild_keys
        )
        if rebuild_changed:
            return self.initialize(merged)
        # Resize in place so the simulation id, worker threads, traffic
        # history and live observability stream remain intact.
        if config.num_servers != len(state.servers):
            self._resize_servers(config.num_servers, config)
        if config.num_clients != len(state.clients):
            self._resize_clients(config.num_clients, config)
        state.config.update(config.to_dict())
        for client in state.clients.values():
            digest = hashlib.sha256(f"{client.client_id}:{config.malicious_probability}".encode()).digest()
            client.malicious = int.from_bytes(digest[:8], "big") / 2**64 < config.malicious_probability
        for server in state.servers.values():
            if server.status == "healthy" and server.process_mode == "http":
                try:
                    self._http_client.configure(server, {"latency_factor": config.latency_factor})
                except Exception as exc:
                    server.last_error = str(exc)
        self._repository.update_config(config.to_dict())
        self._repository.append_event({"type": "simulation_config_updated", "at": time.time(), "changes": payload})
        return self.status()

    def _resize_clients(self, target: int, config: SimulationConfig) -> None:
        state = self._repository.state_ref()
        target = max(1, min(MAX_CLIENTS, int(target)))
        rng = random.Random(config.seed + len(state.clients) + target)
        cities = list(load_global_cities())

        while len(state.clients) < target:
            sequence = len(state.clients) + 1
            client_id = f"client-{sequence:04d}"
            while client_id in state.clients:
                sequence += 1
                client_id = f"client-{sequence:04d}"
            city = cities[(sequence + len(state.servers) + config.seed) % len(cities)]
            latitude, longitude = city_with_jitter(rng, city)
            client = Client(
                client_id=client_id,
                latitude=latitude,
                longitude=longitude,
                city=city.name,
                malicious=rng.random() < config.malicious_probability,
            )
            self._repository.add_client(client)
            self._start_client(client, len(state.clients) - 1)
            self._repository.append_event({
                "type": "client_added",
                "at": time.time(),
                "client_id": client_id,
                "latitude": latitude,
                "longitude": longitude,
                "reason": "live_configuration_resize",
            })

        for client_id in list(state.clients.keys())[target:]:
            client = state.clients.pop(client_id)
            self._stop_client_process(client_id)
            client.active = False
            client.online = False
            client.process_status = "stopped"
            self._repository.append_event({
                "type": "client_removed",
                "at": time.time(),
                "client_id": client_id,
                "reason": "live_configuration_resize",
            })

    def _resize_servers(self, target: int, config: SimulationConfig) -> None:
        state = self._repository.state_ref()
        target = max(1, min(MAX_SERVERS, int(target)))
        cities = list(load_global_cities())
        rng = random.Random(config.seed + len(state.servers) + target)

        for server_id in list(state.servers.keys())[target:]:
            server = state.servers.get(server_id)
            if server is None:
                continue
            if server.status not in {"stopped", "offline"}:
                self.retire_server(server_id)
            else:
                process = self._processes.pop(server_id, None)
                if process and process.poll() is None:
                    process.terminate()
            state.servers.pop(server_id, None)

        used_ports = {server.port for server in state.servers.values()}
        while len(state.servers) < target:
            sequence = len(state.servers) + 1
            server_id = f"cdn-{sequence:02d}"
            while server_id in state.servers:
                sequence += 1
                server_id = f"cdn-{sequence:02d}"
            city = cities[(sequence + config.seed) % len(cities)]
            port = config.base_node_port + sequence - 1
            while port in used_ports:
                port += 1
            latitude = city.latitude + rng.uniform(-0.12, 0.12)
            longitude = city.longitude + rng.uniform(-0.12, 0.12)
            self.add_server({
                "server_id": server_id,
                "port": port,
                "latitude": latitude,
                "longitude": longitude,
                "city": city.name,
                "capacity_tier": config.node_tier,
            })
            used_ports.add(port)

        self._configure_peers(state)
        self.refresh_servers()

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
        self._refresh_client_processes()
        state = self._repository.snapshot_without_clients()
        client_summary = self._repository.client_summary()
        now = time.time()
        active_clients = client_summary["active"]
        demand_rps = active_clients * float(state.config.get("demand_rps_per_client", 0.25))
        available_servers = sum(1 for server in state.servers.values() if server.status in {"healthy", "degraded", "overloaded"})
        capacity_values = [float(server.capacity_rps) for server in state.servers.values() if server.server_id and server.status in {"healthy", "degraded", "overloaded"} and server.capacity_rps > 0]
        if not capacity_values and available_servers:
            fallback_profile = profile_for_tier(str(state.config.get("node_tier", "basic")))
            capacity_values = [capacity_limits(fallback_profile)["capacity_rps"]] * available_servers
        capacity = sum(capacity_values)
        utilization = demand_rps / capacity if capacity else 0
        queue_depth = sum(server.queue_depth for server in state.servers.values())
        queue_rejected = sum(server.queue_rejected for server in state.servers.values())
        queue_wait_ms = round(sum(server.queue_wait_ms for server in state.servers.values()) / len(state.servers), 1) if state.servers else 0.0
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
        monthly_variable_cost = active_clients * 2.0
        monthly_cost = monthly_server_cost + monthly_fixed_cost + monthly_variable_cost
        paying_clients = max(1, client_summary["total"]) if client_summary["total"] else 0
        configured_price = float(state.config.get("monthly_client_price_usd", state.config.get("monthly_client_price_unit", 25.0)))
        break_even_price = monthly_cost / paying_clients if paying_clients else 0
        minimum_price = break_even_price * 1.2 if paying_clients else 0
        revenue = client_summary["paying_active"] * configured_price
        observed_requests = sum(int(item.get("request_count", 1)) for item in recent_traffic)
        observed_rps = round(observed_requests / window_seconds, 3)
        total_requests = sum(int(server.requests_total) for server in state.servers.values())
        successful_requests = max(0, total_requests - error_count)
        success_rate_pct = round(100 * successful_requests / total_requests, 2) if total_requests else None
        slo_p95_ms = float(state.config.get("slo_p95_ms", 250.0))
        slo_success_rate_pct = float(state.config.get("slo_success_rate_pct", 99.0))
        slo_compliant = bool(observed_requests and p95_latency <= slo_p95_ms and (success_rate_pct is None or success_rate_pct >= slo_success_rate_pct))
        server_latencies: dict[str, list[float]] = {server_id: [] for server_id in state.servers}
        for item in recent_traffic:
            server_id = str(item.get("server_id") or "")
            if server_id in server_latencies:
                server_latencies[server_id].append(
                    float(item.get("end_to_end_ms", item.get("http_rtt_ms", 0.0)))
                )
        # The aggregate demand model is the source of pressure for the
        # orchestration view.  Reflect it on every participating node even
        # before an optional local HTTP request reaches that node.
        modeled_pressure = demand_rps / max(capacity, 1.0)
        for server in state.servers.values():
            if server.status not in {"healthy", "degraded", "overloaded"}:
                continue
            modeled_queue_depth = max(0, round((modeled_pressure - 0.90) * 20))
            modeled_queue_wait_ms = round(max(0.0, modeled_pressure - 0.75) * 120, 3)
            # The orchestration screen uses a common aggregate-demand model
            # for virtual and local HTTP nodes.  Assigning (rather than
            # accumulating) these derived fields lets a recovered node turn
            # green immediately after a capacity action; measured request
            # latency and error counters remain separate evidence below.
            server.utilization = round(modeled_pressure, 3)
            server.capacity_pressure = round(modeled_pressure, 3)
            server.load = min(16, round(modeled_pressure * 16))
            server.queue_depth = modeled_queue_depth
            server.queue_wait_ms = modeled_queue_wait_ms
        health_by_server: dict[str, str] = {}
        live_servers = self._repository.state_ref().servers
        for server_id, server in state.servers.items():
            server_p95 = percentile(sorted(server_latencies.get(server_id, [])), 0.95)
            health = effective_server_health(
                server, latency_p95_ms=server_p95, slo_p95_ms=slo_p95_ms,
            )
            health_by_server[server_id] = health
            server.status = health
            server.health_status = health
            server.latency_p95_ms = server_p95
            server.slo_breached = health != "healthy"
            live_server = live_servers.get(server_id)
            if live_server is not None:
                live_server.status = health
                live_server.health_status = health
                live_server.latency_p95_ms = server_p95
                live_server.utilization = server.utilization
                live_server.capacity_pressure = server.capacity_pressure
                live_server.load = server.load
                live_server.queue_depth = server.queue_depth
                live_server.queue_wait_ms = server.queue_wait_ms
                live_server.slo_breached = health != "healthy"

        healthy_servers = sum(health == "healthy" for health in health_by_server.values())
        degraded_servers = sum(health == "degraded" for health in health_by_server.values())
        overloaded_servers = sum(health == "overloaded" for health in health_by_server.values())
        available_servers = sum(health in {"healthy", "degraded", "overloaded"} for health in health_by_server.values())
        if not available_servers:
            profile = "indisponível"
            message = "Nenhum nó disponível para atender a demanda"
        elif utilization >= 1.0 or queue_depth > 0:
            profile = "gargalo"
            message = "Demanda próxima ou acima da capacidade; a CDN já perde folga operacional"
        elif utilization >= 0.75 or p95_latency > slo_p95_ms:
            profile = "alerta"
            message = "Pressão ou latência acima do alvo: revise capacidade, cache e balanceamento"
        elif healthy_servers < available_servers:
            profile = "degradada"
            message = "Há nós degradados; a entrega continua disponível, mas com menor margem"
        elif healthy_servers >= max(1, active_clients * 2):
            profile = "sobredimensionada"
            message = "Muitos nós para a demanda atual: a qualidade está boa, mas o custo é alto"
        else:
            profile = "equilibrada"
            message = "Capacidade, latência e disponibilidade estão equilibradas"

        node_health = (
            healthy_servers + (degraded_servers * 0.60) + (overloaded_servers * 0.25)
        ) / max(1, len(state.servers))
        capacity_health = max(0.05, 1.0 - max(0.0, utilization - 0.70) / 0.80)
        latency_health = (
            max(0.05, 1.0 - max(0.0, p95_latency - slo_p95_ms) / max(1.0, slo_p95_ms * 1.5))
            if observed_requests else 1.0
        )
        success_health = (
            max(0.05, min(1.0, success_rate_pct / max(1.0, slo_success_rate_pct)))
            if success_rate_pct is not None else 1.0
        )
        health_score_pct = round(100 * min(node_health, capacity_health, latency_health, success_health), 1)
        self._record_metric(
            state,
            now,
            {
                "blacklist_total": len(state.blacklist),
                "total_requests": total_requests,
                "total_errors": error_count,
                "average_latency_ms": average_latency,
                "p95_latency_ms": p95_latency,
                "healthy_servers": healthy_servers,
                "available_servers": available_servers,
                "servers_total": len(state.servers),
                "health_score_pct": health_score_pct,
                "server_requests": {
                    server.server_id: int(server.requests_total)
                    for server in state.servers.values()
                },
            },
        )
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
            "tick_interval_seconds": round(float(state.config.get("tick_interval_seconds", 1.25)), 2),
            "servers_total": len(state.servers),
            "clients_total": client_summary["total"],
            "malicious_clients": client_summary["malicious"],
            "initialization": self.initialization_progress(),
            "blacklisted_total": len(state.blacklist),
            "scalability": {
                "active_clients": active_clients,
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
                "observed_request_count": observed_requests,
                "observed_rps": observed_rps,
                "observed_errors": error_count,
                "success_rate_pct": success_rate_pct,
                "slo_p95_ms": slo_p95_ms,
                "slo_success_rate_pct": slo_success_rate_pct,
                "slo_compliant": slo_compliant,
                "health_score_pct": health_score_pct,
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

    def _record_metric(self, state: SimulationState, now: float, values: dict) -> None:
        """Keep a bounded, cumulative series for dashboard evolution charts."""
        last = state.metrics_history[-1] if state.metrics_history else None
        if last and now - float(last.get("at", 0)) < 1.0:
            return
        self._repository.append_metric(
            {
                "at": now,
                "elapsed_seconds": round(max(0.0, now - float(state.started_at or now)), 1),
                **values,
            }
        )

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
        if len(state.clients) >= MAX_CLIENTS:
            raise ValueError(f"A simulação já atingiu o limite de {MAX_CLIENTS:,} clientes".replace(",", "."))
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
        self._start_client(client, len(state.clients) - 1)
        self._repository.update_config({"num_clients": len(state.clients)})
        self._repository.append_event({"type": "client_added", "at": time.time(), "client_id": client_id, "latitude": latitude, "longitude": longitude})
        return client.to_dict()

    def record_client_feedback(self, client_id: str, payload: dict) -> dict:
        state = self._repository.state_ref()
        client = state.clients.get(client_id)
        if client is None:
            raise KeyError(f"Cliente {client_id} não encontrado")
        if not isinstance(payload, dict):
            raise ValueError("feedback deve ser um objeto")
        liked = payload.get("liked")
        if not isinstance(liked, bool):
            raise ValueError("liked deve ser booleano")
        rating = payload.get("rating", 5 if liked else 2)
        try:
            rating = int(rating)
        except (TypeError, ValueError) as exc:
            raise ValueError("rating deve ser um inteiro entre 1 e 5") from exc
        if not 1 <= rating <= 5:
            raise ValueError("rating deve estar entre 1 e 5")
        video_id = str(payload.get("video_id") or state.config.get("video_id") or default_content_id())
        chunk_number = payload.get("chunk_number")
        latest_watch = next(
            (
                item
                for item in reversed(client.watch_history)
                if item.get("video_id") == video_id
                and (chunk_number is None or int(item.get("chunk_number", -1)) == int(chunk_number))
            ),
            None,
        )
        latency_ms = float((latest_watch or {}).get("latency_ms", 0.0))
        latency_related = bool(latency_ms >= 250.0 and not liked)
        feedback = {
            "at": time.time(),
            "video_id": video_id,
            "chunk_number": int(chunk_number) if chunk_number is not None else (latest_watch or {}).get("chunk_number"),
            "liked": liked,
            "rating": rating,
            "comment": str(payload.get("comment", ""))[:280],
            "latency_ms": round(latency_ms, 3),
            "latency_related": latency_related,
        }
        client.feedback_history.append(feedback)
        client.feedback_history = client.feedback_history[-100:]
        client.likes += int(liked)
        client.dislikes += int(not liked)
        client.feedback_score = round(sum(item["rating"] for item in client.feedback_history) / len(client.feedback_history) * 20.0, 2)
        client.feedback_latency_avg_ms = round(sum(float(item.get("latency_ms", 0.0)) for item in client.feedback_history) / len(client.feedback_history), 3)
        for watch in reversed(client.watch_history):
            if watch.get("video_id") == video_id and (chunk_number is None or int(watch.get("chunk_number", -1)) == int(chunk_number)):
                watch["liked"] = liked
                break
        self._repository.append_event({"type": "client_feedback", "at": feedback["at"], "client_id": client_id, "video_id": video_id, "liked": liked, "rating": rating, "latency_ms": latency_ms, "latency_related": latency_related})
        return {"client": client.to_dict(), "feedback": feedback}

    def add_server(self, payload: dict) -> dict:
        state = self._repository.state_ref()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("A simulação ainda não foi inicializada")
        if len(state.servers) >= MAX_SERVERS:
            raise ValueError(f"A simulação já atingiu o limite de {MAX_SERVERS} servidores")
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
            capacity_tier=str(payload.get("capacity_tier") or state.config.get("node_tier", "basic")),
        )
        if len(state.servers) >= self._real_node_process_limit:
            server.process_mode = "virtual"
        self._repository.add_server(server)
        config = SimulationConfig.from_payload({**state.config, "secret_key": self._secret_key})
        self._start_node(server, config)
        self._configure_peers(state)
        self.refresh_servers()
        self._reconcile_blacklist(state)
        self._repository.update_config({"num_servers": len(state.servers)})
        self._repository.append_event({"type": "server_added", "at": time.time(), "server_id": server_id, "latitude": latitude, "longitude": longitude})
        return server.to_dict()

    def update_server_capacity(self, server_id: str, tier: str) -> dict:
        state = self._repository.state_ref()
        server = state.servers.get(server_id)
        if server is None:
            raise KeyError(f"Servidor {server_id} não encontrado")
        if tier not in {"basic", "standard", "pro", "enterprise"}:
            raise ValueError("tier inválido")
        server.lifecycle_status = "recovering"
        result = self._http_client.configure(server, {"capacity_tier": tier})
        server.capacity_tier = tier
        server.lifecycle_status = "running"
        self.refresh_servers()
        self._configure_peers(state)
        self._repository.append_event({"type": "server_capacity_updated", "at": time.time(), "server_id": server_id, "tier": tier, "reason": "ação de gestão com manutenção didática"})
        return {"server": server.to_dict(), "node": result}

    def retire_server(self, server_id: str) -> dict:
        state = self._repository.state_ref()
        server = state.servers.get(server_id)
        if server is None:
            raise KeyError(f"Servidor {server_id} não encontrado")
        active = [item for item in state.servers.values() if item.status not in {"stopped", "offline"}]
        if len(active) <= 1:
            raise ValueError("não é permitido retirar o último nó operacional")
        server.lifecycle_status = "draining"
        process = self._processes.pop(server_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        server.lifecycle_status = "stopped"
        server.status = "stopped"
        server.health_status = "offline"
        self._configure_peers(state)
        self._repository.append_event({"type": "server_retired", "at": time.time(), "server_id": server_id, "reason": "descomissionamento seguro por gestão"})
        return server.to_dict()

    def _start_node(self, server: CDNServer, config: SimulationConfig) -> None:
        if server.process_mode == "virtual":
            profile = profile_for_tier(server.capacity_tier or config.node_tier)
            limits = capacity_limits(profile)
            server.process_id = None
            server.status = "healthy"
            server.lifecycle_status = "virtual"
            server.health_status = "healthy"
            server.capacity_rps = float(limits["capacity_rps"])
            server.last_error = None
            return
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

    def _start_client(self, client: Client, index: int = 0) -> None:
        if index >= self._real_client_process_limit:
            client.process_id = None
            client.process_status = "virtual"
            return
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

    def _stop_client_process(self, client_id: str) -> None:
        process = self._client_processes.pop(client_id, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def _refresh_client_processes(self) -> None:
        state = self._repository.state_ref()
        for client_id, process in self._client_processes.items():
            client = state.clients.get(client_id)
            if client is None:
                continue
            client.process_status = "online" if process.poll() is None else "offline"
            # Process telemetry is not a viewer-session state.  A client
            # remains active in the simulation even if its optional local
            # placeholder process has ended.
            if client.active and state.lifecycle == "running":
                client.online = True

    def refresh_clients(self, limit: int | None = None) -> list[dict]:
        state = self._repository.state_ref()
        if state.lifecycle == "ended":
            clients = list(state.clients.values())
            return [client.to_dict() for client in clients[:limit]] if limit is not None else [client.to_dict() for client in clients]
        self._refresh_client_processes()
        result = []
        clients = list(state.clients.values()) if limit is None else list(state.clients.values())[:limit]
        for client in clients:
            if client.client_id not in self._client_processes and client.process_status == "starting":
                client.process_status = "virtual"
            result.append(client.to_dict())
        return result

    def _configure_peers(self, state: SimulationState) -> None:
        self._build_peer_graph(state.servers)
        peer_directory = {
            server.server_id: {
                "server_id": server.server_id,
                "url": server.url,
                "latitude": server.latitude,
                "longitude": server.longitude,
                "role": server.role,
                "region": server.region,
            }
            for server in state.servers.values()
            if server.process_mode == "http"
        }

        def peers_for(server: CDNServer) -> list[dict]:
            return [peer_directory[peer_id] for peer_id in server.peer_ids if peer_id in peer_directory]

        eligible = [server for server in state.servers.values() if server.status == "healthy" and server.process_mode == "http"]

        def configure(server: CDNServer):
            try:
                self._http_client.configure_peers(server, peers_for(server))
                return server, None
            except Exception as exc:
                return server, exc

        if len(eligible) <= 1:
            configured = [configure(server) for server in eligible]
        else:
            with ThreadPoolExecutor(max_workers=min(16, len(eligible)), thread_name_prefix="cdn-peers") as executor:
                configured = list(executor.map(configure, eligible))
        for server, error in configured:
            if error is not None:
                server.last_error = str(error)

    def _build_peer_graph(self, servers: dict[str, CDNServer]) -> None:
        """Build a bounded origin/regional/edge graph instead of a full mesh."""

        active = [server for server in servers.values() if server.process_mode == "http"]
        neighbors = {server.server_id: set() for server in active}
        if len(active) < 2:
            for server in active:
                server.peer_ids = []
            return

        origin = next((server for server in active if server.role == "origin"), active[0])
        regionals = [server for server in active if server.role == "regional" and server.server_id != origin.server_id]

        def nearest(source: CDNServer, candidates: list[CDNServer], limit: int) -> list[CDNServer]:
            return sorted(
                candidates,
                key=lambda candidate: (
                    haversine_km(source.latitude, source.longitude, candidate.latitude, candidate.longitude),
                    candidate.server_id,
                ),
            )[:limit]

        def connect(left: CDNServer, right: CDNServer) -> None:
            if left.server_id == right.server_id:
                return
            neighbors[left.server_id].add(right.server_id)
            neighbors[right.server_id].add(left.server_id)

        for regional in regionals:
            connect(origin, regional)

        for server in active:
            if server.server_id == origin.server_id or server.server_id in {item.server_id for item in regionals}:
                continue
            parents = nearest(server, regionals, 2)
            if not parents:
                parents = nearest(server, [origin], 1)
            for parent in parents:
                connect(server, parent)

        for server in active:
            server.peer_ids = sorted(neighbors[server.server_id])

    def refresh_servers(self) -> list[dict]:
        state = self._repository.state_ref()
        if state.lifecycle in {"ended", "idle"}:
            return [server.to_dict() for server in state.servers.values()]
        virtual_servers = []
        http_servers = []
        for server in state.servers.values():
            if server.process_mode == "virtual":
                profile = profile_for_tier(server.capacity_tier or str(state.config.get("node_tier", "basic")))
                limits = capacity_limits(profile)
                server.status = "offline" if server.fault.get("offline") else ("degraded" if server.fault.get("extra_latency_ms") or server.fault.get("drop_rate") else "healthy")
                server.lifecycle_status = "virtual"
                server.health_status = server.status
                server.capacity_rps = float(limits["capacity_rps"])
                server.capacity_pressure = float(server.utilization)
                server.slo_breached = server.status in {"offline", "degraded", "overloaded"}
                virtual_servers.append(server)
            else:
                http_servers.append(server)

        def fetch(server: CDNServer):
            try:
                return server, self._http_client.status(server), None
            except Exception as exc:
                return server, None, exc

        if http_servers:
            with ThreadPoolExecutor(max_workers=min(16, len(http_servers)), thread_name_prefix="cdn-status") as executor:
                fetched = list(executor.map(fetch, http_servers))
        else:
            fetched = []
        for server, status, error in fetched:
            if error is not None:
                server.status = "offline"
                server.last_error = str(error)
                continue
            try:
                server.status = status.get("status", "healthy")
                server.lifecycle_status = status.get("lifecycle_status", "running")
                server.health_status = status.get("health_status", server.status)
                server.capacity_tier = status.get("capacity_tier", server.capacity_tier)
                server.peer_ids = list(status.get("peers", server.peer_ids))
                server.load = int(status.get("load", 0))
                server.blacklist_size = int(status.get("blacklist_size", 0))
                server.messages_received = int(status.get("messages_received", 0))
                server.uptime_seconds = float(status.get("uptime_seconds", server.uptime_seconds))
                # A local node reports only HTTP traffic.  Do not let a
                # status poll overwrite the aggregate simulator counter.
                server.http_requests_total = int(
                    status.get("requests_total", server.http_requests_total)
                )
                server.http_errors_total = int(
                    status.get("errors_total", server.http_errors_total)
                )
                server.requests_total = (
                    server.simulated_requests_total + server.http_requests_total
                )
                server.errors_total = (
                    server.simulated_errors_total + server.http_errors_total
                )
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
        return [server.to_dict() for server in [*virtual_servers, *http_servers]]

    def _reconcile_blacklist(self, state: SimulationState) -> None:
        entries = [entry.to_internal_dict() for entry in state.blacklist.values()]
        if not entries:
            return
        for server in state.servers.values():
            if server.status != "healthy" or server.process_mode != "http":
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
        if not isinstance(payload, dict):
            raise ValueError("o cenário de falha deve ser um objeto JSON")
        fault = payload.get("fault", payload)
        if not isinstance(fault, dict):
            raise ValueError("fault deve ser um objeto")
        allowed = {"offline", "extra_latency_ms", "drop_rate"}
        if set(fault) - allowed:
            raise ValueError("falha contém campos desconhecidos")
        if not fault:
            raise ValueError("informe pelo menos um efeito de falha")
        normalized_fault: dict[str, object] = {}
        if "offline" in fault:
            value = fault["offline"]
            if not isinstance(value, bool):
                raise ValueError("offline deve ser booleano")
            normalized_fault["offline"] = value
        for field, minimum, maximum in (("extra_latency_ms", 0.0, 30_000.0), ("drop_rate", 0.0, 1.0)):
            if field not in fault:
                continue
            value = fault[field]
            if isinstance(value, bool):
                raise ValueError(f"{field} deve ser numérico")
            try:
                numeric = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"{field} deve ser numérico") from exc
            if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
                raise ValueError(f"{field} deve estar entre {minimum:g} e {maximum:g}")
            normalized_fault[field] = numeric
        if server.process_mode == "virtual":
            server.fault.update({
                "offline": bool(normalized_fault.get("offline", server.fault.get("offline", False))),
                "extra_latency_ms": float(normalized_fault.get("extra_latency_ms", server.fault.get("extra_latency_ms", 0.0))),
                "drop_rate": float(normalized_fault.get("drop_rate", server.fault.get("drop_rate", 0.0))),
            })
            result = {"server_id": server.server_id, "fault": dict(server.fault), "process_mode": "virtual"}
        else:
            try:
                result = self._http_client.configure(server, {"fault": normalized_fault})
            except Exception as exc:
                server.status = "offline"
                server.health_status = "offline"
                server.last_error = str(exc)
                raise RuntimeError(f"não foi possível configurar {server.server_id}: processo CDN indisponível") from exc
        self.refresh_servers()
        self._configure_peers(state)
        self._repository.append_event({"type": "fault_injected", "at": time.time(), "server_id": server_id, "fault": normalized_fault, "reason": "laboratório local; nenhum serviço externo afetado"})
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



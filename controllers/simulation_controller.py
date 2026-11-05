from __future__ import annotations

import os
import hashlib
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

from config import SimulationConfig
from models.entities import CDNServer, SimulationState
from models.entities import Client
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.topology_service import TopologyService
from services.city_lookup_service import CityLookupService


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
        self.shutdown_nodes()
        servers, clients = self._topology.build(config)
        state = SimulationState(initialized=True, started_at=time.time(), updated_at=time.time(), config=config.to_dict(), servers=servers, clients=clients)
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
        self.refresh_clients()
        malicious_count = sum(1 for client in clients.values() if client.malicious)
        return {
            "initialized": True,
            "configuration": config.to_dict(),
            "malicious_clients": malicious_count,
            "servers": [server.to_dict() for server in servers.values()],
            "clients": [client.to_dict() for client in clients.values()],
        }

    def update(self, payload: dict) -> dict:
        state = self._repository.snapshot()
        if not state.initialized:
            raise RuntimeError("A simulação ainda não foi inicializada")
        structural = {key for key in ("num_servers", "num_clients", "base_node_port", "base_client_port") if key in payload}
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
        self._repository.set_paused(True)
        self._repository.append_event({"type": "simulation_paused", "at": time.time()})
        return self.status()

    def resume(self) -> dict:
        self._repository.set_paused(False)
        self._repository.append_event({"type": "simulation_resumed", "at": time.time()})
        return self.status()

    def status(self) -> dict:
        state = self._repository.snapshot()
        self.refresh_clients()
        healthy_servers = sum(1 for server in state.servers.values() if server.status == "healthy")
        online_clients = sum(1 for client in state.clients.values() if client.active and client.online)
        capacity_per_server = 8
        capacity = healthy_servers * capacity_per_server
        utilization = online_clients / capacity if capacity else 0
        if not healthy_servers:
            profile = "indisponível"
            message = "Nenhum nó saudável para atender a demanda"
        elif utilization > 1:
            profile = "gargalo"
            message = "Demanda acima da capacidade: filas e latência tendem a crescer"
        elif healthy_servers >= max(1, online_clients * 2):
            profile = "sobredimensionada"
            message = "Muitos nós para poucos clientes: custo operacional elevado"
        else:
            profile = "equilibrada"
            message = "Capacidade compatível com a demanda observada"
        latencies = [float(item.get("latency_ms", 0)) for item in state.traffic if item.get("latency_ms") is not None]
        ordered_latencies = sorted(latencies)
        p95_index = min(len(ordered_latencies) - 1, max(0, int(len(ordered_latencies) * 0.95) - 1)) if ordered_latencies else 0
        average_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
        p95_latency = round(ordered_latencies[p95_index], 1) if ordered_latencies else 0
        monthly_server_cost = healthy_servers * float(state.config.get("monthly_server_cost_usd", state.config.get("monthly_server_cost_unit", 100.0)))
        monthly_fixed_cost = float(state.config.get("monthly_fixed_cost_usd", state.config.get("monthly_fixed_cost_unit", 150.0)))
        monthly_variable_cost = online_clients * 2.0
        monthly_cost = monthly_server_cost + monthly_fixed_cost + monthly_variable_cost
        paying_clients = max(1, len(state.clients)) if state.clients else 0
        configured_price = float(state.config.get("monthly_client_price_usd", state.config.get("monthly_client_price_unit", 25.0)))
        break_even_price = monthly_cost / paying_clients if paying_clients else 0
        minimum_price = break_even_price * 1.2 if paying_clients else 0
        revenue = len(state.clients) * configured_price
        return {
            "initialized": state.initialized,
            "paused": state.paused,
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
                "capacity_per_server": capacity_per_server,
                "total_capacity": capacity,
                "utilization": round(utilization, 3),
                "profile": profile,
                "message": message,
                "estimated_monthly_cost_usd": round(monthly_cost, 2),
                "estimated_queue_latency_ms": round(12 + max(0, utilization - 0.75) * 100, 1),
                "average_latency_ms": average_latency,
                "p95_latency_ms": p95_latency,
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

    def add_client(self, payload: dict) -> dict:
        state = self._repository.snapshot()
        if not state.initialized:
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
        client_id = str(payload.get("client_id") or f"client-{len(state.clients) + 1:04d}")
        client = Client(
            client_id=client_id,
            latitude=latitude,
            longitude=longitude,
            city=str(payload.get("city") or self._city_lookup.lookup(latitude, longitude)),
            malicious=bool(payload.get("malicious", False)),
        )
        self._repository.add_client(client)
        self._start_client(client)
        self._repository.update_config({"num_clients": len(state.clients)})
        self._repository.append_event({"type": "client_added", "at": time.time(), "client_id": client_id, "latitude": latitude, "longitude": longitude})
        return client.to_dict()

    def add_server(self, payload: dict) -> dict:
        state = self._repository.snapshot()
        if not state.initialized:
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
        server_id = str(payload.get("server_id") or f"cdn-{len(state.servers) + 1:02d}")
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
        state = self._repository.snapshot()
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
            if server.status == "healthy"
        ]
        for server in state.servers.values():
            if server.status != "healthy":
                continue
            try:
                self._http_client.configure_peers(server, peers)
            except Exception as exc:
                server.last_error = str(exc)

    def refresh_servers(self) -> list[dict]:
        state = self._repository.snapshot()
        result = []
        for server in state.servers.values():
            try:
                status = self._http_client.status(server)
                server.status = status.get("status", "healthy")
                server.load = int(status.get("load", 0))
                server.blacklist_size = int(status.get("blacklist_size", 0))
                server.messages_received = int(status.get("messages_received", 0))
                server.last_error = None
            except Exception as exc:
                server.status = "offline"
                server.last_error = str(exc)
            result.append(server.to_dict())
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


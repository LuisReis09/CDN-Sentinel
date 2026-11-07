from __future__ import annotations

import random
import threading
import time
import uuid

from repositories.in_memory import SimulationRepository
from services.stream_service import ClientOfflineError, SimulationPausedError, StreamService
from utils.geo import haversine_km


class ClientActivityService:
    """Advances one shared simulation tick and produces client session churn."""

    def __init__(self, repository: SimulationRepository, stream_service: StreamService, interval_seconds: float = 2.5) -> None:
        self._repository = repository
        self._stream_service = stream_service
        self._interval_seconds = interval_seconds
        self._tick_interval_seconds = interval_seconds
        self._random = random.Random(20261101)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, tick_interval_seconds: float = 2.5) -> None:
        self.stop()
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="client-activity-simulator", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        tick = 0
        while not self._stop_event.wait(self._tick_interval_seconds):
            state = self._repository.state_ref()
            if not state.initialized or state.paused or state.lifecycle != "running":
                continue
            tick += 1
            self._repository.append_event({
                "type": "simulation_tick",
                "at": time.time(),
                "tick": tick,
                "tick_interval_seconds": self._tick_interval_seconds,
                "session_transition_probability": 0.2,
            })
            clients = [client for client in state.clients.values() if client.active]
            if len(clients) > 250:
                self._advance_virtual_clients(state, clients, tick)
            else:
                for client in clients:
                    if self._random.random() < 0.2:
                        client.online = not client.online
                        event_type = "client_connected" if client.online else "client_disconnected"
                        self._repository.append_event({"type": event_type, "at": time.time(), "client_id": client.client_id, "tick": tick, "probability": 0.2, "reason": "tick_session_churn", "videos_consumed": client.videos_consumed})
                    if not client.online:
                        continue
                    try:
                        self._stream_service.stream(client, state, chunk_number=client.videos_consumed % 5)
                    except (ClientOfflineError, SimulationPausedError, PermissionError, RuntimeError, OSError):
                        continue
            self._emit_server_communications(state, tick)

    def _advance_virtual_clients(self, state, clients: list, tick: int) -> None:
        """Account for large populations without one subprocess/request per client."""
        # A bounded sample keeps session churn visible without making a tick
        # O(number of clients). The demand calculation below still uses every
        # online client in the population.
        sample_step = max(1, len(clients) // 128)
        for client in clients[::sample_step][:128]:
            if self._random.random() < 0.2:
                client.online = not client.online

        online_clients = [client for client in clients if client.online]
        demand_rps = len(online_clients) * float(state.config.get("demand_rps_per_client", 0.25))
        available = [
            server
            for server in state.servers.values()
            if server.status in {"healthy", "degraded", "overloaded"}
        ]
        if not online_clients or not available:
            return
        fallback_capacity = 8.0
        capacities = {
            server.server_id: max(fallback_capacity, float(server.capacity_rps or fallback_capacity))
            for server in available
        }
        total_capacity = sum(capacities.values())
        served_rps = min(demand_rps, total_capacity)
        interval = max(0.5, float(self._tick_interval_seconds))
        # Do not emit hundreds of map lines for a 500-node simulation. A
        # deterministic spread still keeps the backbone visually informative.
        visible_servers = available[:64]
        visible_capacity = sum(capacities[server.server_id] for server in visible_servers)
        for index, server in enumerate(visible_servers):
            request_count = max(0, round(served_rps * interval * capacities[server.server_id] / max(visible_capacity, 1.0)))
            if request_count == 0:
                continue
            client = online_clients[index % len(online_clients)]
            distance = haversine_km(client.latitude, client.longitude, server.latitude, server.longitude)
            utilization = demand_rps / max(total_capacity, 1.0)
            latency = round(18.0 + min(240.0, distance * 0.006 * float(state.config.get("latency_factor", 1.0))), 3)
            rejected = max(0, round(request_count * max(0.0, utilization - 1.0)))
            server.requests_total += request_count
            server.errors_total += rejected
            server.requests_in_flight = 0
            server.load = min(16, round(utilization * 16))
            server.utilization = round(demand_rps / max(capacities[server.server_id], 1.0), 3)
            server.capacity_pressure = server.utilization
            server.queue_depth = max(0, round((server.utilization - 0.9) * 20))
            server.queue_rejected += rejected
            server.queue_wait_ms = round(max(0.0, (server.utilization - 0.75) * 120), 3)
            self._repository.append_traffic({
                "at": time.time(),
                "request_id": f"batch-{tick}-{server.server_id}",
                "trace_id": f"trace-batch-{tick}-{server.server_id}",
                "client_id": client.client_id,
                "server_id": server.server_id,
                "distance_km": round(distance, 2),
                "latency_ms": latency,
                "artificial_latency_ms": latency,
                "http_rtt_ms": 0.0,
                "queue_wait_ms": server.queue_wait_ms,
                "end_to_end_ms": round(latency + server.queue_wait_ms, 3),
                "chunk_id": f"batch-chunk-{tick}-{server.server_id}",
                "request_count": request_count,
                "virtual": True,
                "routing_reason": "roteamento virtual agregado para escala",
            })
        self._repository.append_event({
            "type": "client_request_batch",
            "at": time.time(),
            "tick": tick,
            "client_count": len(online_clients),
            "request_count": round(served_rps * interval),
            "demand_rps": round(demand_rps, 3),
            "served_rps": round(served_rps, 3),
            "virtual": True,
            "reason": "agregação de telemetria para população grande",
        })

    def _emit_server_communications(self, state, tick: int) -> None:
        online_count = sum(1 for client in state.clients.values() if client.online)
        peers = [server for server in state.servers.values() if server.status in {"healthy", "degraded", "overloaded"} and server.process_mode == "http"]
        peer_ids = {peer.server_id for peer in peers}
        source_candidates = [server for server in peers if any(peer_id in peer_ids for peer_id in server.peer_ids)]
        if not source_candidates:
            return
        source = self._random.choice(source_candidates)
        peer_ids = set(source.peer_ids)
        destinations = [server for server in peers if server.server_id in peer_ids]
        if not destinations:
            return
        target = self._random.choice(destinations)
        roll = self._random.random()
        if roll < 0.12:
            message_type = "NEW_CONTENT_DELIVERY"
            communication_kind = "new_content"
            probability = 0.12
            payload_summary = "content_id + versão do asset + região de origem"
            message = {
                "content_id": state.config.get("video_id", "bigbuckbunny"),
                "content_title": state.config.get("video_id", "bigbuckbunny"),
                "asset_version": f"tick-{tick:04d}",
                "region": source.city,
                "delivery_mode": "edge_prefetch",
            }
        elif roll < 0.42:
            message_type = "METADATA_UPDATE"
            communication_kind = "update"
            probability = 0.30
            payload_summary = "content_id + contagem de viewers + metadados de catálogo"
            message = {
                "content_id": state.config.get("video_id", "bigbuckbunny"),
                "content_title": state.config.get("video_id", "bigbuckbunny"),
                "viewer_count_delta": online_count,
                "region": source.city,
                "metadata_version": f"catalog-{tick:04d}",
                "delivery_mode": "catalog_sync",
            }
        elif any(float(server.utilization or 0) >= 0.9 for server in peers) and roll < 0.62:
            message_type = "CAPACITY_ALERT"
            communication_kind = "capacity"
            probability = 0.20
            payload_summary = "utilização por nó + folga de capacidade + fila"
            message = {
                "content_id": state.config.get("video_id", "bigbuckbunny"),
                "content_title": state.config.get("video_id", "bigbuckbunny"),
                "capacity_signal": round(max(float(server.utilization or 0) for server in peers), 3),
                "queue_depth": max(int(server.queue_depth or 0) for server in peers),
                "region": source.city,
                "delivery_mode": "capacity_gossip",
            }
        else:
            return
        message.update({
            "message_id": f"tick-{tick}-{uuid.uuid4().hex[:10]}",
            "message_type": message_type,
            "communication_kind": communication_kind,
            "from_server": source.server_id,
            "to_server": target.server_id,
            "encryption": "AES-256-GCM",
            "tick": tick,
            "emission_probability": probability,
            "sent_at": time.time(),
        })
        try:
            ack = self._stream_service.publish_server_message(source, target, message, float(state.config.get("latency_factor", 1.0)))
            self._repository.append_event({
                "type": "server_message",
                "at": time.time(),
                **message,
                "status": "acknowledged",
                "payload_summary": payload_summary,
                "ack_server_id": ack.get("server_id"),
                "encryption": ack.get("encryption", "AES-256-GCM"),
            })
        except Exception as exc:
            self._repository.append_event({
                "type": "server_message",
                "at": time.time(),
                **message,
                "status": "failed",
                "payload_summary": payload_summary,
                "error": str(exc),
            })


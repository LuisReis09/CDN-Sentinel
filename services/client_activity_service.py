from __future__ import annotations

import random
import threading
import time
import uuid

from repositories.in_memory import SimulationRepository
from services.stream_service import ClientOfflineError, SimulationPausedError, StreamService
from services.content_provider import default_content_id
from utils.geo import haversine_km
from utils.latency import propagation_delay_seconds


class ClientActivityService:
    """Advances one shared simulation tick and produces client session churn."""

    # Keep presence visibly dynamic in the didactic map without changing the
    # demand model itself. Clients still need an initial delivery before
    # transitions begin.
    session_transition_probability = 0.38

    def __init__(self, repository: SimulationRepository, stream_service: StreamService, interval_seconds: float = 2.5, on_tick=None) -> None:
        self._repository = repository
        self._stream_service = stream_service
        self._interval_seconds = interval_seconds
        self._tick_interval_seconds = interval_seconds
        self._random = random.Random(20261101)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_tick = on_tick

    def set_on_tick(self, callback) -> None:
        self._on_tick = callback

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

    def configure_tick_interval(self, tick_interval_seconds: float) -> None:
        """Change the cadence for the next wait without recreating the worker."""
        self._tick_interval_seconds = max(0.5, float(tick_interval_seconds))

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
                "session_transition_probability": self.session_transition_probability,
            })
            clients = [client for client in state.clients.values() if client.active]
            if len(clients) > 250:
                self._advance_virtual_clients(state, clients, tick)
            else:
                for client in clients:
                    self._maybe_toggle_client(client, tick)
                    if not client.online:
                        continue
                    try:
                        self._stream_service.stream(client, state, chunk_number=client.videos_consumed % 5)
                    except (ClientOfflineError, SimulationPausedError, PermissionError, RuntimeError, OSError):
                        continue
            self._emit_server_communications(state, tick)
            if self._on_tick:
                try:
                    self._on_tick()
                except Exception as exc:
                    self._repository.append_event({"type": "management_tick_failed", "at": time.time(), "error": str(exc)})

    def _advance_virtual_clients(self, state, clients: list, tick: int) -> None:
        """Account for large populations without one subprocess/request per client."""
        # A bounded sample keeps session churn visible without making a tick
        # O(number of clients). The demand calculation below still uses every
        # online client in the population.
        sample_size = min(128, len(clients))
        sample_start = (tick * sample_size) % max(1, len(clients))
        sampled_clients = [clients[(sample_start + index) % len(clients)] for index in range(sample_size)]
        for client in sampled_clients:
            self._maybe_toggle_client(client, tick)

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
            # The virtual path follows the same geospatial model as a real
            # stream.  Distance is the only latency input exposed to the
            # simulation; a client twice as far observes roughly twice the
            # propagation delay (before queueing and HTTP overhead).
            latency = round(propagation_delay_seconds(distance, 1.0) * 1000, 3)
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
            client.videos_consumed += request_count
            client.last_activity_at = time.time()
            watch_record = {
                "at": time.time(),
                "video_id": state.config.get("video_id") or default_content_id(),
                "chunk_number": client.videos_consumed % 5,
                "chunk_id": f"batch-chunk-{tick}-{server.server_id}",
                "server_id": server.server_id,
                "latency_ms": round(latency + server.queue_wait_ms, 3),
                "network_latency_ms": latency,
                "queue_wait_ms": server.queue_wait_ms,
                "liked": None,
            }
            client.watch_history.append(watch_record)
            client.watch_history = client.watch_history[-100:]
            self._stream_service.record_delivery_feedback(client, watch_record)
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

    def _maybe_toggle_client(self, client, tick: int) -> None:
        """Toggle sessions in both directions, but only after first delivery."""
        if client.videos_consumed < 1:
            client.online = True
            return
        if self._random.random() >= self.session_transition_probability:
            return
        client.online = not client.online
        event_type = "client_connected" if client.online else "client_disconnected"
        self._repository.append_event({
            "type": event_type,
            "at": time.time(),
            "client_id": client.client_id,
            "tick": tick,
            "probability": self.session_transition_probability,
            "reason": "tick_session_churn_after_first_video",
            "videos_consumed": client.videos_consumed,
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
                "content_id": state.config.get("video_id") or default_content_id(),
                "content_title": state.config.get("video_id") or default_content_id(),
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
                "content_id": state.config.get("video_id") or default_content_id(),
                "content_title": state.config.get("video_id") or default_content_id(),
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
                "content_id": state.config.get("video_id") or default_content_id(),
                "content_title": state.config.get("video_id") or default_content_id(),
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



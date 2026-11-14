from __future__ import annotations

import random
import threading
import time
import uuid

from repositories.in_memory import SimulationRepository
from services.stream_service import StreamService
from services.content_provider import default_content_id
from utils.geo import haversine_km, rank_delivery_servers
from utils.latency import propagation_delay_seconds


class ClientActivityService:
    """Advances aggregate demand while every simulated client stays available.

    Real requests still exercise the data plane.  Background ticks are kept
    aggregate so they do not compete with a viewer for FFmpeg/QIM work.

    Management advances together with the telemetry clock so player actions
    are reflected on the next visible simulation update.
    """

    # Every active client receives a visible playback update on a normal
    # scenario tick.  Keep a cap for unusually large ad-hoc simulations and
    # rotate through it fairly instead of returning to one FFmpeg/QIM job per
    # client.
    virtual_delivery_batch_size = 2_000

    def __init__(self, repository: SimulationRepository, stream_service: StreamService, interval_seconds: float = 1.25, on_tick=None) -> None:
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

    def start(self, tick_interval_seconds: float = 1.25) -> None:
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
                "delivery_model": "aggregated-active-clients",
            })
            clients = [client for client in state.clients.values() if client.active]
            self._advance_virtual_clients(state, clients, tick)
            self._emit_server_communications(state, tick)
            if self._on_tick:
                try:
                    self._on_tick()
                except Exception as exc:
                    self._repository.append_event({"type": "management_tick_failed", "at": time.time(), "error": str(exc)})

    def _advance_virtual_clients(self, state, clients: list, tick: int) -> None:
        """Account for all active clients without per-client video encoding."""
        for client in clients:
            # ``online`` is retained for old archived API payloads, but a
            # running simulation no longer models disconnected sessions.
            client.online = True
        active_clients = clients
        demand_rps = len(active_clients) * float(state.config.get("demand_rps_per_client", 0.25))
        available = [
            server
            for server in state.servers.values()
            if server.status in {"healthy", "degraded", "overloaded"}
        ]
        if not active_clients or not available:
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
            utilization = demand_rps / max(total_capacity, 1.0)
            # The virtual path follows the same geospatial model as a real
            # stream.  Distance is the only latency input exposed to the
            # simulation; a client twice as far observes roughly twice the
            # propagation delay (before queueing and HTTP overhead).
            rejected = max(0, round(request_count * max(0.0, utilization - 1.0)))
            server.simulated_requests_total += request_count
            server.simulated_errors_total += rejected
            server.requests_total = server.simulated_requests_total + server.http_requests_total
            server.errors_total = server.simulated_errors_total + server.http_errors_total
            server.requests_in_flight = 0
            server.load = min(16, round(utilization * 16))
            server.utilization = round(utilization, 3)
            server.capacity_pressure = server.utilization
            server.queue_depth = max(0, round((server.utilization - 0.9) * 20))
            server.queue_rejected += rejected
            server.queue_wait_ms = round(max(0.0, (server.utilization - 0.75) * 120), 3)
            self._repository.append_traffic({
                "at": time.time(),
                "request_id": f"batch-{tick}-{server.server_id}",
                "trace_id": f"trace-batch-{tick}-{server.server_id}",
                "client_id": "aggregate",
                "server_id": server.server_id,
                "distance_km": 0.0,
                "latency_ms": server.queue_wait_ms,
                "artificial_latency_ms": 0.0,
                "http_rtt_ms": 0.0,
                "queue_wait_ms": server.queue_wait_ms,
                "end_to_end_ms": server.queue_wait_ms,
                "chunk_id": f"batch-chunk-{tick}-{server.server_id}",
                "request_count": request_count,
                "virtual": True,
                "routing_reason": "roteamento virtual agregado para escala",
            })
        # The aggregate traffic record above protects the real playback path
        # from hundreds of QIM/FFmpeg jobs. A suspected pirate whose real
        # marked media is being encoded/inspected is held until that forensic
        # pipeline resolves; suspicion alone is still not a blacklist action.
        progress_clients = [
            client for client in active_clients
            if client.client_id not in state.forensic_pending_clients
        ]
        if not progress_clients:
            return
        batch_size = min(len(progress_clients), self.virtual_delivery_batch_size)
        start = ((tick - 1) * batch_size) % len(progress_clients)
        now = time.time()
        pending_assignments: dict[str, int] = {}
        for offset in range(batch_size):
            client = progress_clients[(start + offset) % len(progress_clients)]
            # The aggregate delivery path keeps geography as its primary
            # signal, but shares a same-tick burst with nearby idle nodes.
            _score, server = rank_delivery_servers(
                client.latitude,
                client.longitude,
                available,
                require_http=False,
                pending_assignments=pending_assignments,
            )[0]
            pending_assignments[server.server_id] = pending_assignments.get(server.server_id, 0) + 1
            distance = haversine_km(client.latitude, client.longitude, server.latitude, server.longitude)
            network_latency = round(propagation_delay_seconds(distance, 1.0) * 1000, 3)
            client.videos_consumed += 1
            client.last_activity_at = now
            client.watch_history.append({
                "at": now,
                "video_id": state.config.get("video_id") or default_content_id(),
                "chunk_number": client.videos_consumed % 5,
                "chunk_id": f"simulated-chunk-{tick}-{client.client_id}",
                "server_id": server.server_id,
                "latency_ms": round(network_latency + server.queue_wait_ms, 3),
                "network_latency_ms": network_latency,
                "queue_wait_ms": server.queue_wait_ms,
                "liked": None,
                "delivery_mode": "simulated-aggregate",
            })
            client.watch_history = client.watch_history[-100:]
        self._repository.append_event({
            "type": "client_request_batch",
            "at": time.time(),
            "tick": tick,
            "client_count": len(active_clients),
            "progress_client_count": len(progress_clients),
            "forensic_pending_clients": len(state.forensic_pending_clients),
            "request_count": round(served_rps * interval),
            "demand_rps": round(demand_rps, 3),
            "served_rps": round(served_rps, 3),
            "virtual": True,
            "reason": "telemetria agregada para clientes sempre ativos",
        })

    def _emit_server_communications(self, state, tick: int) -> None:
        active_count = sum(1 for client in state.clients.values() if client.active)
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
                "viewer_count_delta": active_count,
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



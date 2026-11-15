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
    """Advance bounded, heterogeneous client events and local node telemetry.

    Each client gets an individual session/request decision and route; only
    traffic records are coalesced per server so large simulations remain fast.
    Management advances together with the operational telemetry clock.
    """

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
                "delivery_model": "heterogeneous-client-events",
            })
            clients = [client for client in state.clients.values() if client.active]
            self._advance_virtual_clients(state, clients, tick)
            self._emit_server_communications(state, tick)
            if self._on_tick:
                try:
                    self._on_tick(self._tick_interval_seconds)
                except TypeError:
                    # Keep compatibility with small integrations that expose
                    # a no-argument management callback.
                    self._on_tick()
                except Exception as exc:
                    self._repository.append_event({"type": "management_tick_failed", "at": time.time(), "error": str(exc)})

    def _advance_virtual_clients(self, state, clients: list, tick: int) -> None:
        """Generate heterogeneous client events and derive node telemetry.

        Video bytes are still not encoded for every virtual viewer. Each
        client does receive its own session/request decision, route, latency,
        watch history and automatic feedback. Only the final traffic records
        are coalesced per server, which keeps a 100k-client run bounded while
        preserving demand conservation and local bottlenecks.
        """
        interval = max(0.5, float(self._tick_interval_seconds))
        now = time.time()
        blocked = {
            client_id for client_id, entry in state.temporary_blacklist.items()
            if float(entry.get("expires_at", 0)) > now
        } | set(state.forensic_pending_clients)
        available = [
            server for server in state.servers.values()
            if server.status in {"healthy", "degraded", "overloaded"}
        ]
        if not clients or not available:
            return
        policy = str(state.config.get("load_balancing_policy", "hybrid-latency-capacity"))
        seed = int(state.config.get("seed", 2026))
        rng = random.Random(seed + tick * 7919)
        pending_assignments: dict[str, int] = {}
        by_server: dict[str, list[dict]] = {server.server_id: [] for server in available}
        total_demand_rps = 0.0
        total_attempts = 0
        total_rejected = 0
        simulated_seconds = tick * interval
        for client in clients:
            if not client.active or client.client_id in blocked:
                client.online = False if client.client_id in blocked else client.online
                continue
            local_hour = (simulated_seconds / 3600.0 + client.timezone_offset_hours) % 24.0
            peak_factor = 1.35 if 18.0 <= local_hour <= 23.0 else 0.65 if 1.0 <= local_hour < 6.0 else 1.0
            expected_rps = max(0.0, float(client.activity_rate_rps or state.config.get("demand_rps_per_client", 0.25)))
            expected_rps *= peak_factor * max(0.35, float(client.content_affinity or 1.0))
            total_demand_rps += expected_rps
            if not client.online:
                if rng.random() > float(client.session_probability or 0.85):
                    continue
                client.online = True
            if tick < int(client.next_activity_tick or 0):
                continue
            expected_requests = expected_rps * interval
            request_count = min(4, int(expected_requests) + int(rng.random() < (expected_requests % 1.0)))
            first_event = client.requests_generated == 0 and client.next_activity_tick == 0
            if request_count <= 0 and (first_event or rng.random() < min(0.95, expected_requests * 1.5)):
                request_count = 1
            client.next_activity_tick = tick + max(1, round(float(client.watch_interval_ticks or 1.0) * rng.uniform(0.7, 1.4)))
            if request_count <= 0:
                continue
            for _ in range(request_count):
                ranked = rank_delivery_servers(
                    client.latitude,
                    client.longitude,
                    available,
                    require_http=False,
                    pending_assignments=pending_assignments,
                    policy=policy,
                )
                if not ranked:
                    continue
                _score, server = ranked[0]
                pending_assignments[server.server_id] = pending_assignments.get(server.server_id, 0) + 1
                distance = haversine_km(client.latitude, client.longitude, server.latitude, server.longitude)
                by_server[server.server_id].append({"client": client, "distance_km": distance})
                client.requests_generated += 1
                client.videos_consumed += 1
                client.last_activity_at = now
                total_attempts += 1
        for server in available:
            assignments = by_server[server.server_id]
            attempted = len(assignments)
            capacity = max(1.0, float(server.capacity_rps or 8.0))
            cache_hit_rate = max(0.0, min(0.95, float(getattr(server, "cache_hit_rate", 0.0) or 0.0)))
            cache_hits = round(attempted * cache_hit_rate)
            cache_misses = max(0, attempted - cache_hits)
            server.cache_hits += cache_hits
            server.cache_misses += cache_misses
            effective_attempts = cache_hits * 0.35 + cache_misses
            pressure = effective_attempts / max(capacity * interval, 1.0)
            fault = server.fault or {}
            drop_rate = max(0.0, min(1.0, float(fault.get("drop_rate", 0.0) or 0.0)))
            rejected = min(attempted, round(attempted * drop_rate + max(0.0, pressure - 1.0) * attempted))
            total_rejected += rejected
            queue_depth = max(0, round(max(0.0, pressure - 0.85) * 20))
            queue_wait = round(max(0.0, pressure - 0.65) * 180.0, 3)
            extra_latency = max(0.0, float(fault.get("extra_latency_ms", 0.0) or 0.0))
            mean_distance = sum(item["distance_km"] for item in assignments) / attempted if attempted else 0.0
            network_latency = propagation_delay_seconds(mean_distance, float(state.config.get("latency_factor", 1.0))) * 1000.0
            observed_latency = round(network_latency * (1.0 - 0.20 * cache_hit_rate) + queue_wait + extra_latency, 3)
            server.simulated_requests_total += attempted
            server.simulated_errors_total += rejected
            server.requests_total = server.simulated_requests_total + server.http_requests_total
            server.errors_total = server.simulated_errors_total + server.http_errors_total
            server.requests_in_flight = 0
            server.load = min(16, round(pressure * 16))
            server.utilization = round(pressure, 4)
            server.capacity_pressure = round(pressure, 4)
            server.queue_depth = queue_depth
            server.queue_rejected += rejected
            server.queue_wait_ms = queue_wait
            server.last_request_at = now if attempted else server.last_request_at
            for item in assignments:
                client = item["client"]
                watch = {
                    "at": now,
                    "video_id": state.config.get("video_id") or default_content_id(),
                    "chunk_number": client.videos_consumed % 5,
                    "chunk_id": f"simulated-chunk-{tick}-{client.client_id}",
                    "server_id": server.server_id,
                    "latency_ms": observed_latency,
                    "network_latency_ms": round(network_latency, 3),
                    "queue_wait_ms": queue_wait,
                    "liked": None,
                    "delivery_mode": "simulated-aggregate",
                }
                client.watch_history.append(watch)
                client.watch_history = client.watch_history[-100:]
                self._stream_service.record_delivery_feedback(
                    client, watch, source="virtual_simulation", emit_event=False,
                )
            if attempted:
                self._repository.append_traffic({
                    "at": now,
                    "request_id": f"batch-{tick}-{server.server_id}",
                    "trace_id": f"trace-batch-{tick}-{server.server_id}",
                    "client_id": "aggregate",
                    "client_count": len({item["client"].client_id for item in assignments}),
                    "client_ids_sample": [item["client"].client_id for item in assignments[:8]],
                    "server_id": server.server_id,
                    "distance_km": round(mean_distance, 2),
                    "latency_ms": observed_latency,
                    "artificial_latency_ms": round(network_latency, 3),
                    "http_rtt_ms": 0.0,
                    "queue_wait_ms": queue_wait,
                    "end_to_end_ms": observed_latency,
                    "chunk_id": f"batch-chunk-{tick}-{server.server_id}",
                    "request_count": attempted,
                    "rejected_count": rejected,
                    "cache_hit_count": cache_hits,
                    "cache_miss_count": cache_misses,
                    "virtual": True,
                    "routing_reason": f"{policy}; eventos individuais agregados por nó",
                })
        self._repository.append_event({
            "type": "client_request_batch",
            "at": now,
            "tick": tick,
            "client_count": len(clients),
            "progress_client_count": len(clients) - len(blocked),
            "forensic_pending_clients": len(blocked),
            "request_count": total_attempts,
            "rejected_count": total_rejected,
            "demand_rps": round(total_demand_rps, 3),
            "served_rps": round(max(0, total_attempts - total_rejected) / interval, 3),
            "virtual": True,
            "reason": "eventos individuais com sessão, fuso, pico e afinidade de conteúdo",
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



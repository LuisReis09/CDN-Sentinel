from __future__ import annotations

import random
import threading
import time
import uuid

from repositories.in_memory import SimulationRepository
from services.stream_service import ClientOfflineError, SimulationPausedError, StreamService


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
        self._tick_interval_seconds = max(0.25, float(tick_interval_seconds))
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
            state = self._repository.snapshot()
            if not state.initialized or state.paused:
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
            for client in clients:
                if self._random.random() < 0.2:
                    client.online = not client.online
                    event_type = "client_connected" if client.online else "client_disconnected"
                    self._repository.append_event({"type": event_type, "at": time.time(), "client_id": client.client_id, "tick": tick, "probability": 0.2, "reason": "tick_session_churn", "videos_consumed": client.videos_consumed})
                if not client.online:
                    continue
                try:
                    self._stream_service.stream(client, state, chunk_number=client.videos_consumed % 5)
                except (ClientOfflineError, PermissionError, RuntimeError, OSError):
                    continue
            self._emit_server_communications(state, tick)

    def _emit_server_communications(self, state, tick: int) -> None:
        clients = list(state.clients.values())
        peers = [server for server in state.servers.values() if server.status == "healthy"]
        if len(peers) < 2:
            return
        source = self._random.choice(peers)
        destinations = [server for server in peers if server.server_id != source.server_id]
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
                "viewer_count_delta": len([client for client in clients if client.online]),
                "region": source.city,
                "metadata_version": f"catalog-{tick:04d}",
                "delivery_mode": "catalog_sync",
            }
        else:
            return
        message.update({
            "message_id": f"tick-{tick}-{uuid.uuid4().hex[:10]}",
            "message_type": message_type,
            "communication_kind": communication_kind,
            "from_server": source.server_id,
            "to_server": target.server_id,
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


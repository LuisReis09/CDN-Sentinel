from __future__ import annotations

import time
from typing import Any

from models.entities import SimulationState
from repositories.in_memory import SimulationRepository
from services.leak_service import LeakService
from services.monitor_service import MonitorService
from services.stream_service import StreamService
from services.watermark_demo_service import WatermarkDemoService
from services.client_activity_service import ClientActivityService
from controllers.simulation_controller import SimulationController


class ApiController:
    def __init__(
        self,
        repository: SimulationRepository,
        simulation_controller: SimulationController,
        stream_service: StreamService,
        monitor_service: MonitorService,
        leak_service: LeakService,
        watermark_service,
        watermark_demo_service: WatermarkDemoService,
        client_activity_service: ClientActivityService,
    ) -> None:
        self.repository = repository
        self.simulation_controller = simulation_controller
        self.stream_service = stream_service
        self.monitor_service = monitor_service
        self.leak_service = leak_service
        self.watermark_service = watermark_service
        self.watermark_demo_service = watermark_demo_service
        self.client_activity_service = client_activity_service

    def initialize(self, payload: dict) -> dict:
        result = self.simulation_controller.initialize(payload)
        self.watermark_service.configure(self.simulation_controller.secret_key)
        tick_interval = result["configuration"].get("tick_interval_seconds", 2.5)
        self.leak_service.start(tick_interval)
        self.client_activity_service.start(tick_interval)
        self.monitor_service.start(result.get("servers", []), tick_interval)
        return result

    def update_simulation(self, payload: dict) -> dict:
        result = self.simulation_controller.update(payload)
        tick_interval = result["configuration"].get("tick_interval_seconds", 2.5)
        self.leak_service.start(tick_interval)
        self.client_activity_service.start(tick_interval)
        if result.get("servers"):
            self.monitor_service.start(result.get("servers", []), tick_interval)
        else:
            self.monitor_service.configure_tick_interval(tick_interval)
        return result

    def pause(self) -> dict:
        return self.simulation_controller.pause()

    def resume(self) -> dict:
        return self.simulation_controller.resume()

    def status(self) -> dict:
        return self.simulation_controller.status()

    def create_client(self, payload: dict) -> dict:
        return self.simulation_controller.add_client(payload)

    def create_server(self, payload: dict) -> dict:
        result = self.simulation_controller.add_server(payload)
        self.monitor_service.add_server(result, self.simulation_controller.status()["configuration"].get("tick_interval_seconds", 2.5))
        return result

    def servers(self) -> list[dict]:
        return self.simulation_controller.refresh_servers()

    def stream(self, client_id: str, chunk_number: int) -> dict:
        state = self.repository.snapshot()
        if not state.initialized:
            raise RuntimeError("A simulação ainda não foi inicializada")
        client = state.clients.get(client_id)
        if client is None:
            raise KeyError(f"Cliente {client_id} não encontrado")
        return self.stream_service.stream(client, state, chunk_number).to_dict()

    def scan(self, server_id: str | None = None) -> dict:
        return self.monitor_service.scan(server_id=server_id)

    def monitor_status(self) -> dict:
        return self.monitor_service.status()

    def blacklist(self) -> list[dict]:
        self.simulation_controller.refresh_servers()
        return [entry.to_dict() for entry in self.repository.blacklist_values()]

    def clients(self) -> list[dict]:
        return [client.to_dict() for client in self.repository.snapshot().clients.values()]

    def leaks(self) -> list[dict]:
        return list(self.repository.snapshot().leaks)

    def leak_summaries(self) -> list[dict]:
        fields = ("leak_id", "client_id", "server_id", "origin_server_id", "platform", "platform_id", "platform_kind", "external_url", "created_at", "processed", "detected_at", "detected_by_server_id", "error")
        return [{key: leak.get(key) for key in fields if key in leak} for leak in self.repository.snapshot().leaks]

    def events(self) -> list[dict]:
        return list(self.repository.snapshot().events)

    def traffic(self) -> list[dict]:
        return list(self.repository.snapshot().traffic)

    def overview(self) -> dict:
        state = self.repository.snapshot()
        recent_events = state.events[-25:]
        message_events = [event for event in state.events if event.get("type") == "server_message"][-10:]
        seen_events: set[tuple] = set()
        selected_events = []
        for event in [*recent_events, *message_events]:
            key = (event.get("at"), event.get("type"), event.get("message_id"), event.get("client_id"), event.get("tick"))
            if key not in seen_events:
                seen_events.add(key)
                selected_events.append(event)
        return {
            "status": self.status(),
            "servers": self.servers(),
            "clients": self.clients(),
            "blacklist": self.blacklist(),
            "leaks": self.leak_summaries(),
            "recent_events": sorted(selected_events, key=lambda event: event.get("at", 0))[-35:],
            "recent_traffic": self.traffic()[-25:],
            "monitor": self.monitor_status(),
        }

    def verify_watermark(self, token: str) -> dict:
        claim = self.monitor_service.verify_token(token)
        self.repository.append_event({
            "type": "watermark_verified",
            "at": time.time(),
            "client_id": claim["client_id"],
            "server_id": claim["server_id"],
            "proof_algorithm": "HMAC-SHA256",
        })
        return claim

    def watermark_demo(self, payload: dict) -> dict:
        return self.watermark_demo_service.run(payload)


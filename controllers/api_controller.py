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
        self.leak_service.start()
        self.client_activity_service.start()
        return result

    def update_simulation(self, payload: dict) -> dict:
        result = self.simulation_controller.update(payload)
        self.leak_service.start()
        self.client_activity_service.start()
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
        return self.simulation_controller.add_server(payload)

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

    def scan(self) -> dict:
        return self.monitor_service.scan()

    def blacklist(self) -> list[dict]:
        self.simulation_controller.refresh_servers()
        return [entry.to_dict() for entry in self.repository.blacklist_values()]

    def clients(self) -> list[dict]:
        return [client.to_dict() for client in self.repository.snapshot().clients.values()]

    def leaks(self) -> list[dict]:
        return list(self.repository.snapshot().leaks)

    def events(self) -> list[dict]:
        return list(self.repository.snapshot().events)

    def traffic(self) -> list[dict]:
        return list(self.repository.snapshot().traffic)

    def overview(self) -> dict:
        state = self.repository.snapshot()
        return {
            "status": self.status(),
            "servers": self.servers(),
            "clients": self.clients(),
            "blacklist": self.blacklist(),
            "recent_events": self.events()[-25:],
            "recent_traffic": self.traffic()[-25:],
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


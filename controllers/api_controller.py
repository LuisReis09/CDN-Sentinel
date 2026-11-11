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
        management_engine=None,
    ) -> None:
        self.repository = repository
        self.simulation_controller = simulation_controller
        self.stream_service = stream_service
        self.monitor_service = monitor_service
        self.leak_service = leak_service
        self.watermark_service = watermark_service
        self.watermark_demo_service = watermark_demo_service
        self.client_activity_service = client_activity_service
        self.management_engine = management_engine

    def initialize(self, payload: dict) -> dict:
        self.leak_service.stop()
        self.client_activity_service.stop()
        self.monitor_service.stop()
        result = self.simulation_controller.initialize(payload)
        if self.management_engine:
            self.management_engine.reset(seed=result["configuration"].get("seed", 2026))
        self.watermark_service.configure(self.simulation_controller.secret_key)
        tick_interval = result["configuration"].get("tick_interval_seconds", 2.5)
        self.leak_service.start(tick_interval)
        self.client_activity_service.start(tick_interval)
        self.monitor_service.start(result.get("servers", []), tick_interval)
        return result

    def update_simulation(self, payload: dict) -> dict:
        current = self.repository.snapshot_without_clients()
        rebuild_keys = ("base_node_port", "base_client_port", "seed")
        rebuild = any(
            key in payload and payload[key] != current.config.get(key)
            for key in rebuild_keys
        )
        if rebuild:
            self.leak_service.stop()
            self.client_activity_service.stop()
            self.monitor_service.stop()
        try:
            result = self.simulation_controller.update(payload)
        except Exception:
            if rebuild and current.initialized:
                tick_interval = current.config.get("tick_interval_seconds", 2.5)
                self.leak_service.start(tick_interval)
                self.client_activity_service.start(tick_interval)
                self.monitor_service.start([server.to_dict() for server in current.servers.values()], tick_interval)
            raise
        tick_interval = result["configuration"].get("tick_interval_seconds", 2.5)
        if rebuild:
            self.leak_service.start(tick_interval)
            self.client_activity_service.start(tick_interval)
            self.monitor_service.start([server.to_dict() for server in self.repository.snapshot_without_clients().servers.values()], tick_interval)
        else:
            # Configuration edits, including live population resizing, only
            # adjust worker cadence and monitor membership; no worker restarts.
            self.leak_service.configure_tick_interval(tick_interval)
            self.client_activity_service.configure_tick_interval(tick_interval)
            self.monitor_service.configure_tick_interval(tick_interval)
            updated = self.repository.snapshot_without_clients()
            removed_server_ids = set(current.servers) - set(updated.servers)
            for server_id in removed_server_ids:
                self.monitor_service.remove_server(server_id)
            for server in updated.servers.values():
                self.monitor_service.add_server(
                    server.to_dict(),
                    tick_interval_seconds=tick_interval,
                    start_thread=server.status != "offline",
                )
        return result

    def pause(self) -> dict:
        result = self.simulation_controller.pause()
        if self.management_engine:
            self.management_engine.pause(True)
        return result

    def resume(self) -> dict:
        result = self.simulation_controller.resume()
        if self.management_engine:
            self.management_engine.pause(False)
        return result

    def end(self) -> dict:
        self.leak_service.stop()
        self.client_activity_service.stop()
        self.monitor_service.stop()
        result = self.simulation_controller.end()
        if self.management_engine:
            self.management_engine.pause(True)
        return result

    def management_state(self) -> dict:
        if not self.management_engine:
            raise RuntimeError("motor de gestão não configurado")
        return self.management_engine.snapshot()

    def management_actions(self) -> list[dict]:
        return self.management_engine.action_definitions()

    def management_scenarios(self) -> list[dict]:
        return self.management_engine.scenarios()

    def management_apply_action(self, payload: dict) -> dict:
        return self.management_engine.apply_action(payload)

    def management_start_scenario(self, payload: dict) -> dict:
        if not self.repository.snapshot().initialized or self.repository.snapshot().lifecycle == "ended":
            self.initialize({"num_servers": 3, "num_clients": 16, "seed": int(payload.get("seed", 2026)), "tick_interval_seconds": 2.5})
        return self.management_engine.reset(str(payload.get("scenario_id", "free")), payload.get("seed"))

    def management_reset(self) -> dict:
        return self.management_engine.reset("free")

    def management_history(self) -> list[dict]:
        return self.management_engine.history()

    def status(self) -> dict:
        return self.simulation_controller.status()

    def create_client(self, payload: dict) -> dict:
        return self.simulation_controller.add_client(payload)

    def client_feedback(self, client_id: str, payload: dict) -> dict:
        return self.simulation_controller.record_client_feedback(client_id, payload)

    def create_server(self, payload: dict) -> dict:
        result = self.simulation_controller.add_server(payload)
        self.monitor_service.add_server(result, self.simulation_controller.status()["configuration"].get("tick_interval_seconds", 2.5))
        return result

    def servers(self) -> list[dict]:
        return self.simulation_controller.refresh_servers()

    def stream(self, client_id: str, chunk_number: int, request_id: str | None = None) -> dict:
        # This is a short mutation boundary: stream accounting and failover
        # status must be committed to the repository, unlike public snapshots.
        state = self.repository.state_ref()
        if not state.initialized or state.lifecycle == "ended":
            raise RuntimeError("A simulação ainda não foi inicializada")
        client = state.clients.get(client_id)
        if client is None:
            raise KeyError(f"Cliente {client_id} não encontrado")
        return self.stream_service.stream(client, state, chunk_number, request_id).to_dict()

    def reset_metrics(self) -> dict:
        return self.simulation_controller.reset_metrics()

    def inject_fault(self, server_id: str, payload: dict) -> dict:
        return self.simulation_controller.inject_fault(server_id, payload)

    def history(self, simulation_id: str | None = None) -> list[dict]:
        return self.repository.history(simulation_id)

    def scan(self, server_id: str | None = None) -> dict:
        return self.monitor_service.scan(server_id=server_id)

    def monitor_status(self) -> dict:
        return self.monitor_service.status()

    def blacklist(self) -> list[dict]:
        self.simulation_controller.refresh_servers()
        return [entry.to_dict() for entry in self.repository.blacklist_values()]

    def clients(self) -> list[dict]:
        # Keep the control-plane payload bounded; status.clients_total remains
        # the authoritative count for large simulations.
        return [client.to_dict() for client in self.repository.client_sample(2_000)]

    def leaks(self) -> list[dict]:
        return list(self.repository.snapshot().leaks)

    def leak_summaries(self) -> list[dict]:
        fields = ("leak_id", "client_id", "server_id", "origin_server_id", "platform", "platform_id", "platform_kind", "external_url", "created_at", "processed", "detected_at", "detected_by_server_id", "trace_id", "request_id", "error")
        return [{key: leak.get(key) for key in fields if key in leak} for leak in self.repository.snapshot().leaks]

    def events(self) -> list[dict]:
        return list(self.repository.snapshot().events)

    def traffic(self) -> list[dict]:
        return list(self.repository.snapshot().traffic)

    def overview(self) -> dict:
        status = self.status()
        state = self.repository.snapshot_without_clients()
        servers = self.servers()
        blacklist = [entry.to_dict() for entry in self.repository.blacklist_values()]
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
            "status": status,
            "servers": servers,
            "clients": self.clients(),
            "blacklist": blacklist,
            "leaks": self.leak_summaries(),
            "recent_events": sorted(selected_events, key=lambda event: event.get("at", 0))[-35:],
            "recent_traffic": self.traffic()[-25:],
            "metrics_history": list(state.metrics_history),
            "monitor": self.monitor_status(),
            "management": self.management_engine.snapshot() if self.management_engine else None,
        }

    def verify_watermark(self, token: str) -> dict:
        claim = self.monitor_service.verify_token(token)
        self.repository.append_event({
            "type": "watermark_verified",
            "at": time.time(),
            "client_id": claim["client_id"],
            "server_id": claim["server_id"],
            "proof_algorithm": "AES-256-GCM + HMAC-SHA256",
        })
        return claim

    def detect_watermark_image(self, image) -> dict:
        return self.watermark_service.detect_image(image)

    def detect_watermark_video(self, path) -> dict:
        return self.watermark_service.detect_video(path)

    def watermark_demo(self, payload: dict) -> dict:
        return self.watermark_demo_service.run(payload)



import unittest

from controllers.simulation_controller import SimulationController
from models.entities import CDNServer, Client, SimulationState
from repositories.in_memory import SimulationRepository
from services.blacklist_service import BlacklistService
from services.cdn_http_client import CDNHttpClient
from services.client_activity_service import ClientActivityService
from services.leak_service import LeakService
from services.monitor_service import MonitorService
from services.stream_service import StreamService
from services.watermark_service import WatermarkService
from utils.geo import rank_delivery_servers


class SimulationRealismTests(unittest.TestCase):
    def _repository(self) -> SimulationRepository:
        repository = SimulationRepository()
        clients = {
            f"client-{index}": Client(
                f"client-{index}",
                0.0,
                float(index) * 0.2,
                "Test",
                online=False,
                activity_rate_rps=rate,
                session_probability=1.0,
                watch_interval_ticks=interval,
                next_activity_tick=0,
                content_affinity=affinity,
            )
            for index, (rate, interval, affinity) in enumerate(
                ((0.08, 3.0, 0.7), (0.8, 1.0, 1.0), (2.0, 0.5, 1.3))
            )
        }
        servers = {
            "cdn-a": CDNServer("cdn-a", "127.0.0.1", 5101, 0.0, 0.0, "A", status="healthy", process_mode="virtual", capacity_rps=5),
            "cdn-b": CDNServer("cdn-b", "127.0.0.1", 5102, 0.0, 20.0, "B", status="healthy", process_mode="virtual", capacity_rps=5),
        }
        repository.replace(SimulationState(
            initialized=True,
            lifecycle="running",
            config={
                "seed": 42,
                "demand_rps_per_client": 0.25,
                "tick_interval_seconds": 1.25,
                "load_balancing_policy": "least-utilized",
            },
            clients=clients,
            servers=servers,
        ))
        return repository

    def test_event_driven_clients_conserve_requests_and_diverge_by_profile(self):
        repository = self._repository()
        service = ClientActivityService(
            repository,
            StreamService(CDNHttpClient(), repository),
        )
        state = repository.state_ref()
        for tick in range(1, 5):
            service._advance_virtual_clients(state, list(state.clients.values()), tick)

        generated = sum(client.requests_generated for client in state.clients.values())
        routed = sum(int(item.get("request_count", 0)) for item in state.traffic)
        self.assertEqual(generated, routed)
        self.assertGreater(len({client.videos_consumed for client in state.clients.values()}), 1)
        self.assertGreaterEqual(len({item["server_id"] for item in state.traffic}), 2)
        self.assertTrue(all(item.get("end_to_end_ms", 0) > 0 for item in state.traffic))

    def test_routing_policy_changes_the_selected_node(self):
        near_busy = CDNServer("near", "127.0.0.1", 5101, 0, 0, "Near", status="healthy", capacity_rps=10, utilization=0.95)
        far_idle = CDNServer("far", "127.0.0.1", 5102, 20, 20, "Far", status="healthy", capacity_rps=10, utilization=0.01)
        nearest = rank_delivery_servers(0, 0, [near_busy, far_idle], policy="nearest-healthy")
        least = rank_delivery_servers(0, 0, [near_busy, far_idle], policy="least-utilized")
        self.assertEqual(nearest[0][1].server_id, "near")
        self.assertEqual(least[0][1].server_id, "far")

    def test_cache_action_changes_capacity_and_is_visible_in_virtual_telemetry(self):
        repository = self._repository()
        controller = SimulationController(repository, CDNHttpClient())
        controller.status()
        before = repository.state_ref().servers["cdn-a"].capacity_rps
        controller.update_server_cache("cdn-a", 3)
        controller.refresh_servers()
        after = repository.state_ref().servers["cdn-a"].capacity_rps
        self.assertGreater(after, before)

        service = ClientActivityService(repository, StreamService(CDNHttpClient(), repository))
        state = repository.state_ref()
        service._advance_virtual_clients(state, list(state.clients.values()), 1)
        self.assertGreater(state.servers["cdn-a"].cache_hits + state.servers["cdn-a"].cache_misses, 0)

    def test_fast_forensic_retry_is_bounded_and_not_a_fixed_five_minutes(self):
        repository = self._repository()
        watermark = WatermarkService("realism-test-secret")
        blacklist = BlacklistService(repository, CDNHttpClient(), watermark)
        monitor = MonitorService(repository, watermark, blacklist)
        state = repository.state_ref()
        state.config.update({"simulation_profile": "fast", "forensic_retry_base_seconds": 0.25, "forensic_max_attempts": 4})
        max_attempts, retry_delay, exhausted = monitor._retry_policy(state, {"analysis_count": 1})
        self.assertEqual(max_attempts, 4)
        self.assertLess(retry_delay, 300)
        self.assertFalse(exhausted)

    def test_discovered_simulated_copy_is_inspected_without_a_second_lottery(self):
        repository = self._repository()
        watermark = WatermarkService("realism-test-secret")
        monitor = MonitorService(repository, watermark, BlacklistService(repository, CDNHttpClient(), watermark))
        leak = {
            "media_path": "/simulated/leak.mp4",
            "media_sha256": "a" * 64,
            "client_id": "client-0",
            "origin_server_id": "cdn-a",
            "content_id": "movie-a",
            "piracy_detection_probability": 0.0,
        }
        self.assertTrue(monitor._detection_pass(repository.state_ref(), leak))

    def test_processed_forensic_sample_is_not_recaptured_indefinitely(self):
        repository = self._repository()
        state = repository.state_ref()
        suspect = state.clients["client-0"]
        suspect.malicious = True
        state.leaks.append({"leak_id": "completed", "client_id": suspect.client_id, "processed": True})
        service = LeakService(repository, StreamService(CDNHttpClient(), repository))
        self.assertNotIn(suspect, service._select_candidates(state))

    def test_end_archives_final_clients_and_operational_telemetry(self):
        repository = self._repository()
        controller = SimulationController(repository, CDNHttpClient())
        controller.status()
        archived = controller.end("test") ["history"]
        self.assertEqual(archived["clients_total"], 3)
        self.assertEqual(len(archived["clients"]), 3)
        self.assertTrue(archived["metrics_history"])
        final = archived["metrics_history"][-1]
        self.assertEqual(final["clients_total"], 3)
        self.assertIn("active_clients", final)
        self.assertIn("online_clients", final)


if __name__ == "__main__":
    unittest.main()

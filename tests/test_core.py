import unittest

from services.watermark_service import WatermarkService
from config import SimulationConfig
from utils.robust_watermark import assess_robustness
from utils.geo import haversine_km, load_global_cities
from utils.latency import propagation_delay_seconds
from repositories.in_memory import NodeRepository
from services.capacity_service import capacity_limits, profile_for_tier, service_metrics


class SecurityAndNetworkTests(unittest.TestCase):
    def test_watermark_identifies_client_server_and_chunk(self):
        service = WatermarkService("unit-test-secret")
        token, issued = service.issue("client-0001", "cdn-01", 4)
        claim = service.verify(token)
        self.assertEqual(claim.client_id, "client-0001")
        self.assertEqual(claim.server_id, "cdn-01")
        self.assertEqual(claim.chunk_id, issued.chunk_id)
        with self.assertRaises(ValueError):
            service.verify(token[:-1] + ("0" if token[-1] != "0" else "1"))

    def test_haversine_and_latency_are_distance_based(self):
        distance = haversine_km(-23.5505, -46.6333, 51.5072, -0.1276)
        self.assertGreater(distance, 9000)
        self.assertGreater(propagation_delay_seconds(distance, 2), propagation_delay_seconds(distance, 1))

    def test_city_catalog_is_external_and_global(self):
        cities = load_global_cities()
        self.assertGreaterEqual(len(cities), 100)
        self.assertTrue(any(city.name == "Tokyo" for city in cities))

    def test_robust_signal_survives_demo_filters(self):
        checks = assess_robustness(b"video-sample" * 100, "demo-token")
        self.assertTrue(all(check["survives"] for check in checks))
        self.assertGreaterEqual(checks[1]["confidence"], 0.9)

    def test_tick_interval_and_economics_are_configurable(self):
        config = SimulationConfig.from_payload({"tick_interval_seconds": 5, "monthly_client_price_usd": 40})
        self.assertEqual(config.tick_interval_seconds, 5)
        self.assertEqual(config.simulation_speed, 0.5)
        self.assertEqual(config.monthly_client_price_usd, 40)

    def test_capacity_is_tier_and_workload_based(self):
        basic = capacity_limits(profile_for_tier("basic"))
        pro = capacity_limits(profile_for_tier("pro"))
        self.assertGreater(pro["capacity_rps"], basic["capacity_rps"])
        self.assertGreater(service_metrics(profile_for_tier("basic"), 100)["utilization"], service_metrics(profile_for_tier("basic"), 1)["utilization"])

    def test_bounded_queue_rejects_only_after_capacity_and_queue_are_full(self):
        repository = NodeRepository()
        first = repository.begin_request(max_concurrent=1, max_queue_depth=1)
        second = repository.begin_request(max_concurrent=1, max_queue_depth=1, queue_wait_ms=20)
        third = repository.begin_request(max_concurrent=1, max_queue_depth=1, queue_wait_ms=40)
        self.assertTrue(first["accepted"])
        self.assertTrue(second["accepted"])
        self.assertFalse(third["accepted"])
        self.assertEqual(repository.request_metrics()["queue_rejected"], 1)
        repository.finish_request(queued=first["queued"])
        repository.finish_request(queued=second["queued"])

    def test_capacity_cache_and_slo_are_explicit(self):
        profile = profile_for_tier("standard")
        miss = service_metrics(profile, 8, cache_hit_rate=0)
        hit = service_metrics(profile, 8, cache_hit_rate=0.8)
        self.assertGreater(hit["capacity_rps"], miss["capacity_rps"])
        self.assertEqual(SimulationConfig.from_payload({"slo_p95_ms": 180, "demand_rps_per_client": 2}).slo_p95_ms, 180)


if __name__ == "__main__":
    unittest.main()


import os
import unittest
from unittest.mock import patch

from services.watermark_service import WatermarkService
from services.watermark_demo_service import WatermarkDemoService
from config import SimulationConfig
from utils.robust_watermark import assess_robustness
from utils.geo import haversine_km, load_global_cities
from utils.latency import propagation_delay_seconds


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

    def test_watermark_demo_uses_deterministic_fallback_without_dataset(self):
        with patch.dict(os.environ, {"USE_BIGBUCKBUNNY_DATASET": "0"}):
            result = WatermarkDemoService(WatermarkService("unit-test-secret")).run({})
        self.assertTrue(result["round_trip_verified"])
        self.assertEqual(result["video_source"], "fallback determinístico sem dataset")

    def test_tick_interval_and_economics_are_configurable(self):
        config = SimulationConfig.from_payload({"tick_interval_seconds": 10, "monthly_client_price_usd": 40})
        self.assertEqual(config.tick_interval_seconds, 10)
        self.assertEqual(config.simulation_speed, 0.25)
        self.assertEqual(config.monthly_client_price_usd, 40)


if __name__ == "__main__":
    unittest.main()


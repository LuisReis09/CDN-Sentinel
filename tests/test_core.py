import unittest

from services.watermark_service import WatermarkService
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


if __name__ == "__main__":
    unittest.main()


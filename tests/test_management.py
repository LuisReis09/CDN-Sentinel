import unittest

from management.engine import ManagementEngine
from models.entities import CDNServer, SimulationState
from repositories.in_memory import SimulationRepository
from services.catalog_service import MetadataCatalog


class FakeController:
    def __init__(self, repository):
        self.repository = repository
        self.next_id = 2

    def status(self):
        state = self.repository.snapshot()
        for server in state.servers.values():
            server.capacity_rps = 25 if server.capacity_tier == "basic" else 60
            server.health_status = server.status
        return {
            "scalability": {
                "capacity_rps": sum(server.capacity_rps for server in state.servers.values() if server.status == "healthy"),
                "p95_latency_ms": 120,
                "queue_depth": 0,
                "queue_rejected": 0,
            }
        }

    def add_server(self, payload):
        server_id = f"cdn-{self.next_id:02d}"
        self.next_id += 1
        server = CDNServer(server_id, "127.0.0.1", 5100 + self.next_id, payload["latitude"], payload["longitude"], payload.get("city", "gestão"), capacity_tier="basic", status="healthy", lifecycle_status="running", health_status="healthy")
        self.repository.add_server(server)
        return server.to_dict()

    def update_server_capacity(self, server_id, tier):
        server = self.repository.state_ref().servers[server_id]
        server.capacity_tier = tier
        server.status = "healthy"
        server.health_status = "healthy"
        return {"server": server.to_dict()}

    def retire_server(self, server_id):
        server = self.repository.state_ref().servers[server_id]
        server.status = "stopped"
        server.health_status = "offline"
        return server.to_dict()


class ManagementSimulationTests(unittest.TestCase):
    def setUp(self):
        self.repository = SimulationRepository()
        self.repository.replace(SimulationState(initialized=True, simulation_id="sim-test", lifecycle="running", config={"seed": 11, "demand_rps_per_client": 1.0, "monthly_client_price_usd": 25.0}, servers={"cdn-01": CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "A", status="healthy", lifecycle_status="running", health_status="healthy", capacity_tier="basic")}))
        self.engine = ManagementEngine(self.repository, FakeController(self.repository))
        self.engine.reset("free", 11)

    def test_registry_has_exactly_six_actions(self):
        self.assertEqual(self.engine.registry.action_types, ("horizontal_scale", "vertical_scale", "price_adjustment", "cache_upgrade", "load_balancing", "metadata_upgrade"))

    def test_metadata_index_is_a_real_distinct_in_memory_workload(self):
        catalog = MetadataCatalog()
        linear = catalog.workload(20, "linear")
        indexed = catalog.workload(20, "indexed")
        replica = catalog.workload(20, "read-replica")
        self.assertLess(indexed["lookup_ms"], linear["lookup_ms"])
        self.assertGreater(replica["staleness_ms"], 0)

    def test_horizontal_and_vertical_are_pending_then_applied(self):
        horizontal = self.engine.apply_action({"action_type": "horizontal_scale", "parameters": {"operation": "add", "latitude": 10, "longitude": 10}, "expected_version": self.engine.snapshot()["version"]})
        self.assertEqual(horizontal["action"]["status"], "pending")
        self.engine.tick()
        self.assertEqual(self.engine.snapshot()["day"], 1)
        self.engine.tick()
        self.assertEqual(len(self.engine.snapshot()["nodes"]), 2)
        version = self.engine.snapshot()["version"]
        action = self.engine.apply_action({"action_type": "vertical_scale", "parameters": {"server_id": "cdn-01", "tier": "standard"}, "expected_version": version})
        self.assertEqual(action["action"]["status"], "pending")
        self.engine.tick()
        self.assertEqual(self.engine.snapshot()["nodes"]["cdn-01"]["tier"], "standard")

    def test_price_cooldown_and_daily_accounting_are_bounded(self):
        initial_cash = self.engine.snapshot()["cash_balance_usd"]
        self.engine.apply_action({"action_type": "price_adjustment", "parameters": {"monthly_price_usd": 35}, "expected_version": self.engine.snapshot()["version"]})
        self.engine.tick()
        first = self.engine.snapshot()
        self.assertNotEqual(first["monthly_price_per_client_usd"], 25)
        self.assertLess(first["cash_balance_usd"], initial_cash)
        with self.assertRaises(ValueError):
            self.engine.apply_action({"action_type": "price_adjustment", "parameters": {"monthly_price_usd": 40}, "expected_version": first["version"]})


if __name__ == "__main__":
    unittest.main()

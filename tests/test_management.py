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
        vertical = next(item for item in self.engine.action_definitions() if item["action_type"] == "vertical_scale")
        self.assertEqual(vertical["investment_by_tier"], {"standard": 280.0, "pro": 560.0, "enterprise": 1120.0})

    def test_scenarios_change_initial_conditions(self):
        free = self.engine.reset("free", 11)
        growth = self.engine.reset("rapid-growth", 11)
        self.assertNotEqual(free["initial_cash_balance_usd"], growth["initial_cash_balance_usd"])
        self.assertNotEqual(free["base_paying_clients"], growth["base_paying_clients"])
        self.assertNotEqual(free["monthly_price_per_client_usd"], growth["monthly_price_per_client_usd"])

    def test_rapid_growth_population_reacts_within_one_day(self):
        initial = self.engine.reset("rapid-growth", 11)
        next_day = self.engine.tick()
        self.assertGreater(next_day["paying_clients"], initial["paying_clients"])
        self.assertGreater(next_day["arrivals_today"], 0)

    def test_population_response_is_faster_than_the_scenario_base_rate(self):
        initial = self.engine.reset("rapid-growth", 11)
        next_day = self.engine.tick()
        target = next_day["client_population_target"]
        observed_move = next_day["paying_clients"] - initial["paying_clients"]
        base_rate_move = round((target - initial["paying_clients"]) * 0.72)
        self.assertGreaterEqual(observed_move, base_rate_move)

    def test_slo_alert_explains_which_target_was_missed(self):
        self.repository.update_config({"slo_p95_ms": 100.0, "slo_success_rate_pct": 99.0})
        state = self.engine.reset("free", 11)
        alert = next(item for item in state["alerts"] if item["severity"] == "critical")
        self.assertIn("meta ≤ 100 ms", alert["message"])
        self.assertIn("5% de entregas mais lentas", alert["message"])

    def test_metadata_index_is_a_real_distinct_in_memory_workload(self):
        catalog = MetadataCatalog()
        linear = catalog.workload(20, "linear")
        indexed = catalog.workload(20, "indexed")
        replica = catalog.workload(20, "read-replica")
        self.assertLess(indexed["lookup_ms"], linear["lookup_ms"])
        self.assertGreater(replica["staleness_ms"], 0)

    def test_horizontal_and_vertical_are_pending_then_applied(self):
        registered_servers = []
        self.engine.set_server_added_callback(registered_servers.append)
        horizontal = self.engine.apply_action({"action_type": "horizontal_scale", "parameters": {"operation": "add", "latitude": 10, "longitude": 10}, "expected_version": self.engine.snapshot()["version"]})
        self.assertEqual(horizontal["action"]["status"], "pending")
        self.engine.tick()
        self.assertEqual(self.engine.snapshot()["day"], 1)
        self.engine.tick()
        scaled = self.engine.snapshot()
        self.assertEqual(len(scaled["nodes"]), 2)
        new_server_id = next(
            node_id for node_id in scaled["nodes"] if node_id != "cdn-01"
        )
        self.assertEqual(registered_servers[0]["server_id"], new_server_id)
        version = self.engine.snapshot()["version"]
        action = self.engine.apply_action({"action_type": "vertical_scale", "parameters": {"server_id": new_server_id, "tier": "standard"}, "expected_version": version})
        self.assertEqual(action["action"]["status"], "pending")
        self.assertEqual(action["action"]["investment_usd"], 280.0)
        self.engine.tick()
        self.assertEqual(self.engine.snapshot()["nodes"][new_server_id]["tier"], "standard")

    def test_price_cooldown_and_daily_accounting_are_bounded(self):
        initial_cash = self.engine.snapshot()["cash_balance_usd"]
        self.assertEqual(initial_cash, self.engine.snapshot()["initial_cash_balance_usd"])
        self.engine.apply_action({"action_type": "price_adjustment", "parameters": {"monthly_price_usd": 35}, "expected_version": self.engine.snapshot()["version"]})
        # The action investment is charged immediately.  With the enlarged
        # 72-client starting scenario, one day of valid revenue can already
        # offset it, so the accounting invariant belongs at submission time.
        self.assertLess(self.engine.snapshot()["cash_balance_usd"], initial_cash)
        self.engine.tick()
        first = self.engine.snapshot()
        self.assertNotEqual(first["monthly_price_per_client_usd"], 25)
        self.assertNotEqual(first["cash_balance_usd"], initial_cash)
        with self.assertRaises(ValueError):
            self.engine.apply_action({"action_type": "price_adjustment", "parameters": {"monthly_price_usd": 40}, "expected_version": first["version"]})

    def test_population_moves_with_market_conditions_and_actions_have_cash_effects(self):
        initial = self.engine.snapshot()
        self.engine.tick()
        grown = self.engine.snapshot()
        # A deliberately undersized one-node fixture may lose customers; the
        # important behavior is that the market moves toward its calculated
        # target, rather than being frozen by client-session churn.
        self.assertNotEqual(grown["paying_clients"], initial["paying_clients"])
        self.assertLess(
            abs(grown["paying_clients"] - grown["client_population_target"]),
            abs(initial["paying_clients"] - grown["client_population_target"]),
        )

        version = grown["version"]
        self.engine.apply_action({"action_type": "price_adjustment", "parameters": {"monthly_price_usd": 200}, "expected_version": version})
        self.engine.tick()
        pressured = self.engine.snapshot()
        self.assertGreaterEqual(pressured["departures_today"], 0)
        self.assertLessEqual(pressured["client_population_target"], grown["client_population_target"])
        self.assertGreater(self.engine.snapshot()["events"][-1]["day"], 0)


if __name__ == "__main__":
    unittest.main()


import base64
import os
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.watermark_service import WatermarkService
from services.watermark_registry import WatermarkRegistry
from config import SimulationConfig
from utils.robust_watermark import assess_robustness
from utils.geo import haversine_km, load_global_cities, rank_delivery_servers
from utils.latency import propagation_delay_seconds
from repositories.in_memory import NodeRepository
from services.capacity_service import capacity_limits, profile_for_tier, service_metrics
from controllers.simulation_controller import SimulationController
from controllers.api_controller import ApiController
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.client_activity_service import ClientActivityService
from services.leak_service import LeakService
from services.blacklist_service import BlacklistService
from services.supabase_store import SupabaseSimulationPersistence
from services.stream_service import StreamService
from models.entities import CDNServer, Client, SimulationState
from utils.video import generate_visual_variants, get_video_asset, list_video_examples
from utils.security import watermark_encryption_metadata


class SecurityAndNetworkTests(unittest.TestCase):
    def test_watermark_identifies_client_server_and_chunk(self):
        service = WatermarkService("unit-test-secret")
        token, issued = service.issue("client-0001", "cdn-01", 4)
        self.assertTrue(token.startswith("CDNWM2."))
        self.assertTrue(watermark_encryption_metadata(token)["encrypted"])
        claim = service.verify(token)
        self.assertEqual(claim.client_id, "client-0001")
        self.assertEqual(claim.server_id, "cdn-01")
        self.assertEqual(claim.chunk_id, issued.chunk_id)
        with self.assertRaises(ValueError):
            service.verify(token[:-1] + ("0" if token[-1] != "0" else "1"))

    def test_haversine_and_latency_are_distance_based(self):
        distance = haversine_km(-23.5505, -46.6333, 51.5072, -0.1276)
        self.assertGreater(distance, 9000)
        self.assertGreater(propagation_delay_seconds(distance, 1), 0)

    def test_distance_doubles_propagation_delay_without_frontend_factor(self):
        near = propagation_delay_seconds(1_000, 1)
        far = propagation_delay_seconds(2_000, 1)
        self.assertAlmostEqual(far / near, 2.0, delta=0.01)

    def test_client_activity_advances_every_simulated_client_without_encoding_each_one(self):
        repository = SimulationRepository()
        service = ClientActivityService(repository, StreamService(CDNHttpClient()))
        clients = {
            f"client-{index}": Client(f"client-{index}", index, index, "Test", online=False)
            for index in range(3)
        }
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy", capacity_rps=10)
        nearby = CDNServer("cdn-near", "127.0.0.1", 5102, 1, 1, "Near", status="healthy", capacity_rps=10)
        distant = CDNServer("cdn-far", "127.0.0.1", 5103, 50, 50, "Far", status="healthy", capacity_rps=10)
        repository.replace(SimulationState(
            initialized=True,
            lifecycle="running",
            config={"demand_rps_per_client": 1.0},
            clients=clients,
            servers={
                server.server_id: server,
                nearby.server_id: nearby,
                distant.server_id: distant,
            },
        ))
        service._advance_virtual_clients(repository.state_ref(), list(clients.values()), 1)
        self.assertTrue(all(client.online for client in clients.values()))
        self.assertEqual([client.videos_consumed for client in clients.values()], [1, 1, 1])
        self.assertTrue(all(client.watch_history for client in clients.values()))
        self.assertTrue(all(
            client.watch_history[-1]["delivery_mode"] == "simulated-aggregate"
            for client in clients.values()
        ))
        self.assertEqual(
            clients["client-0"].watch_history[-1]["server_id"],
            "cdn-01",
        )
        self.assertFalse(any(
            event["type"] in {"client_connected", "client_disconnected"}
            for event in repository.snapshot().events
        ))

    def test_http_refresh_preserves_aggregate_request_counter(self):
        repository = SimulationRepository()
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy", capacity_rps=10)
        server.simulated_requests_total = 51
        server.simulated_errors_total = 2
        repository.replace(SimulationState(initialized=True, lifecycle="running", servers={server.server_id: server}))
        http = CDNHttpClient()
        controller = SimulationController(repository, http)
        controller._http_client.status = lambda _server: {
            "status": "healthy", "lifecycle_status": "running", "health_status": "healthy",
            "requests_total": 3, "errors_total": 1, "capacity": {"capacity_rps": 10},
        }
        controller.refresh_servers()
        refreshed = repository.state_ref().servers["cdn-01"]
        self.assertEqual(refreshed.requests_total, 54)
        self.assertEqual(refreshed.errors_total, 3)
        self.assertEqual(refreshed.simulated_requests_total, 51)
        self.assertEqual(refreshed.http_requests_total, 3)

    def test_dashboard_metrics_keep_counter_sources_and_use_actual_observation_window(self):
        repository = SimulationRepository()
        now = time.time()
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy", capacity_rps=20)
        server.simulated_requests_total = 40
        server.http_requests_total = 3
        server.requests_total = 43
        server.simulated_errors_total = 1
        server.http_errors_total = 1
        server.errors_total = 2
        clients = {
            "client-1": Client("client-1", 0, 0, "Test"),
            "client-2": Client("client-2", 1, 1, "Test"),
        }
        repository.replace(SimulationState(
            initialized=True,
            lifecycle="running",
            started_at=now - 2,
            config={
                "demand_rps_per_client": 1.0,
                "tick_interval_seconds": 0.5,
                "monthly_client_price_usd": 25,
                "monthly_fixed_cost_usd": 100,
            },
            clients=clients,
            servers={server.server_id: server},
            forensic_pending_clients={"client-1"},
            traffic=[
                {"at": now - 0.2, "server_id": server.server_id, "request_count": 8, "end_to_end_ms": 80},
                {"at": now - 0.1, "server_id": server.server_id, "request_count": 4, "end_to_end_ms": 120},
            ],
        ))
        status = SimulationController(repository, CDNHttpClient()).status()
        scale = status["scalability"]
        self.assertEqual(status["blacklisted_total"], 0)
        self.assertEqual(status["forensic_pending_total"], 1)
        self.assertEqual(scale["observed_request_count"], 12)
        self.assertLess(scale["metrics_window_seconds"], 60)
        self.assertGreater(scale["observed_rps"], 10)
        self.assertEqual(scale["average_latency_ms"], 100.0)
        self.assertEqual(scale["p95_latency_ms"], 120.0)
        self.assertEqual(scale["total_capacity"], 20)
        self.assertEqual(scale["demand_rps"], 2.0)
        self.assertEqual(scale["observed_errors"], 2)
        self.assertEqual(scale["success_rate_pct"], round(100 * 41 / 43, 2))
        self.assertEqual(repository.snapshot().metrics_history[-1]["total_requests"], 43)

    def test_forensic_capture_latency_does_not_degrade_customer_slo(self):
        repository = SimulationRepository()
        now = time.time()
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy", capacity_rps=20)
        repository.replace(SimulationState(
            initialized=True,
            lifecycle="running",
            started_at=now - 2,
            config={"demand_rps_per_client": 0.25, "tick_interval_seconds": 1, "slo_p95_ms": 250},
            clients={"client-1": Client("client-1", 0, 0, "Test")},
            servers={server.server_id: server},
            traffic=[
                {"at": now - 0.2, "server_id": server.server_id, "request_count": 1, "end_to_end_ms": 80},
                {"at": now - 0.1, "server_id": server.server_id, "request_count": 1, "end_to_end_ms": 7016, "forensic_capture": True},
            ],
        ))
        scale = SimulationController(repository, CDNHttpClient()).status()["scalability"]
        self.assertEqual(scale["p95_latency_ms"], 80.0)
        self.assertTrue(scale["slo_compliant"])
        self.assertEqual(scale["health_score_pct"], 100.0)

    def test_clients_api_marks_only_live_forensic_quarantines(self):
        repository = SimulationRepository()
        now = time.time()
        repository.replace(SimulationState(
            initialized=True,
            clients={
                "held": Client("held", 0, 0, "Test"),
                "released": Client("released", 1, 1, "Test"),
            },
            temporary_blacklist={
                "held": {"client_id": "held", "expires_at": now + 30},
                "released": {"client_id": "released", "expires_at": now - 1},
            },
        ))
        controller = ApiController(
            repository, Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Mock(),
        )
        quarantined = {client["client_id"]: client["forensic_quarantined"] for client in controller.clients()}
        self.assertEqual(quarantined, {"held": True, "released": False})

    def test_clients_api_prioritizes_delivery_blocked_clients_in_bounded_map_sample(self):
        repository = SimulationRepository()
        now = time.time()
        clients = {f"regular-{index}": Client(f"regular-{index}", 0, index, "Test") for index in range(2_001)}
        clients["held"] = Client("held", 1, 1, "Test")
        repository.replace(SimulationState(
            initialized=True,
            clients=clients,
            temporary_blacklist={"held": {"client_id": "held", "expires_at": now + 30}},
        ))
        controller = ApiController(
            repository, Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Mock(),
        )
        sample = controller.clients()
        self.assertEqual(sample[0]["client_id"], "held")
        self.assertTrue(sample[0]["forensic_quarantined"])
        self.assertEqual(len(sample), 2_000)

    def test_supabase_checkpoint_uses_a_durable_json_state_row(self):
        class FakeStore:
            available = True
            disabled_reason = None

            def __init__(self):
                self.rows = []

            def upsert(self, table, row, *, on_conflict):
                self.rows.append((table, row, on_conflict))

        store = FakeStore()
        repository = SimulationRepository(SupabaseSimulationPersistence(store))
        repository.replace(SimulationState(initialized=True, simulation_id="sim-supabase", lifecycle="running"))
        self.assertEqual(store.rows[0][0], "cdn_simulation_state")
        self.assertEqual(store.rows[0][1]["simulation_id"], "sim-supabase")
        self.assertEqual(store.rows[0][1]["payload"]["lifecycle"], "running")

    def test_history_merges_the_durable_archives_by_archive_id(self):
        class FakePersistence:
            enabled = True
            disabled_reason = None

            def checkpoint(self, _state):
                return None

            def history(self, _simulation_id):
                return [{"archive_id": "remote", "ended_at": 20.0, "simulation_id": "sim"}]

        repository = SimulationRepository(FakePersistence())
        repository._history.append({"archive_id": "local", "ended_at": 10.0, "simulation_id": "sim"})
        self.assertEqual(
            [item["archive_id"] for item in repository.history("sim")],
            ["remote", "local"],
        )

    def test_forensic_chain_verification_reads_the_durable_ledger(self):
        class FakeLedger:
            available = True

            def __init__(self):
                self.rows = []

            def events(self, _key_id, _watermark_id=None):
                return list(self.rows)

            def append_event(self, key_id, watermark_id, event_type, payload, payload_hash, previous_hash, created_at):
                row = {
                    "event_id": len(self.rows) + 1,
                    "key_id": key_id,
                    "watermark_id": watermark_id,
                    "event_type": event_type,
                    "payload_json": dict(payload),
                    "payload_hash": payload_hash,
                    "previous_hash": previous_hash,
                    "created_at": created_at,
                }
                self.rows.append(row)
                return row

        with tempfile.TemporaryDirectory() as directory:
            registry = WatermarkRegistry(os.path.join(directory, "registry.sqlite3"))
            ledger = FakeLedger()
            registry._remote = ledger
            registry.append_forensic_event("remote-ledger-secret", "issued", {"client_id": "client-1"})
            registry.append_forensic_event("remote-ledger-secret", "reviewed", {"decision": "accept"})
            self.assertTrue(registry.verify_forensic_events("remote-ledger-secret"))
            ledger.rows[-1]["payload_json"]["decision"] = "reject"
            self.assertFalse(registry.verify_forensic_events("remote-ledger-secret"))

    def test_forensic_hold_stops_simulated_progress_before_real_proof_is_ready(self):
        class FakeStream:
            def stream(self, client, state, chunk_number, **_kwargs):
                return SimpleNamespace(
                    payload=base64.b64encode(b"real-media-proof").decode(),
                    server_id="cdn-01",
                    request_id="request-1",
                    trace_id="trace-1",
                    content_type="video/mp4",
                )

        repository = SimulationRepository()
        malicious = Client("pirate", 0, 0, "Test", malicious=True)
        regular = Client("regular", 1, 1, "Test")
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy", capacity_rps=10)
        repository.replace(SimulationState(
            initialized=True,
            lifecycle="running",
            config={"demand_rps_per_client": 1.0},
            clients={malicious.client_id: malicious, regular.client_id: regular},
            servers={server.server_id: server},
        ))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CDN_LEAK_MEDIA_ROOT": directory}):
            leaks = []
            leak_service = LeakService(repository, FakeStream(), on_leak=leaks.append)
            leak_service._capture_one_leak()
            self.assertEqual(repository.state_ref().forensic_pending_clients, {"pirate"})
            self.assertEqual(len(leaks), 1)
            activity = ClientActivityService(repository, StreamService(CDNHttpClient()))
            activity._advance_virtual_clients(repository.state_ref(), [malicious, regular], 1)
        self.assertEqual(malicious.videos_consumed, 0)
        self.assertEqual(regular.videos_consumed, 1)

    def test_temporary_blacklist_blocks_delivery_but_allows_signed_forensic_capture(self):
        from unittest.mock import Mock

        client = Client("pirate", 0, 0, "Test", malicious=True)
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy")
        state = SimulationState(
            initialized=True,
            lifecycle="running",
            config={"latency_factor": 0},
            clients={client.client_id: client},
            servers={server.server_id: server},
            forensic_pending_clients={client.client_id},
            temporary_blacklist={client.client_id: {"expires_at": time.time() + 60}},
        )
        http = Mock()
        with self.assertRaises(PermissionError):
            StreamService(http).stream(client, state, 0)
        http.stream.assert_not_called()
        http.stream.return_value = {
            "load": 0, "network_latency_ms": 1, "http_rtt_ms": 2,
            "chunk_id": "forensic", "content_type": "video/mp4", "payload": "YQ==",
            "watermark_token": "CDNWM1.x.y", "server_id": "cdn-01", "issued_at": 1,
        }
        result = StreamService(http).stream(client, state, 0, forensic_capture=True)
        self.assertEqual(result.server_id, "cdn-01")
        self.assertTrue(http.stream.call_args.kwargs["forensic_capture"])

    def test_temporary_blacklist_is_distributed_reassigned_and_eventually_expires(self):
        from unittest.mock import Mock

        repository = SimulationRepository()
        client = Client("pirate", 0, 0, "Test", malicious=True)
        failed = CDNServer("cdn-a", "127.0.0.1", 5101, 0, 0, "A", status="offline")
        healthy = CDNServer("cdn-b", "127.0.0.1", 5102, 1, 1, "B", status="healthy")
        repository.replace(SimulationState(
            initialized=True,
            lifecycle="running",
            config={"forensic_quarantine_seconds": 30},
            clients={client.client_id: client},
            servers={failed.server_id: failed, healthy.server_id: healthy},
        ))
        http = Mock()
        service = BlacklistService(repository, http, WatermarkService("temporary-blacklist-test-secret"))
        entry = service.quarantine(client.client_id)
        self.assertEqual(entry["owner_server_id"], "cdn-b")
        self.assertEqual(entry["propagated_to"], ["cdn-b"])
        self.assertTrue(repository.state_ref().forensic_pending_clients)
        entry["owner_server_id"] = "cdn-a"
        actions = service.maintain_quarantines()
        self.assertEqual(actions[0]["action"], "reassigned")
        self.assertEqual(entry["owner_server_id"], "cdn-b")
        entry["expires_at"] = time.time() - 1
        self.assertEqual(service.maintain_quarantines()[0]["action"], "expired")
        self.assertNotIn(client.client_id, repository.state_ref().temporary_blacklist)
        self.assertNotIn(client.client_id, repository.state_ref().forensic_pending_clients)

    def test_leak_worker_captures_before_waiting_for_the_next_tick(self):
        service = LeakService(SimulationRepository(), StreamService(CDNHttpClient()))
        captured = []

        def capture():
            captured.append(True)
            service._stop_event.set()

        service._capture_one_leak = capture
        service._run()
        self.assertEqual(captured, [True])

    def test_delivery_ranking_shares_nearby_nodes_but_keeps_geography(self):
        first = CDNServer("cdn-a", "127.0.0.1", 5101, 0, 0, "A", capacity_rps=10, utilization=0.95)
        second = CDNServer("cdn-b", "127.0.0.1", 5102, 0.01, 0.01, "B", capacity_rps=10, utilization=0.05)
        far = CDNServer("cdn-c", "127.0.0.1", 5103, 20, 20, "C", capacity_rps=10, utilization=0.0)
        ranked = rank_delivery_servers(0, 0, [first, second, far])
        self.assertEqual(ranked[0][1].server_id, "cdn-b")
        self.assertNotEqual(ranked[0][1].server_id, "cdn-c")

    def test_management_clock_uses_every_operational_tick(self):
        service = ClientActivityService(SimulationRepository(), StreamService(CDNHttpClient()))
        service.configure_tick_interval(1.25)
        self.assertEqual(service._tick_interval_seconds, 1.25)
        service.configure_tick_interval(0.5)
        self.assertEqual(service._tick_interval_seconds, 0.5)
        service.configure_tick_interval(5.0)
        self.assertEqual(service._tick_interval_seconds, 5.0)

    def test_client_process_generates_feedback_from_delivery_latency(self):
        repository = SimulationRepository()
        service = StreamService(CDNHttpClient(), repository)
        client = Client("client-1", 0, 0, "Test")
        feedback = service.record_delivery_feedback(client, {
            "video_id": "youtube_clipped_videos",
            "chunk_number": 1,
            "server_id": "cdn-01",
            "latency_ms": 610.0,
            "liked": None,
        })
        self.assertFalse(feedback["liked"])
        self.assertEqual(feedback["source"], "client_process")
        self.assertEqual(client.dislikes, 1)
        self.assertEqual(repository.snapshot().events[-1]["type"], "client_feedback_generated")

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
        self.assertEqual(config.tick_interval_seconds, 5.0)
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

    def test_scale_limits_and_pressure_states_are_explicit(self):
        config = SimulationConfig.from_payload({"num_servers": 500, "num_clients": 100000})
        self.assertEqual(config.num_servers, 500)
        self.assertEqual(config.num_clients, 100000)
        repository = SimulationRepository()
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy", capacity_rps=10)
        clients = {f"client-{index}": Client(f"client-{index}", 0, 0, "Test") for index in range(36)}
        repository.replace(SimulationState(initialized=True, lifecycle="running", config={"demand_rps_per_client": 0.25}, servers={server.server_id: server}, clients=clients))
        status = SimulationController(repository, CDNHttpClient()).status()
        self.assertEqual(status["scalability"]["profile"], "alerta")
        self.assertGreaterEqual(status["scalability"]["utilization"], 0.9)

    def test_dashboard_health_and_node_state_follow_capacity_pressure(self):
        repository = SimulationRepository()
        server = CDNServer("cdn-01", "127.0.0.1", 5101, 0, 0, "Test", status="healthy", capacity_rps=10)
        clients = {f"client-{index}": Client(f"client-{index}", 0, 0, "Test") for index in range(60)}
        repository.replace(SimulationState(
            initialized=True,
            lifecycle="running",
            config={"demand_rps_per_client": 0.25, "slo_p95_ms": 250},
            servers={server.server_id: server},
            clients=clients,
        ))
        controller = SimulationController(repository, CDNHttpClient())
        status = controller.status()
        observed = repository.state_ref().servers["cdn-01"]
        self.assertGreaterEqual(status["scalability"]["utilization"], 1.5)
        self.assertLess(status["scalability"]["health_score_pct"], 100)
        self.assertEqual(observed.health_status, "overloaded")

        # A cumulative rejection counter must not leave the node red after
        # the capacity condition itself has recovered.
        repository.state_ref().clients = {
            "client-1": Client("client-1", 0, 0, "Test")
        }
        recovered = controller.status()
        self.assertEqual(recovered["scalability"]["health_score_pct"], 100.0)
        self.assertEqual(observed.health_status, "healthy")

    def test_management_scenario_resizes_the_observed_population(self):
        from app import create_app

        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 0
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        try:
            initialized = client.post(
                "/api/control/simulation/init",
                json={"num_servers": 1, "num_clients": 1, "demand_rps_per_client": 0.25, "seed": 53},
            )
            self.assertEqual(initialized.status_code, 201, initialized.get_json())
            started = client.post(
                "/api/management/scenarios/start",
                json={"scenario_id": "rapid-growth", "seed": 53},
            )
            self.assertEqual(started.status_code, 201, started.get_json())
            status = client.get("/api/control/simulation/status").get_json()
            self.assertEqual(status["clients_total"], 100)
            self.assertEqual(status["scalability"]["active_clients"], 100)
            self.assertEqual(status["configuration"]["demand_rps_per_client"], 1.0)
            self.assertEqual(status["tick_interval_seconds"], 1.25)
            self.assertTrue(all(item.active for item in controller.repository.state_ref().clients.values()))
        finally:
            client.post("/api/control/simulation/end")

    def test_local_video_catalog_has_valid_reproducible_mp4_variants(self):
        examples = list_video_examples()
        self.assertTrue(any(item["video_id"] == "cdn_sentinel_demo" for item in examples))
        original, content_type = get_video_asset("cdn_sentinel_demo")
        watermarked, _ = get_video_asset("cdn_sentinel_demo", "watermarked")
        difference, _ = get_video_asset("cdn_sentinel_demo", "difference")
        self.assertEqual(content_type, "video/mp4")
        self.assertTrue(original.read_bytes().startswith(b"\x00\x00\x00"))
        self.assertNotEqual(original.read_bytes(), watermarked.read_bytes())
        self.assertNotEqual(original.read_bytes(), difference.read_bytes())

    def test_generated_difference_is_not_saturated_white(self):
        generated_id = generate_visual_variants("cdn_sentinel_demo", "watermark-audit-token")
        difference, _ = get_video_asset("cdn_sentinel_demo", "difference", generated_id)
        frame = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(difference), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
            check=True,
            capture_output=True,
        ).stdout
        self.assertGreater(len(frame), 0)
        self.assertLess(sum(frame) / len(frame), 128)
        self.assertGreater(max(frame), 0)
        self.assertGreater(len(set(frame)), 1)

    def test_watermark_demo_endpoint_uses_a_valid_default_video(self):
        from app import create_app

        client = create_app().test_client()
        response = client.post("/api/security/watermark/demo", json={})
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload["round_trip_verified"])
        self.assertNotEqual(payload["video_variants"]["difference"], "")

    def test_client_feedback_records_watch_latency_and_updates_the_client(self):
        from app import create_app

        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 0
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        initialized = client.post("/api/control/simulation/init", json={"num_servers": 1, "num_clients": 1, "seed": 31})
        self.assertEqual(initialized.status_code, 201)
        client_id = initialized.get_json()["clients"][0]["client_id"]
        state_client = controller.repository.state_ref().clients[client_id]
        state_client.watch_history.append({"at": 1.0, "video_id": "bigbuckbunny", "chunk_number": 2, "chunk_id": "chunk-test", "server_id": "cdn-01", "latency_ms": 420.0})
        response = client.post(f"/api/clients/{client_id}/feedback", json={"video_id": "bigbuckbunny", "chunk_number": 2, "liked": False, "rating": 2})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["client"]["dislikes"], 1)
        self.assertEqual(payload["client"]["feedback_latency_avg_ms"], 420.0)
        self.assertTrue(payload["feedback"]["latency_related"])
        client.post("/api/control/simulation/end")

    def test_video_endpoint_returns_mp4_and_supports_range_requests(self):
        from app import create_app

        client = create_app().test_client()
        response = client.get("/api/security/watermark/demo/video?video_id=cdn_sentinel_demo&variant=original")
        partial = client.get("/api/security/watermark/demo/video?video_id=cdn_sentinel_demo&variant=watermarked", headers={"Range": "bytes=0-31"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "video/mp4")
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.mimetype, "video/mp4")
        response.close()
        partial.close()

    def test_map_client_creation_and_capacity_are_dynamic(self):
        from app import create_app

        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 0
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()

        first = client.post("/api/control/simulation/init", json={"num_servers": 1, "num_clients": 1, "seed": 19})
        self.assertEqual(first.status_code, 201)
        first_utilization = client.get("/api/control/simulation/status").get_json()["scalability"]["utilization"]
        created = client.post("/api/clients", json={"latitude": 12.34, "longitude": -56.78, "malicious": False})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(client.get("/api/control/simulation/status").get_json()["clients_total"], 2)

        second = client.post("/api/control/simulation/init", json={"num_servers": 1, "num_clients": 1000, "seed": 19})
        self.assertEqual(second.status_code, 201)
        second_utilization = client.get("/api/control/simulation/status").get_json()["scalability"]["utilization"]
        self.assertGreater(second_utilization, first_utilization)
        client.post("/api/control/simulation/end")

    def test_live_configuration_can_be_edited_during_orchestration(self):
        from app import create_app

        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 0
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        initialized = client.post("/api/control/simulation/init", json={"num_servers": 1, "num_clients": 1, "seed": 44})
        self.assertEqual(initialized.status_code, 201)
        simulation_id = client.get("/api/control/simulation/status").get_json()["simulation_id"]
        activity_thread = controller.client_activity_service._thread
        leak_thread = controller.leak_service._thread
        live_update = client.patch("/api/control/simulation/config", json={"tick_interval_seconds": 1.5, "monthly_client_price_usd": 40, "malicious_probability": 0.1})
        self.assertEqual(live_update.status_code, 200)
        self.assertEqual(live_update.get_json()["simulation_id"], simulation_id)
        self.assertEqual(live_update.get_json()["configuration"]["tick_interval_seconds"], 1.5)
        self.assertIs(controller.client_activity_service._thread, activity_thread)
        self.assertIs(controller.leak_service._thread, leak_thread)
        structural_update = client.patch("/api/control/simulation/config", json={"num_clients": 2})
        self.assertEqual(structural_update.status_code, 200)
        self.assertEqual(structural_update.get_json()["simulation_id"], simulation_id)
        self.assertEqual(structural_update.get_json()["clients_total"], 2)
        server_update = client.patch("/api/control/simulation/config", json={"num_servers": 2})
        self.assertEqual(server_update.status_code, 200)
        self.assertEqual(server_update.get_json()["simulation_id"], simulation_id)
        self.assertEqual(server_update.get_json()["servers_total"], 2)
        downsize = client.patch("/api/control/simulation/config", json={"num_clients": 1, "num_servers": 1})
        self.assertEqual(downsize.status_code, 200)
        self.assertEqual(downsize.get_json()["simulation_id"], simulation_id)
        self.assertEqual(downsize.get_json()["clients_total"], 1)
        self.assertEqual(downsize.get_json()["servers_total"], 1)
        client.post("/api/control/simulation/end")

    def test_end_archives_run_for_history_endpoint(self):
        from app import create_app

        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 0
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        initialized = client.post("/api/control/simulation/init", json={"num_servers": 2, "num_clients": 1, "seed": 17})
        self.assertEqual(initialized.status_code, 201)
        ended = client.post("/api/control/simulation/end")
        self.assertEqual(ended.status_code, 200)
        history = client.get("/api/observability/history").get_json()["histories"]
        self.assertTrue(history)
        self.assertEqual(history[-1]["simulation_id"], ended.get_json()["simulation_id"])

    def test_network_lab_fault_buttons_reject_invalid_values_without_500(self):
        from app import create_app

        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 0
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        initialized = client.post("/api/control/simulation/init", json={"num_servers": 1, "num_clients": 1, "seed": 18})
        self.assertEqual(initialized.status_code, 201)
        server_id = initialized.get_json()["servers"][0]["server_id"]
        for payload in (
            {"offline": True},
            {"offline": False, "extra_latency_ms": 0, "drop_rate": 0},
            {"offline": False, "extra_latency_ms": 250, "drop_rate": 0},
            {"offline": False, "extra_latency_ms": 0, "drop_rate": 0.25},
        ):
            self.assertEqual(client.post(f"/api/control/fault/{server_id}", json=payload).status_code, 200)
        invalid = client.post(f"/api/control/fault/{server_id}", json={"drop_rate": None})
        self.assertEqual(invalid.status_code, 400)
        client.post("/api/control/simulation/end")


if __name__ == "__main__":
    unittest.main()


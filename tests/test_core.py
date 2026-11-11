import subprocess
import unittest

from services.watermark_service import WatermarkService
from config import SimulationConfig
from utils.robust_watermark import assess_robustness
from utils.geo import haversine_km, load_global_cities
from utils.latency import propagation_delay_seconds
from repositories.in_memory import NodeRepository
from services.capacity_service import capacity_limits, profile_for_tier, service_metrics
from controllers.simulation_controller import SimulationController
from repositories.in_memory import SimulationRepository
from services.cdn_http_client import CDNHttpClient
from services.client_activity_service import ClientActivityService
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

    def test_client_session_churn_is_bidirectional_after_first_video(self):
        repository = SimulationRepository()
        service = ClientActivityService(repository, StreamService(CDNHttpClient()))
        client = Client("client-1", 0, 0, "Test", online=False)
        service._maybe_toggle_client(client, 1)
        self.assertTrue(client.online)
        client.videos_consumed = 1
        service.session_transition_probability = 1.0
        service._maybe_toggle_client(client, 2)
        self.assertFalse(client.online)
        service._maybe_toggle_client(client, 3)
        self.assertTrue(client.online)

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


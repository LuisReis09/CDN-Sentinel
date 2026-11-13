import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from app import create_app


class WatermarkE2EForensicsTests(unittest.TestCase):
    def test_real_node_media_is_playable_and_monitor_detects_reencoded_leak(self):
        fixture = tempfile.TemporaryDirectory(prefix="cdn-forensic-source-")
        source = Path(fixture.name) / "e2e.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", "data/media/bigbuckbunny.mp4",
            "-t", "6", "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "23", str(source),
        ], check=True, capture_output=True, timeout=60)
        env_updates = {
            "CDN_DATASET_ROOT": fixture.name,
            "CDN_REQUIRE_VIEWER_AUTH": "1",
            "CDN_VIEWER_SESSION_SECRET": "e2e-viewer-secret-with-high-entropy-2026",
            "CDN_CONTROL_TOKEN": "e2e-operator-token-2026",
        }
        previous_env = {key: os.environ.get(key) for key in env_updates}
        os.environ.update(env_updates)
        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 1
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        operator_headers = {"X-CDN-Control-Token": env_updates["CDN_CONTROL_TOKEN"]}
        try:
            initialized = client.post(
                "/api/control/simulation/init",
                json={"num_servers": 1, "num_clients": 2, "malicious_probability": 0, "seed": 121, "base_node_port": 5921, "tick_interval_seconds": 5, "video_id": "youtube_clipped_videos"},
                headers=operator_headers,
            )
            self.assertEqual(initialized.status_code, 201, initialized.get_json())
            controller.client_activity_service.stop()
            controller.leak_service.stop()
            client_id = initialized.get_json()["clients"][0]["client_id"]
            innocent_id = initialized.get_json()["clients"][1]["client_id"]

            self.assertEqual(client.get(f"/api/clients/{client_id}/media?chunk=0").status_code, 401)
            grant = client.post(f"/api/clients/{client_id}/viewer-sessions", json={}, headers=operator_headers)
            self.assertEqual(grant.status_code, 201, grant.get_json())
            viewer_headers = {"Authorization": f"Bearer {grant.get_json()['token']}"}
            self.assertEqual(client.get(f"/api/clients/{innocent_id}/media?chunk=0", headers=viewer_headers).status_code, 401)
            delivered = client.get(f"/api/clients/{client_id}/media?chunk=0", headers=viewer_headers)
            self.assertEqual(delivered.status_code, 200, delivered.get_json())
            self.assertTrue(delivered.data[4:8] == b"ftyp")
            self.assertEqual(delivered.headers.get("X-Watermark-Visual"), "embedded-in-video-frames")
            self.assertNotIn("X-Watermark-Token", delivered.headers)
            self.assertNotIn("X-Watermark-Chunk", delivered.headers)
            delivered_again = client.get(f"/api/clients/{client_id}/media?chunk=0", headers=viewer_headers)
            self.assertEqual(delivered_again.status_code, 200, delivered_again.get_json())
            self.assertEqual(delivered_again.data, delivered.data)

            other_grant = client.post(f"/api/clients/{innocent_id}/viewer-sessions", json={}, headers=operator_headers)
            self.assertEqual(other_grant.status_code, 201, other_grant.get_json())
            other = client.get(f"/api/clients/{innocent_id}/media?chunk=0", headers={"Authorization": f"Bearer {other_grant.get_json()['token']}"})
            self.assertEqual(other.status_code, 200, other.get_json())
            self.assertNotEqual(other.data, delivered.data)
            self.assertNotIn("X-Watermark-Token", other.headers)

            with tempfile.TemporaryDirectory(prefix="cdn-watermark-e2e-") as temporary:
                root = Path(temporary)
                marked = root / "marked.mp4"
                leaked = root / "leaked.mp4"
                marked.write_bytes(delivered.data)
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-v", "error", "-i", str(marked),
                        "-map", "0:v:0", "-map_metadata", "-1", "-an",
                        "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p", str(leaked),
                    ],
                    check=True,
                    capture_output=True,
                )
                self.assertEqual(
                    subprocess.run(
                        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1", str(leaked)],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    "h264",
                )
                controller.repository.append_leak({
                    "leak_id": "leak-e2e-reencoded",
                    "client_id": "unknown",
                    "server_id": "cdn-01",
                    "media_path": str(leaked),
                    "processed": False,
                    "trace_id": "trace-e2e-reencoded",
                    "request_id": "request-e2e-reencoded",
                })
                scan = controller.scan("cdn-01")
                self.assertEqual(len(scan["detected"]), 1, scan)
                self.assertEqual(scan["detected"][0]["claim"]["client_id"], client_id)
                self.assertEqual(scan["detected"][0]["claim"]["session_id"], grant.get_json()["session_id"])
                self.assertEqual(scan["detected"][0]["forensic_source"], "visual-media")
                self.assertEqual(scan["detected"][0]["decision"], "PENDING_REVIEW")
                self.assertNotEqual(scan["detected"][0]["claim"]["client_id"], innocent_id)
                self.assertEqual(scan["detected"][0]["blacklist"]["client_id"], client_id)
                self.assertEqual(len(controller.repository.blacklist_values()), 1)
                self.assertEqual(controller.repository.blacklist_values()[0].client_id, client_id)

                with leaked.open("rb") as file:
                    uploaded = client.post("/api/monitor/investigations", data={"file": (file, "leaked.mp4")}, content_type="multipart/form-data", headers=operator_headers)
                self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
                self.assertEqual(uploaded.get_json()["session_id"], scan["detected"][0]["claim"]["session_id"])
                self.assertEqual(uploaded.get_json()["content_match"]["status"], "MATCH")
                self.assertFalse(uploaded.get_json()["blacklist_changed"])
                investigation_id = uploaded.get_json()["investigation_id"]
                reviewed = client.post(
                    f"/api/monitor/investigations/{investigation_id}/review",
                    json={"decision": "ACCEPT", "reviewer": "test-operator"},
                    headers=operator_headers,
                )
                self.assertEqual(reviewed.status_code, 200, reviewed.get_json())
                self.assertEqual(reviewed.get_json()["administrative_action"], "NO_AUTOMATIC_BLACKLIST")
                self.assertEqual(len(controller.repository.blacklist_values()), 1)
                self.assertEqual(controller.repository.blacklist_values()[0].client_id, client_id)
                repeated = client.post(
                    f"/api/monitor/investigations/{investigation_id}/review",
                    json={"decision": "ACCEPT", "reviewer": "test-operator"},
                    headers=operator_headers,
                )
                self.assertEqual(repeated.status_code, 400)
                controller.monitor_service.stop()
                controller.repository.append_leak({
                    "leak_id": "leak-needs-reanalysis", "client_id": "untrusted-simulator-hint",
                    "server_id": "cdn-01", "media_path": str(source), "processed": False,
                    "created_at": 0.0,
                })
                first_attempt = controller.scan("cdn-01")
                self.assertEqual(first_attempt["scanned"], 1)
                self.assertEqual(first_attempt["detected"], [])
                second_attempt = controller.scan("cdn-01")
                self.assertEqual(second_attempt["scanned"], 1)
                pending = next(leak for leak in controller.repository.state_ref().leaks if leak["leak_id"] == "leak-needs-reanalysis")
                self.assertTrue(pending["analyzed"])
                self.assertFalse(pending["attributed"])
                self.assertFalse(pending["processed"])
                self.assertTrue(pending["needs_reanalysis"])
                self.assertEqual(pending["analysis_count"], 2)
                public = next(leak for leak in controller.leaks() if leak["leak_id"] == "leak-needs-reanalysis")
                self.assertNotIn("client_id", public)
                self.assertNotIn("media_path", public)
        finally:
            controller.end()
            for key, previous in previous_env.items():
                if previous is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = previous
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()

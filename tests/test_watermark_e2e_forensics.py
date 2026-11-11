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
        previous_dataset_root = os.environ.get("CDN_DATASET_ROOT")
        os.environ["CDN_DATASET_ROOT"] = fixture.name
        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 1
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        try:
            initialized = client.post(
                "/api/control/simulation/init",
                json={"num_servers": 1, "num_clients": 2, "malicious_probability": 0, "seed": 121, "base_node_port": 5921, "tick_interval_seconds": 5, "video_id": "youtube_clipped_videos"},
            )
            self.assertEqual(initialized.status_code, 201, initialized.get_json())
            client_id = initialized.get_json()["clients"][0]["client_id"]
            innocent_id = initialized.get_json()["clients"][1]["client_id"]

            delivered = client.get(f"/api/clients/{client_id}/media?chunk=0")
            self.assertEqual(delivered.status_code, 200, delivered.get_json())
            self.assertTrue(delivered.data[4:8] == b"ftyp")
            self.assertEqual(delivered.headers.get("X-Watermark-Visual"), "embedded-in-video-frames")
            self.assertNotIn("X-Watermark-Token", delivered.headers)
            self.assertNotIn("X-Watermark-Chunk", delivered.headers)

            other = client.get(f"/api/clients/{innocent_id}/media?chunk=0")
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
                self.assertEqual(scan["detected"][0]["forensic_source"], "visual-media")
                self.assertEqual(scan["detected"][0]["decision"], "PENDING_REVIEW")
                self.assertNotEqual(scan["detected"][0]["claim"]["client_id"], innocent_id)
                self.assertEqual(controller.repository.blacklist_values(), [])

                with leaked.open("rb") as file:
                    uploaded = client.post("/api/monitor/investigations", data={"file": (file, "leaked.mp4")}, content_type="multipart/form-data")
                self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
                self.assertEqual(uploaded.get_json()["session_id"], scan["detected"][0]["claim"]["session_id"])
                self.assertEqual(uploaded.get_json()["content_match"]["status"], "MATCH")
                self.assertFalse(uploaded.get_json()["blacklist_changed"])
                investigation_id = uploaded.get_json()["investigation_id"]
                reviewed = client.post(
                    f"/api/monitor/investigations/{investigation_id}/review",
                    json={"decision": "ACCEPT", "reviewer": "test-operator"},
                )
                self.assertEqual(reviewed.status_code, 200, reviewed.get_json())
                self.assertEqual(reviewed.get_json()["administrative_action"], "NO_AUTOMATIC_BLACKLIST")
                self.assertEqual(controller.repository.blacklist_values(), [])
                repeated = client.post(
                    f"/api/monitor/investigations/{investigation_id}/review",
                    json={"decision": "ACCEPT", "reviewer": "test-operator"},
                )
                self.assertEqual(repeated.status_code, 400)
        finally:
            controller.end()
            if previous_dataset_root is None:
                os.environ.pop("CDN_DATASET_ROOT", None)
            else:
                os.environ["CDN_DATASET_ROOT"] = previous_dataset_root
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()

import subprocess
import tempfile
import unittest
from pathlib import Path

from app import create_app


class WatermarkE2EForensicsTests(unittest.TestCase):
    def test_real_node_media_is_playable_and_monitor_detects_reencoded_leak(self):
        app = create_app()
        controller = app.extensions["cdn_controller"]
        controller.simulation_controller._real_node_process_limit = 1
        controller.simulation_controller._real_client_process_limit = 0
        client = app.test_client()
        try:
            initialized = client.post(
                "/api/control/simulation/init",
                json={"num_servers": 1, "num_clients": 1, "seed": 121, "base_node_port": 5921},
            )
            self.assertEqual(initialized.status_code, 201, initialized.get_json())
            client_id = initialized.get_json()["clients"][0]["client_id"]

            delivered = client.get(f"/api/clients/{client_id}/media?chunk=0")
            self.assertEqual(delivered.status_code, 200)
            self.assertTrue(delivered.data[4:8] == b"ftyp")
            self.assertEqual(delivered.headers.get("X-Watermark-Visual"), "embedded-in-video-frames")

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
                self.assertIn(client_id, {entry.client_id for entry in controller.repository.blacklist_values()})
        finally:
            controller.end()


if __name__ == "__main__":
    unittest.main()

"""Regression coverage for the real HTTP-node forensic pipeline.

This deliberately exercises the same path used by the browser: a real node
resolves a concrete dataset asset, emits a two-second QIM3 sample, the monitor
recovers the watermark, and the controller exposes the permanent ban.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app


class HttpSimulationForensicsTests(unittest.TestCase):
    def test_malicious_http_client_is_permanently_banned_within_twenty_seconds(self):
        with tempfile.TemporaryDirectory(prefix="cdn-http-forensic-") as directory:
            root = Path(directory)
            environment = {
                "CDN_WATERMARK_REGISTRY_PATH": str(root / "ledger.sqlite3"),
                "CDN_WATERMARK_CACHE_ROOT": str(root / "watermarked"),
                "CDN_LEAK_MEDIA_ROOT": str(root / "leaks"),
                # Keep this test deterministic and local even when a
                # developer's .env has Supabase credentials.
                "SUPABASE_URL": "",
                "SUPABASE_SECRET_KEY": "",
            }
            with patch.dict(os.environ, environment, clear=False):
                app = create_app()
                controller = app.extensions["cdn_controller"]
                controller.simulation_controller._real_node_process_limit = 1
                controller.simulation_controller._real_client_process_limit = 0
                client = app.test_client()
                started = time.monotonic()
                try:
                    response = client.post(
                        "/api/control/simulation/init",
                        json={
                            "num_servers": 1,
                            "num_clients": 1,
                            "malicious_probability": 1.0,
                            "simulation_profile": "realistic",
                            "forensic_capture_workers": 1,
                            "tick_interval_seconds": 1.25,
                            "base_node_port": 6391,
                            "seed": 881,
                        },
                    )
                    self.assertEqual(response.status_code, 201, response.get_json())
                    controller.client_activity_service.stop()
                    client_id = response.get_json()["clients"][0]["client_id"]
                    deadline = started + 20.0
                    while time.monotonic() < deadline:
                        if client_id in controller.repository.state_ref().blacklist:
                            break
                        time.sleep(0.2)

                    state = controller.repository.state_ref()
                    self.assertIn(client_id, state.blacklist)
                    self.assertFalse(state.clients[client_id].active)
                    self.assertNotIn(client_id, state.temporary_blacklist)
                    self.assertLess(time.monotonic() - started, 20.0)
                    leak = next(item for item in state.leaks if item["client_id"] == client_id)
                    self.assertEqual(leak["forensic_state"], "confirmed")
                    self.assertEqual(leak["forensic_status"], "VALID")
                    self.assertEqual(
                        leak["content_id"],
                        leak["forensic_evidence"]["claim"]["content_id"],
                    )

                    overview = client.get("/api/observability/overview")
                    self.assertEqual(overview.status_code, 200, overview.get_json())
                    visible = next(item for item in overview.get_json()["clients"] if item["client_id"] == client_id)
                    self.assertTrue(visible["blacklist_permanent"])
                    self.assertFalse(visible["forensic_quarantined"])
                    self.assertEqual(client.get(f"/api/clients/{client_id}/stream").status_code, 403)
                finally:
                    controller.end()


if __name__ == "__main__":
    unittest.main()

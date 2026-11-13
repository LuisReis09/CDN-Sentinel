import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from PIL import Image

from services.watermark_registry import WatermarkRegistry, WatermarkRegistryCollision
from services.watermark_service import WatermarkService
from watermark.claims import ClaimError, create_claim_token, verify_claim_token
from watermark.ecc import ReedSolomonCodec, deinterleave, interleave


class ForensicClaimTests(unittest.TestCase):
    def test_claim_rotation_tampering_expiry_and_persistence(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = WatermarkRegistry(Path(temporary) / "ledger.sqlite3")
            service = WatermarkService("primary-secret-with-entropy-2026", registry)
            old_token, old_claim = service.issue_forensic_claim(client_id="client-a", server_id="edge-a", content_id="youtube_clipped_videos/videos/example.mp4")
            self.assertEqual(service.verify(old_token).watermark_id, old_claim.watermark_id)
            with self.assertRaises(ClaimError):
                verify_claim_token(old_token, "wrong-secret-with-entropy-2026")
            with self.assertRaises(ClaimError):
                verify_claim_token(old_token, "primary-secret-with-entropy-2026", now=time.time() + 100_000)
            with self.assertRaises(ValueError):
                service.verify(old_token[:-1] + ("0" if old_token[-1] != "0" else "1"))
            service.rotate_key("secondary", "secondary-secret-with-entropy-2026")
            new_token, new_claim = service.issue_forensic_claim(client_id="client-b", server_id="edge-a", content_id="bigbuckbunny")
            self.assertEqual(new_claim.key_id, "secondary")
            self.assertEqual(service.verify(old_token).client_id, "client-a")
            self.assertEqual(service.verify(new_token).client_id, "client-b")
            reopened = WatermarkService("primary-secret-with-entropy-2026", WatermarkRegistry(registry.path))
            reopened.rotate_key("secondary", "secondary-secret-with-entropy-2026")
            self.assertEqual(reopened.verify(new_token).client_id, "client-b")
            self.assertIsNotNone(reopened._registry_store.claim_for_marker("primary-secret-with-entropy-2026", __import__("utils.image_watermark", fromlist=["visual_marker"]).visual_marker(old_token)))
            session_token, session_claim = service.issue_forensic_claim(
                client_id="client-a", server_id="edge-a", content_id="bigbuckbunny",
                session_id="view-repeated-session-2026", segment_range="0-0", algorithm_id="dct-qim-v2",
            )
            repeated_token, repeated_claim = service.issue_forensic_claim(
                client_id="client-a", server_id="edge-a", content_id="bigbuckbunny",
                session_id="view-repeated-session-2026", segment_range="0-0", algorithm_id="dct-qim-v2",
            )
            self.assertEqual(repeated_token, session_token)
            self.assertEqual(repeated_claim.watermark_id, session_claim.watermark_id)
            reopened_token, _ = reopened.issue_forensic_claim(
                client_id="client-a", server_id="edge-a", content_id="bigbuckbunny",
                session_id="view-repeated-session-2026", segment_range="0-0", algorithm_id="dct-qim-v2",
                key_id="secondary",
            )
            self.assertEqual(reopened_token, session_token)
            failover_token, failover_claim = service.issue_forensic_claim(
                client_id="client-a", server_id="edge-b", content_id="bigbuckbunny",
                session_id="view-repeated-session-2026", segment_range="0-0", algorithm_id="dct-qim-v2",
            )
            self.assertNotEqual(failover_token, session_token)
            self.assertEqual(failover_claim.session_id, session_claim.session_id)
            with self.assertRaises(ValueError):
                service.issue_forensic_claim(
                    client_id="client-b", server_id="edge-a", content_id="bigbuckbunny",
                    session_id="view-repeated-session-2026", segment_range="0-0", algorithm_id="dct-qim-v2",
                )

    def test_ledger_collision_and_event_integrity(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = WatermarkRegistry(Path(temporary) / "ledger.sqlite3")
            service = WatermarkService("ledger-test-secret-with-entropy", registry)
            token, claim = service.issue_forensic_claim(client_id="client-a", server_id="edge-a", content_id="bigbuckbunny")
            from utils.image_watermark import visual_marker
            marker = visual_marker(token)
            with self.assertRaises(WatermarkRegistryCollision):
                registry.put("ledger-test-secret-with-entropy", marker, "different-token", time.time())
            event = registry.append_forensic_event(service.secret_key, "TEST", {"watermark_id": claim.watermark_id}, claim.watermark_id)
            self.assertEqual(registry.forensic_events(service.secret_key, claim.watermark_id)[0]["payload_hash"], event["payload_hash"])
            other_secret = "other-ledger-test-secret-2026"
            registry.append_forensic_event(other_secret, "OTHER", {"ok": True})
            self.assertTrue(registry.verify_forensic_events(service.secret_key))
            self.assertTrue(registry.verify_forensic_events(other_secret))
            self.assertEqual(len(registry.forensic_events(service.secret_key)), 1)
            with closing(sqlite3.connect(registry.path)) as connection, connection:
                connection.execute("UPDATE forensic_events SET payload_json = ? WHERE payload_hash = ?", ('{"tampered":true}', event["payload_hash"]))
            self.assertFalse(registry.verify_forensic_events(service.secret_key))
            self.assertTrue(registry.verify_forensic_events(other_secret))

    def test_ecc_detects_corruption_and_interleaving_round_trip(self):
        codec = ReedSolomonCodec(16)
        codeword = codec.encode(b"forensic")
        self.assertEqual(codec.decode(codeword), (b"forensic", 0))
        damaged = bytearray(codeword)
        damaged[2] ^= 1
        with self.assertRaises(ValueError):
            codec.decode(bytes(damaged))
        self.assertEqual(deinterleave(interleave(codeword, 5), 5), codeword)


if __name__ == "__main__":
    unittest.main()

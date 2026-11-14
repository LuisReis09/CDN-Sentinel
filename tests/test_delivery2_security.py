import copy
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

from models.entities import CDNServer, Client, SimulationState
from node_app import CDNNode, create_node_app
from repositories.in_memory import SimulationRepository
from services.stream_service import StreamService
from utils.protocol import signed_headers, verify_headers
from utils.crypto import encrypt_payload
from utils.security import create_watermark_token


class Delivery2SecurityTests(unittest.TestCase):
    def test_node_delivery_issues_cdnwm4_qim3_claim(self):
        class LocalVideo:
            def get_chunk(self, content_id, chunk_number):
                return b"synthetic-video", "video/mp4"

            def resolve_asset(self, content_id, chunk_number=0):
                raise FileNotFoundError(content_id)

        with tempfile.TemporaryDirectory() as temporary:
            previous = os.environ.get("CDN_WATERMARK_REGISTRY_PATH")
            os.environ["CDN_WATERMARK_REGISTRY_PATH"] = str(Path(temporary) / "ledger.sqlite3")
            try:
                node = CDNNode("cdn-current", "127.0.0.1", 59990, 0, 0, "Test", "current-watermark-secret-2026", 0, content_provider=LocalVideo())
                node._watermarked_media = Mock(return_value=b"marked-video")
                result = node.stream("client-current", 2, "youtube_clipped_videos/videos/clip.mp4")
                self.assertTrue(result["watermark_token"].startswith("CDNWM4."))
                self.assertEqual(result["watermark_version"], "CDNWM4")
                self.assertEqual(result["watermark_algorithm"], "dct-qim-v3")
                self.assertTrue(result["watermark_id"])
                node._watermarked_media.assert_called_once()
                self.assertEqual(node._watermarked_media.call_args.args[-1], "qim3")
            finally:
                node._retry_stop.set()
                if previous is None:
                    os.environ.pop("CDN_WATERMARK_REGISTRY_PATH", None)
                else:
                    os.environ["CDN_WATERMARK_REGISTRY_PATH"] = previous

    def test_internal_protocol_has_timestamp_nonce_and_replay_protection(self):
        seen = set()

        def remember(nonce):
            if nonce in seen:
                return False
            seen.add(nonce)
            return True

        headers = signed_headers("secret", "POST", "/internal/config", {"latency_factor": 2})
        valid, reason = verify_headers("secret", "POST", "/internal/config", {"latency_factor": 2}, headers, remember)
        self.assertTrue(valid, reason)
        valid, reason = verify_headers("secret", "POST", "/internal/config", {"latency_factor": 2}, headers, remember)
        self.assertFalse(valid)
        self.assertIn("nonce", reason)

    def test_node_rejects_unauthenticated_and_forged_blacklist(self):
        node = CDNNode("cdn-test", "127.0.0.1", 59991, 0, 0, "Test", "secret", 1)
        client = create_node_app(node).test_client()
        self.assertEqual(client.get("/internal/status").status_code, 401)
        token = create_watermark_token("client-1", "cdn-test", 1.0, "chunk-1", "secret")
        entry = {"client_id": "client-1", "watermark_server_id": "cdn-test", "proof_signature": "wrong", "proof_token": token}
        headers = signed_headers("secret", "POST", "/internal/blacklist", {"entry": entry})
        response = client.post("/internal/blacklist", json={"entry": entry}, headers=headers)
        self.assertEqual(response.status_code, 403)
        node._retry_stop.set()

    def test_node_accepts_signed_and_encrypted_internal_configuration(self):
        node = CDNNode("cdn-test", "127.0.0.1", 59992, 0, 0, "Test", "secret", 1)
        client = create_node_app(node).test_client()
        cleartext = {"latency_factor": 2}
        payload = encrypt_payload(cleartext, "secret", aad="/internal/config")
        response = client.post(
            "/internal/config",
            json=payload,
            headers=signed_headers("secret", "POST", "/internal/config", payload),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["latency_factor"], 2.0)
        node._retry_stop.set()

    def test_node_enforces_and_releases_a_leased_temporary_blacklist(self):
        node = CDNNode("cdn-test", "127.0.0.1", 59993, 0, 0, "Test", "secret", 1)
        client = create_node_app(node).test_client()
        entry = {
            "client_id": "client-1",
            "quarantine_id": "quarantine-test",
            "expires_at": time.time() + 30,
        }
        payload = encrypt_payload({"entry": entry}, "secret", aad="/internal/quarantine")
        response = client.post(
            "/internal/quarantine",
            json=payload,
            headers=signed_headers("secret", "POST", "/internal/quarantine", payload),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(node.repository.is_temporarily_blacklisted("client-1"))
        release = encrypt_payload({"client_id": "client-1", "quarantine_id": "quarantine-test"}, "secret", aad="/internal/quarantine/release")
        response = client.post(
            "/internal/quarantine/release",
            json=release,
            headers=signed_headers("secret", "POST", "/internal/quarantine/release", release),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(node.repository.is_temporarily_blacklisted("client-1"))
        node._retry_stop.set()

    def test_snapshot_does_not_expose_live_mutable_state(self):
        repository = SimulationRepository()
        state = SimulationState(initialized=True, clients={"c": Client("c", 0, 0, "Test")})
        repository.replace(state)
        snapshot = repository.snapshot()
        snapshot.clients["c"].city = "altered"
        self.assertEqual(repository.snapshot().clients["c"].city, "Test")

    def test_stream_fails_over_to_next_healthy_candidate(self):
        first = CDNServer("cdn-a", "127.0.0.1", 5101, 0, 0, "A")
        second = CDNServer("cdn-b", "127.0.0.1", 5102, 10, 10, "B")
        client = Client("client-1", 0, 0, "Test")
        state = SimulationState(initialized=True, config={"latency_factor": 0}, clients={client.client_id: client}, servers={first.server_id: first, second.server_id: second})
        http = Mock()
        http.stream.side_effect = [requests.ConnectionError("offline"), {"load": 0, "network_latency_ms": 1, "http_rtt_ms": 2, "chunk_id": "chunk", "content_type": "video/mp4", "payload": "YQ==", "watermark_token": "CDNWM1.x.y", "server_id": "cdn-b", "issued_at": 1}]
        result = StreamService(http).stream(client, state, 0, "request-1")
        self.assertEqual(result.server_id, "cdn-b")
        self.assertIn("failover", result.routing_reason)
        self.assertEqual(first.status, "offline")

    def test_stream_fails_over_when_first_node_has_not_received_blacklist(self):
        first = CDNServer("cdn-a", "127.0.0.1", 5101, 0, 0, "A")
        second = CDNServer("cdn-b", "127.0.0.1", 5102, 10, 10, "B")
        client = Client("client-1", 0, 0, "Test")
        state = SimulationState(initialized=True, config={"latency_factor": 0}, clients={client.client_id: client}, servers={first.server_id: first, second.server_id: second})
        blocked = requests.HTTPError("local blacklist")
        blocked.response = Mock(status_code=403)
        http = Mock()
        http.stream.side_effect = [blocked, {"load": 0, "network_latency_ms": 1, "http_rtt_ms": 2, "chunk_id": "chunk", "content_type": "video/mp4", "payload": "YQ==", "watermark_token": "CDNWM1.x.y", "server_id": "cdn-b", "issued_at": 1}]
        result = StreamService(http).stream(client, state, 0, "request-blacklist-propagation")
        self.assertEqual(result.server_id, "cdn-b")
        self.assertIn("blacklist local", result.routing_candidates[0]["reason"])


if __name__ == "__main__":
    unittest.main()

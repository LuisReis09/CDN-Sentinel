import json
import os
import unittest
from unittest.mock import patch

from app import create_app
from services.operator_auth_service import hash_password


class OperatorAuthTests(unittest.TestCase):
    def test_secure_mode_protects_reads_mutations_roles_and_expired_sessions(self):
        accounts = {
            "alice": {"role": "operator", "password_hash": hash_password("correct-password-operator")},
            "ruth": {"role": "reviewer", "password_hash": hash_password("correct-password-reviewer")},
        }
        with patch.dict(os.environ, {
            "CDN_AUTH_MODE": "secure",
            "CDN_OPERATOR_ACCOUNTS": json.dumps(accounts),
            "CDN_SECRET_KEY": "secure-test-key-with-at-least-32-chars",
            "CDN_VIEWER_SESSION_SECRET": "secure-test-viewer-key-with-32-chars",
            "CDN_CORS_ORIGINS": "",
        }):
            app = create_app()
        client = app.test_client()
        self.assertEqual(client.get("/api/observability/overview").status_code, 401)
        self.assertNotIn("Access-Control-Allow-Origin", client.get("/api/observability/overview", headers={"Origin": "https://evil.example"}).headers)
        self.assertEqual(client.get("/api/monitor/leaks").status_code, 401)
        self.assertEqual(client.post("/api/security/watermark/verify", json={"token": "x"}).status_code, 401)
        login = client.post("/api/auth/login", json={"username": "alice", "password": "correct-password-operator"})
        self.assertEqual(login.status_code, 200, login.get_json())
        self.assertIn("HttpOnly", login.headers["Set-Cookie"])
        self.assertIn("Secure", login.headers["Set-Cookie"])
        self.assertEqual(client.get("/api/observability/overview").status_code, 200)
        self.assertEqual(client.post("/api/control/simulation/pause").status_code, 403)
        self.assertEqual(client.post("/api/auth/logout", headers={"X-CDN-CSRF": login.get_json()["csrf"]}).status_code, 200)
        self.assertEqual(client.get("/api/observability/overview").status_code, 401)
        reviewer = client.post("/api/auth/login", json={"username": "ruth", "password": "correct-password-reviewer"})
        self.assertEqual(reviewer.status_code, 200)
        self.assertEqual(client.get("/api/observability/overview").status_code, 403)
        with patch.object(app.extensions["cdn_controller"].forensic_investigation_service, "review", return_value={"reviewer": "ruth"}) as reviewed:
            response = client.post("/api/monitor/investigations/missing/review", json={"decision": "REJECT", "reviewer": "forged"}, headers={"X-CDN-CSRF": reviewer.get_json()["csrf"]})
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()["reviewer"], "ruth")
            self.assertEqual(reviewed.call_args.args[2], "ruth")
        with patch("services.operator_auth_service.time.time", return_value=10**12):
            self.assertEqual(client.get("/api/auth/session").status_code, 401)

    def test_secure_mode_refuses_incomplete_configuration(self):
        with patch.dict(os.environ, {"CDN_AUTH_MODE": "secure", "CDN_OPERATOR_ACCOUNTS": "", "CDN_SECRET_KEY": "short"}):
            with self.assertRaises(ValueError):
                create_app()

    def test_local_mode_refuses_public_bind_without_explicit_ack(self):
        with patch.dict(os.environ, {"CDN_AUTH_MODE": "local", "CDN_BIND_HOST": "0.0.0.0", "CDN_LOCAL_BIND_ACK": ""}):
            with self.assertRaises(ValueError):
                create_app()


if __name__ == "__main__":
    unittest.main()

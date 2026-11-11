import unittest

from services.viewer_session_service import ViewerSessionService


class ViewerSessionTests(unittest.TestCase):
    def test_grant_is_bound_to_client_content_run_and_expiry(self):
        service = ViewerSessionService("viewer-test-secret-with-high-entropy-2026")
        grant = service.issue("client-a", "movie-a", "sim-a", ttl_seconds=60)
        self.assertEqual(
            service.verify(grant["token"], "client-a", "movie-a", "sim-a", now=grant["issued_at"])["session_id"],
            grant["session_id"],
        )
        for client, content, simulation in (
            ("client-b", "movie-a", "sim-a"),
            ("client-a", "movie-b", "sim-a"),
            ("client-a", "movie-a", "sim-b"),
        ):
            with self.assertRaises(PermissionError):
                service.verify(grant["token"], client, content, simulation)
        with self.assertRaises(PermissionError):
            service.verify(grant["token"], "client-a", "movie-a", "sim-a", now=grant["valid_until"] + 1)
        altered = grant["token"][:-1] + ("0" if grant["token"][-1] != "0" else "1")
        with self.assertRaises(PermissionError):
            service.verify(altered, "client-a", "movie-a", "sim-a")


if __name__ == "__main__":
    unittest.main()

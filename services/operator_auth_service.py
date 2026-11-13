"""Small local identity boundary for the administrative API.

Accounts are supplied by the operator through backend configuration. Sessions
are opaque, revocable and kept in process; a shared session store is required
before running more than one API worker in secure mode.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque


ROLES = {"operator", "investigator", "reviewer"}
SESSION_SECONDS = 900


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = 310_000) -> str:
    if len(password) < 16:
        raise ValueError("password must have at least 16 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


class OperatorAuthService:
    def __init__(self, accounts_json: str) -> None:
        try:
            accounts = json.loads(accounts_json)
            if not isinstance(accounts, dict) or not accounts:
                raise ValueError("accounts must be a nonempty mapping")
            for username, account in accounts.items():
                if not isinstance(username, str) or not username or len(username) > 80:
                    raise ValueError("invalid username")
                if not isinstance(account, dict) or account.get("role") not in ROLES:
                    raise ValueError("invalid role")
                self._parse_hash(account.get("password_hash"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("CDN_OPERATOR_ACCOUNTS must contain valid password hashes and roles") from exc
        self._accounts = accounts
        self._sessions: dict[str, dict] = {}
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.RLock()

    @staticmethod
    def _parse_hash(encoded: str) -> tuple[int, bytes, bytes]:
        scheme, iterations_text, salt_hex, digest_hex = encoded.split("$")
        iterations = int(iterations_text)
        salt, digest = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if scheme != "pbkdf2_sha256" or iterations < 200_000 or len(salt) < 16 or len(digest) != 32:
            raise ValueError("invalid password hash")
        return iterations, salt, digest

    def _allow(self, bucket: dict[str, deque[float]], key: str, count: int, window: int) -> bool:
        now = time.monotonic()
        with self._lock:
            entries = bucket[key]
            while entries and entries[0] <= now - window:
                entries.popleft()
            if len(entries) >= count:
                return False
            entries.append(now)
            return True

    def allow_login(self, remote_address: str) -> bool:
        return self._allow(self._attempts, remote_address, 10, 60)

    def allow_processing(self, username: str) -> bool:
        return self._allow(self._requests, username, 12, 60)

    def login(self, username: str, password: str, user_agent: str) -> dict | None:
        account = self._accounts.get(username) if isinstance(username, str) else None
        # Keep the PBKDF2 path for unknown users to reduce username probing.
        encoded = account["password_hash"] if account else hash_password("invalid-account-password")
        iterations, salt, expected = self._parse_hash(encoded)
        supplied = hashlib.pbkdf2_hmac("sha256", str(password).encode(), salt, iterations)
        if not account or not hmac.compare_digest(supplied, expected):
            return None
        session_id = secrets.token_urlsafe(32)
        session = {
            "username": username, "role": account["role"],
            "csrf": secrets.token_urlsafe(32),
            "user_agent_hash": hashlib.sha256(user_agent.encode()).digest(),
            "expires_at": int(time.time()) + SESSION_SECONDS,
        }
        with self._lock:
            self._sessions[session_id] = session
        return {**session, "session_id": session_id}

    def session(self, session_id: str, user_agent: str) -> dict | None:
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None
            if session["expires_at"] < time.time():
                del self._sessions[session_id]
                return None
            user_agent_hash = hashlib.sha256(user_agent.encode()).digest()
            if not hmac.compare_digest(session["user_agent_hash"], user_agent_hash):
                return None
            return dict(session)

    def revoke(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

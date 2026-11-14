from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from threading import RLock

from services.supabase_store import SupabaseLedgerBackend, SupabaseUnavailable


class WatermarkRegistryCollision(ValueError):
    """Raised when two authenticated tokens claim the same visual marker."""


class WatermarkRegistry:
    """Durable marker-to-token index used by forensic attribution."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.getenv("CDN_WATERMARK_REGISTRY_PATH")
        # Explicit paths are used by tests and local forensic exports. The
        # normal application registry mirrors to Supabase and retains SQLite
        # only as an outage-safe forensic fallback.
        self._remote = SupabaseLedgerBackend.from_environment() if path is None and not configured else None
        self.path = (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[1] / "data" / "runtime" / "watermark_registry.sqlite3"
        ).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    @staticmethod
    def key_id(secret_key: str) -> str:
        return hashlib.sha256(secret_key.encode("utf-8")).hexdigest()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS watermark_registry (
                        key_id TEXT NOT NULL,
                        marker TEXT NOT NULL,
                        token TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        algorithm_version TEXT NOT NULL DEFAULT 'CDNIMG5-SECDED-48',
                        PRIMARY KEY (key_id, marker)
                    )
                    """
                )
                try:
                    connection.execute(
                        "ALTER TABLE watermark_registry ADD COLUMN algorithm_version TEXT NOT NULL DEFAULT 'CDNIMG5-SECDED-48'"
                    )
                except sqlite3.OperationalError:
                    pass
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS watermark_registry_token_idx ON watermark_registry(key_id, token)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forensic_claims (
                        watermark_id TEXT PRIMARY KEY,
                        key_id TEXT NOT NULL,
                        marker TEXT NOT NULL,
                        claim_token TEXT NOT NULL,
                        claim_json TEXT NOT NULL,
                        claim_hash TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        session_id TEXT,
                        content_id TEXT,
                        segment_range TEXT,
                        algorithm_id TEXT,
                        server_id TEXT,
                        UNIQUE(key_id, marker)
                    )
                    """
                )
                for column in ("session_id", "content_id", "segment_range", "algorithm_id", "server_id"):
                    try:
                        connection.execute(f"ALTER TABLE forensic_claims ADD COLUMN {column} TEXT")
                    except sqlite3.OperationalError:
                        pass
                connection.execute("DROP INDEX IF EXISTS forensic_claims_session_idx")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS forensic_claims_session_node_idx ON forensic_claims(key_id, session_id, content_id, segment_range, algorithm_id, server_id) WHERE session_id IS NOT NULL"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forensic_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key_id TEXT,
                        watermark_id TEXT,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        previous_hash TEXT,
                        created_at REAL NOT NULL
                    )
                    """
                )
                try:
                    connection.execute("ALTER TABLE forensic_events ADD COLUMN key_id TEXT")
                except sqlite3.OperationalError:
                    pass
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS forensic_events_watermark_idx ON forensic_events(watermark_id, created_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS forensic_events_key_idx ON forensic_events(key_id, event_id)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ab_sessions (
                        session_id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL,
                        content_id TEXT NOT NULL,
                        watermark_id TEXT NOT NULL,
                        cache_id TEXT NOT NULL,
                        fingerprint TEXT NOT NULL,
                        record_mac TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        UNIQUE(content_id, fingerprint)
                    )
                    """
                )
                connection.execute("CREATE INDEX IF NOT EXISTS ab_sessions_content_idx ON ab_sessions(content_id, fingerprint)")

    def _remote_call(self, operation):
        if not self._remote or not self._remote.available:
            return False, None
        try:
            return True, operation(self._remote)
        except SupabaseUnavailable:
            self._remote = None
            return False, None

    def put(self, secret_key: str, marker: str, token: str, created_at: float) -> None:
        key_id = self.key_id(secret_key)
        try:
            mirrored, _ = self._remote_call(
                lambda remote: remote.put_marker(key_id, marker, token, float(created_at), "CDNIMG5-SECDED-48")
            )
        except ValueError as exc:
            raise WatermarkRegistryCollision(str(exc)) from exc
        with self._lock, closing(self._connect()) as connection:
            with connection:
                existing = connection.execute(
                    "SELECT token FROM watermark_registry WHERE key_id = ? AND marker = ?",
                    (key_id, marker),
                ).fetchone()
                if existing and str(existing[0]) != token:
                    raise WatermarkRegistryCollision(
                        "colisão de marcador visual: dois tokens autenticados usam o mesmo marcador"
                    )
                connection.execute(
                    """
                    INSERT INTO watermark_registry(key_id, marker, token, created_at, algorithm_version)
                    VALUES (?, ?, ?, ?, 'CDNIMG5-SECDED-48')
                    ON CONFLICT(key_id, marker) DO UPDATE SET token=excluded.token, created_at=excluded.created_at,
                        algorithm_version=excluded.algorithm_version
                    """,
                    (key_id, marker, token, float(created_at)),
                )

    def load(self, secret_key: str) -> dict[str, str]:
        key_id = self.key_id(secret_key)
        mirrored, rows = self._remote_call(lambda remote: remote.load_markers(key_id))
        if mirrored:
            return rows
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT marker, token FROM watermark_registry WHERE key_id = ?", (key_id,),
            ).fetchall()
        return {str(marker): str(token) for marker, token in rows}

    def put_claim(self, secret_key: str, marker: str, token: str, claim: dict) -> None:
        """Persist a versioned claim and its exact marker atomically."""
        watermark_id = str(claim.get("watermark_id") or "")
        if not watermark_id:
            raise ValueError("claim sem watermark_id")
        canonical = json.dumps(claim, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        claim_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key_id = self.key_id(secret_key)
        try:
            self._remote_call(
                lambda remote: remote.put_claim(key_id, marker, token, claim, claim_hash)
            )
        except ValueError as exc:
            raise WatermarkRegistryCollision(str(exc)) from exc
        with self._lock, closing(self._connect()) as connection:
            with connection:
                existing = connection.execute(
                    "SELECT claim_hash FROM forensic_claims WHERE watermark_id = ?", (watermark_id,)
                ).fetchone()
                if existing and str(existing[0]) != claim_hash:
                    raise WatermarkRegistryCollision("watermark_id já associado a claim diferente")
                existing_marker = connection.execute(
                    "SELECT token FROM watermark_registry WHERE key_id = ? AND marker = ?", (key_id, marker)
                ).fetchone()
                if existing_marker and str(existing_marker[0]) != token:
                    raise WatermarkRegistryCollision("colisão de marcador visual: dois tokens autenticados usam o mesmo marcador")
                connection.execute(
                    """
                    INSERT INTO watermark_registry(key_id, marker, token, created_at, algorithm_version)
                    VALUES (?, ?, ?, ?, 'CDNWM4-SECDED48')
                    ON CONFLICT(key_id, marker) DO UPDATE SET token=excluded.token, created_at=excluded.created_at,
                        algorithm_version=excluded.algorithm_version
                    """,
                    (key_id, marker, token, float(claim.get("issued_at", time.time()))),
                )
                connection.execute(
                    """
                    INSERT INTO forensic_claims(watermark_id, key_id, marker, claim_token, claim_json, claim_hash, created_at, session_id, content_id, segment_range, algorithm_id, server_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(watermark_id) DO UPDATE SET marker=excluded.marker, claim_token=excluded.claim_token,
                        claim_json=excluded.claim_json, claim_hash=excluded.claim_hash,
                        session_id=excluded.session_id, content_id=excluded.content_id,
                        segment_range=excluded.segment_range, algorithm_id=excluded.algorithm_id,
                        server_id=excluded.server_id
                    """,
                    (watermark_id, key_id, marker, token, canonical, claim_hash, time.time(),
                     claim.get("session_id"), claim.get("content_id"), claim.get("segment_range"), claim.get("algorithm_id"), claim.get("server_id")),
                )

    def claim_for_session(self, secret_key: str, session_id: str, content_id: str, segment_range: str, algorithm_id: str, server_id: str) -> dict | None:
        key_id = self.key_id(secret_key)
        mirrored, remote_row = self._remote_call(
            lambda remote: remote.claim_for_session(key_id, session_id, content_id, segment_range, algorithm_id, server_id)
        )
        if mirrored:
            if not remote_row:
                return None
            payload = remote_row["claim"]
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != remote_row["claim_hash"]:
                raise ValueError("integridade do claim da sessÃ£o invÃ¡lida")
            return {"claim_token": remote_row["claim_token"], "claim": payload}
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT claim_token, claim_json, claim_hash FROM forensic_claims WHERE key_id = ? AND session_id = ? AND content_id = ? AND segment_range = ? AND algorithm_id = ? AND server_id = ?",
                (self.key_id(secret_key), session_id, content_id, segment_range, algorithm_id, server_id),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(str(row[1]))
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != str(row[2]):
            raise ValueError("integridade do claim da sessão inválida")
        return {"claim_token": str(row[0]), "claim": payload}

    def claim_for_marker(self, secret_key: str, marker: str) -> dict | None:
        key_id = self.key_id(secret_key)
        mirrored, remote_row = self._remote_call(lambda remote: remote.claim_for_marker(key_id, marker))
        if mirrored:
            if not remote_row:
                return None
            payload = remote_row["claim"]
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != remote_row["claim_hash"]:
                raise ValueError("integridade do claim no ledger invÃ¡lida")
            return remote_row
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT watermark_id, claim_token, claim_json, claim_hash FROM forensic_claims WHERE key_id = ? AND marker = ?",
                (self.key_id(secret_key), marker),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(str(row[2]))
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != str(row[3]):
            raise ValueError("integridade do claim no ledger inválida")
        return {"watermark_id": str(row[0]), "claim_token": str(row[1]), "claim": payload, "claim_hash": str(row[3])}

    def append_forensic_event(self, secret_key: str, event_type: str, payload: dict, watermark_id: str | None = None) -> dict:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        key_id = self.key_id(secret_key)
        mirrored, remote_events = self._remote_call(lambda remote: remote.events(key_id))
        if mirrored:
            previous_hash = remote_events[-1]["payload_hash"] if remote_events else None
            signed = json.dumps([event_type, watermark_id, previous_hash, canonical], separators=(",", ":"), ensure_ascii=False)
            payload_hash = hmac.new(secret_key.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()
            written, _ = self._remote_call(
                lambda remote: remote.append_event(key_id, watermark_id, event_type, payload, payload_hash, previous_hash, time.time())
            )
            if written:
                return {"event_type": event_type, "watermark_id": watermark_id, "payload_hash": payload_hash, "previous_hash": previous_hash}
        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                previous = connection.execute(
                    "SELECT payload_hash FROM forensic_events WHERE key_id = ? ORDER BY event_id DESC LIMIT 1",
                    (key_id,),
                ).fetchone()
                previous_hash = str(previous[0]) if previous else None
                signed = json.dumps([event_type, watermark_id, previous_hash, canonical], separators=(",", ":"), ensure_ascii=False)
                payload_hash = hmac.new(secret_key.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()
                connection.execute(
                    "INSERT INTO forensic_events(key_id, watermark_id, event_type, payload_json, payload_hash, previous_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (key_id, watermark_id, event_type, canonical, payload_hash, previous_hash, time.time()),
                )
        return {"event_type": event_type, "watermark_id": watermark_id, "payload_hash": payload_hash, "previous_hash": previous_hash}

    def forensic_events(self, secret_key: str, watermark_id: str | None = None) -> list[dict]:
        key_id = self.key_id(secret_key)
        mirrored, remote_rows = self._remote_call(lambda remote: remote.events(key_id, watermark_id))
        if mirrored:
            return [
                {
                    "event_id": row["event_id"], "watermark_id": row.get("watermark_id"),
                    "event_type": row["event_type"], "payload": row["payload_json"],
                    "payload_hash": row["payload_hash"], "previous_hash": row.get("previous_hash"),
                    "created_at": row["created_at"],
                }
                for row in remote_rows
            ]
        query = "SELECT event_id, watermark_id, event_type, payload_json, payload_hash, previous_hash, created_at FROM forensic_events WHERE key_id = ?"
        args: tuple = (key_id,)
        if watermark_id:
            query += " AND watermark_id = ?"
            args = (self.key_id(secret_key), watermark_id)
        query += " ORDER BY event_id"
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(query, args).fetchall()
        return [{"event_id": row[0], "watermark_id": row[1], "event_type": row[2], "payload": json.loads(row[3]), "payload_hash": row[4], "previous_hash": row[5], "created_at": row[6]} for row in rows]

    def verify_forensic_events(self, secret_key: str) -> bool:
        # Go through the public reader so verification follows the active
        # durable backend.  With Supabase configured, events are deliberately
        # not duplicated into SQLite, therefore reading SQLite here would
        # incorrectly report an empty (and valid) chain.
        rows = self.forensic_events(secret_key)
        previous_hash = None
        for row in rows:
            watermark_id = row.get("watermark_id")
            event_type = row.get("event_type")
            canonical = json.dumps(row.get("payload"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            stored_hash = row.get("payload_hash")
            linked_hash = row.get("previous_hash")
            if linked_hash != previous_hash:
                return False
            signed = json.dumps([event_type, watermark_id, previous_hash, canonical], separators=(",", ":"), ensure_ascii=False)
            expected = hmac.new(secret_key.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(str(stored_hash), expected):
                return False
            previous_hash = stored_hash
        return True

    def ab_pattern_exists(self, content_id: str, fingerprint: str) -> bool:
        mirrored, exists = self._remote_call(lambda remote: remote.ab_pattern_exists(content_id, fingerprint))
        if mirrored:
            return bool(exists)
        with self._lock, closing(self._connect()) as connection:
            return connection.execute(
                "SELECT 1 FROM ab_sessions WHERE content_id = ? AND fingerprint = ?", (content_id, fingerprint)
            ).fetchone() is not None

    def put_ab_session(self, secret_key: str, session_id: str, client_id: str, content_id: str, watermark_id: str, cache_id: str, fingerprint: str) -> None:
        if not fingerprint or set(fingerprint) - {"A", "B"}:
            raise ValueError("fingerprint A/B inválido")
        fields = [session_id, client_id, content_id, watermark_id, cache_id, fingerprint]
        canonical = json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
        mac = hmac.new(secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        mirrored, _ = self._remote_call(
            lambda remote: remote.put_ab_session({
                "session_id": session_id, "client_id": client_id, "content_id": content_id,
                "watermark_id": watermark_id, "cache_id": cache_id, "fingerprint": fingerprint,
                "record_mac": mac, "created_at": time.time(),
            })
        )
        if mirrored:
            return
        with self._lock, closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO ab_sessions(session_id, client_id, content_id, watermark_id, cache_id, fingerprint, record_mac, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (*fields, mac, time.time()),
                )

    def ab_session(self, secret_key: str, session_id: str) -> dict | None:
        mirrored, remote_row = self._remote_call(lambda remote: remote.ab_session(session_id))
        if mirrored:
            if not remote_row:
                return None
            fields = [remote_row[key] for key in ("session_id", "client_id", "content_id", "watermark_id", "cache_id", "fingerprint")]
            canonical = json.dumps(fields, separators=(",", ":"), ensure_ascii=False)
            expected = hmac.new(secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(str(remote_row["record_mac"]), expected):
                raise ValueError("integridade da sessÃ£o A/B invÃ¡lida")
            return dict(zip(("session_id", "client_id", "content_id", "watermark_id", "cache_id", "fingerprint"), fields))
        with self._lock, closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT session_id, client_id, content_id, watermark_id, cache_id, fingerprint, record_mac FROM ab_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        canonical = json.dumps(list(row[:6]), separators=(",", ":"), ensure_ascii=False)
        expected = hmac.new(secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(str(row[6]), expected):
            raise ValueError("integridade da sessão A/B inválida")
        return dict(zip(("session_id", "client_id", "content_id", "watermark_id", "cache_id", "fingerprint"), row[:6]))

"""Small server-side Supabase Data API adapter with safe local fallback.

The application never exposes the secret key to the frontend.  Schema changes
remain in ``supabase/migrations`` and are deployed through the Supabase CLI or
SQL editor; the REST API is used only after those tables exist.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import requests


class SupabaseUnavailable(RuntimeError):
    pass


def load_project_env() -> None:
    """Load the repository .env without replacing deployment environment vars."""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class SupabaseStore:
    def __init__(self, url: str, secret_key: str, timeout_seconds: float = 8.0) -> None:
        self.url = url.rstrip("/")
        self._secret_key = secret_key
        self._timeout_seconds = timeout_seconds
        self._disabled_reason: str | None = None

    @classmethod
    def from_environment(cls) -> "SupabaseStore | None":
        load_project_env()
        url = os.getenv("SUPABASE_URL", "").strip()
        secret = os.getenv("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            return None
        return cls(url, secret)

    @property
    def available(self) -> bool:
        return self._disabled_reason is None

    @property
    def disabled_reason(self) -> str | None:
        return self._disabled_reason

    def _request(self, method: str, path: str, *, params: dict[str, str] | None = None, payload: Any = None, headers: dict[str, str] | None = None) -> Any:
        if self._disabled_reason:
            raise SupabaseUnavailable(self._disabled_reason)
        merged = {
            "apikey": self._secret_key,
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
        }
        if headers:
            merged.update(headers)
        try:
            response = requests.request(
                method,
                f"{self.url}/rest/v1/{path.lstrip('/')}",
                params=params,
                json=payload,
                headers=merged,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            if not response.content:
                return None
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            # Do not repeatedly stall simulation ticks when a development
            # credential is unavailable. The local repositories remain the
            # recoverable fallback until the process is restarted.
            self._disabled_reason = f"Supabase unavailable: {exc}"
            raise SupabaseUnavailable(self._disabled_reason) from exc

    def select(self, table: str, *, params: dict[str, str]) -> list[dict]:
        result = self._request("GET", table, params=params)
        return result if isinstance(result, list) else []

    def upsert(self, table: str, row: dict, *, on_conflict: str) -> None:
        self._request(
            "POST", table,
            params={"on_conflict": on_conflict},
            payload=row,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def insert(self, table: str, row: dict) -> Any:
        return self._request("POST", table, payload=row, headers={"Prefer": "return=representation"})

    def delete(self, table: str, *, params: dict[str, str]) -> None:
        self._request("DELETE", table, params=params, headers={"Prefer": "return=minimal"})


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (set, tuple, list)):
        return [jsonable(item) for item in value]
    return value


class SupabaseSimulationPersistence:
    """Persists controller state as a durable checkpoint without changing its API."""

    def __init__(self, store: SupabaseStore | None = None) -> None:
        self._store = store or SupabaseStore.from_environment()
        self._last_checkpoint_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._store and self._store.available)

    @property
    def disabled_reason(self) -> str | None:
        return self._store.disabled_reason if self._store else "Supabase is not configured"

    def checkpoint(self, state: Any, *, force: bool = False) -> None:
        if not self._store or not self._store.available or not getattr(state, "simulation_id", ""):
            return
        now = time.monotonic()
        if not force and now - self._last_checkpoint_at < 1.0:
            return
        try:
            self._store.upsert(
                "cdn_simulation_state",
                {
                    "state_key": "controller-current",
                    "simulation_id": state.simulation_id,
                    "payload": jsonable(state),
                },
                on_conflict="state_key",
            )
            self._last_checkpoint_at = now
        except SupabaseUnavailable:
            return

    def archive(self, record: dict) -> None:
        if not self._store or not self._store.available:
            return
        try:
            self._store.upsert(
                "cdn_simulation_history",
                {
                    "archive_id": record.get("archive_id"),
                    "simulation_id": record["simulation_id"],
                    "ended_at": record["ended_at"],
                    "payload": jsonable(record),
                },
                on_conflict="archive_id",
            )
        except SupabaseUnavailable:
            return

    def history(self, simulation_id: str | None = None) -> list[dict]:
        """Read archived runs from the durable store when it is available."""
        if not self._store or not self._store.available:
            return []
        params = {"select": "payload", "order": "ended_at.desc", "limit": "100"}
        if simulation_id:
            params["simulation_id"] = f"eq.{simulation_id}"
        try:
            rows = self._store.select("cdn_simulation_history", params=params)
        except SupabaseUnavailable:
            return []
        return [row["payload"] for row in rows if isinstance(row.get("payload"), dict)]


class SupabaseLedgerBackend:
    """REST-backed counterpart for the forensic SQLite registry tables."""

    def __init__(self, store: SupabaseStore) -> None:
        self._store = store

    @classmethod
    def from_environment(cls) -> "SupabaseLedgerBackend | None":
        store = SupabaseStore.from_environment()
        return cls(store) if store else None

    @property
    def available(self) -> bool:
        return self._store.available

    def put_marker(self, key_id: str, marker: str, token: str, created_at: float, algorithm_version: str) -> None:
        existing = self._store.select(
            "cdn_watermark_registry",
            params={"select": "token", "key_id": f"eq.{key_id}", "marker": f"eq.{marker}", "limit": "1"},
        )
        if existing and str(existing[0]["token"]) != token:
            raise ValueError("visual marker collision")
        self._store.upsert(
            "cdn_watermark_registry",
            {"key_id": key_id, "marker": marker, "token": token, "created_at": created_at, "algorithm_version": algorithm_version},
            on_conflict="key_id,marker",
        )

    def load_markers(self, key_id: str) -> dict[str, str]:
        rows = self._store.select(
            "cdn_watermark_registry",
            params={"select": "marker,token", "key_id": f"eq.{key_id}"},
        )
        return {str(row["marker"]): str(row["token"]) for row in rows}

    def put_claim(self, key_id: str, marker: str, token: str, claim: dict, claim_hash: str) -> None:
        watermark_id = str(claim["watermark_id"])
        existing = self._store.select(
            "cdn_forensic_claims",
            params={"select": "claim_hash", "watermark_id": f"eq.{watermark_id}", "limit": "1"},
        )
        if existing and str(existing[0]["claim_hash"]) != claim_hash:
            raise ValueError("watermark id collision")
        self.put_marker(key_id, marker, token, float(claim.get("issued_at", 0)), "CDNWM4-SECDED48")
        self._store.upsert(
            "cdn_forensic_claims",
            {
                "watermark_id": watermark_id, "key_id": key_id, "marker": marker,
                "claim_token": token, "claim_json": claim, "claim_hash": claim_hash,
                "created_at": float(claim.get("issued_at", 0)),
                "session_id": claim.get("session_id"), "content_id": claim.get("content_id"),
                "segment_range": claim.get("segment_range"), "algorithm_id": claim.get("algorithm_id"),
                "server_id": claim.get("server_id"),
            },
            on_conflict="watermark_id",
        )

    def claim_for_session(self, key_id: str, session_id: str, content_id: str, segment_range: str, algorithm_id: str, server_id: str) -> dict | None:
        rows = self._store.select(
            "cdn_forensic_claims",
            params={
                "select": "claim_token,claim_json,claim_hash", "key_id": f"eq.{key_id}",
                "session_id": f"eq.{session_id}", "content_id": f"eq.{content_id}",
                "segment_range": f"eq.{segment_range}", "algorithm_id": f"eq.{algorithm_id}",
                "server_id": f"eq.{server_id}", "limit": "1",
            },
        )
        if not rows:
            return None
        row = rows[0]
        return {"claim_token": str(row["claim_token"]), "claim": row["claim_json"], "claim_hash": str(row["claim_hash"])}

    def claim_for_marker(self, key_id: str, marker: str) -> dict | None:
        rows = self._store.select(
            "cdn_forensic_claims",
            params={"select": "watermark_id,claim_token,claim_json,claim_hash", "key_id": f"eq.{key_id}", "marker": f"eq.{marker}", "limit": "1"},
        )
        if not rows:
            return None
        row = rows[0]
        return {"watermark_id": str(row["watermark_id"]), "claim_token": str(row["claim_token"]), "claim": row["claim_json"], "claim_hash": str(row["claim_hash"])}

    def append_event(self, key_id: str, watermark_id: str | None, event_type: str, payload: dict, payload_hash: str, previous_hash: str | None, created_at: float) -> dict:
        rows = self._store.insert(
            "cdn_forensic_events",
            {"key_id": key_id, "watermark_id": watermark_id, "event_type": event_type,
             "payload_json": payload, "payload_hash": payload_hash, "previous_hash": previous_hash,
             "created_at": created_at},
        )
        return rows[0] if isinstance(rows, list) and rows else {}

    def events(self, key_id: str, watermark_id: str | None = None) -> list[dict]:
        params = {"select": "event_id,watermark_id,event_type,payload_json,payload_hash,previous_hash,created_at", "key_id": f"eq.{key_id}", "order": "event_id.asc"}
        if watermark_id:
            params["watermark_id"] = f"eq.{watermark_id}"
        return self._store.select("cdn_forensic_events", params=params)

    def ab_pattern_exists(self, content_id: str, fingerprint: str) -> bool:
        return bool(self._store.select("cdn_ab_sessions", params={"select": "session_id", "content_id": f"eq.{content_id}", "fingerprint": f"eq.{fingerprint}", "limit": "1"}))

    def put_ab_session(self, row: dict) -> None:
        self._store.insert("cdn_ab_sessions", row)

    def ab_session(self, session_id: str) -> dict | None:
        rows = self._store.select("cdn_ab_sessions", params={"select": "session_id,client_id,content_id,watermark_id,cache_id,fingerprint,record_mac", "session_id": f"eq.{session_id}", "limit": "1"})
        return rows[0] if rows else None

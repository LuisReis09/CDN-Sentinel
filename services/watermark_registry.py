from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from threading import RLock


class WatermarkRegistryCollision(ValueError):
    """Raised when two authenticated tokens claim the same visual marker."""


class WatermarkRegistry:
    """Durable marker-to-token index used by forensic attribution."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.getenv("CDN_WATERMARK_REGISTRY_PATH")
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

    def put(self, secret_key: str, marker: str, token: str, created_at: float) -> None:
        with self._lock, closing(self._connect()) as connection:
            with connection:
                key_id = self.key_id(secret_key)
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
        with self._lock, closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT marker, token FROM watermark_registry WHERE key_id = ?",
                (self.key_id(secret_key),),
            ).fetchall()
        return {str(marker): str(token) for marker, token in rows}


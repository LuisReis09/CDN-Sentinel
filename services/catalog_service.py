"""Small in-memory metadata workload used by the management simulator."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogItem:
    content_id: str
    title: str
    region: str
    popularity: int


class MetadataCatalog:
    """Compare deterministic linear and indexed metadata workloads.

    This small catalog is intentionally a simulation workload, not the
    controller's durable Supabase store. It makes the metadata optimization
    action observable without presenting a synthetic lookup as a database.
    """

    def __init__(self, size: int = 512) -> None:
        self.items = [CatalogItem(f"content-{index:04d}", f"Demo video {index:04d}", "global", (index * 17) % 101) for index in range(size)]
        self._index = {item.content_id: item for item in self.items}

    def lookup(self, content_id: str, tier: str = "linear") -> dict:
        started = time.perf_counter()
        if tier == "linear":
            result = next((item for item in self.items if item.content_id == content_id), None)
        elif tier in {"indexed", "read-replica"}:
            result = self._index.get(content_id)
        else:
            raise ValueError("tier de catálogo inválido")
        elapsed_ms = (time.perf_counter() - started) * 1000
        deterministic_floor = {"linear": 0.25, "indexed": 0.04, "read-replica": 0.06}[tier]
        return {"found": result is not None, "lookup_ms": round(max(deterministic_floor, elapsed_ms), 3), "tier": tier, "staleness_ms": 120 if tier == "read-replica" else 0}

    def workload(self, queries: int, tier: str = "linear") -> dict:
        queries = max(0, int(queries))
        results = [self.lookup(f"content-{(index * 31) % len(self.items):04d}", tier) for index in range(min(queries, 128))]
        average = sum(item["lookup_ms"] for item in results) / len(results) if results else 0.0
        return {"queries": queries, "lookup_ms": round(average, 3), "tier": tier, "staleness_ms": results[0]["staleness_ms"] if results else 0}


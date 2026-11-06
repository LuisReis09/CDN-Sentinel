"""Deterministic, bounded capacity model shared by controller and CDN nodes.

The workload size is virtual and labelled as such.  Local HTTP requests are
still measured separately, so a small demo payload cannot masquerade as a
production video transfer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import ceil
from typing import Any


@dataclass(frozen=True)
class CapacityProfile:
    tier: str
    cpu_units: int
    max_concurrent_requests: int
    processing_ms_per_request: float
    uplink_mbps: float
    cache_capacity_mb: int
    working_set_size_mb: int
    mean_chunk_bytes: int
    max_queue_depth: int
    cost_monthly_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CAPACITY_TIERS: dict[str, CapacityProfile] = {
    "basic": CapacityProfile(
        tier="basic",
        cpu_units=2,
        max_concurrent_requests=16,
        processing_ms_per_request=80.0,
        uplink_mbps=100.0,
        cache_capacity_mb=512,
        working_set_size_mb=2048,
        mean_chunk_bytes=262_144,
        max_queue_depth=32,
        cost_monthly_usd=100.0,
    ),
    "standard": CapacityProfile(
        tier="standard",
        cpu_units=4,
        max_concurrent_requests=32,
        processing_ms_per_request=55.0,
        uplink_mbps=250.0,
        cache_capacity_mb=2048,
        working_set_size_mb=4096,
        mean_chunk_bytes=262_144,
        max_queue_depth=64,
        cost_monthly_usd=180.0,
    ),
    "pro": CapacityProfile(
        tier="pro",
        cpu_units=8,
        max_concurrent_requests=64,
        processing_ms_per_request=35.0,
        uplink_mbps=500.0,
        cache_capacity_mb=8192,
        working_set_size_mb=8192,
        mean_chunk_bytes=262_144,
        max_queue_depth=128,
        cost_monthly_usd=320.0,
    ),
    "enterprise": CapacityProfile(
        tier="enterprise",
        cpu_units=16,
        max_concurrent_requests=128,
        processing_ms_per_request=24.0,
        uplink_mbps=1000.0,
        cache_capacity_mb=32768,
        working_set_size_mb=16384,
        mean_chunk_bytes=262_144,
        max_queue_depth=256,
        cost_monthly_usd=600.0,
    ),
}


def profile_for_tier(tier: str = "basic", overrides: dict[str, Any] | None = None) -> CapacityProfile:
    """Return a validated profile, optionally overriding workload parameters."""

    key = str(tier or "basic").lower()
    if key not in CAPACITY_TIERS:
        raise ValueError(f"tier desconhecido: {tier}")
    profile = CAPACITY_TIERS[key]
    if not overrides:
        return profile
    allowed = {
        field: value
        for field, value in overrides.items()
        if field in profile.__dataclass_fields__ and field != "tier"
    }
    result = replace(profile, **allowed)
    if result.max_concurrent_requests <= 0 or result.max_queue_depth < 0:
        raise ValueError("concorrência e fila devem ser não negativas, com concorrência positiva")
    if result.processing_ms_per_request <= 0 or result.uplink_mbps <= 0 or result.mean_chunk_bytes <= 0:
        raise ValueError("tempo de processamento, banda e chunk devem ser positivos")
    return result


def capacity_limits(profile: CapacityProfile, cache_hit_rate: float = 0.0) -> dict[str, float]:
    """Compute resource bottlenecks in requests per second.

    Cache hits use less CPU and network, but the input is explicit so callers
    can distinguish measured/virtual cache behaviour from an arbitrary bonus.
    """

    hit_rate = max(0.0, min(1.0, float(cache_hit_rate)))
    cpu_limit = profile.max_concurrent_requests * 1000.0 / profile.processing_ms_per_request
    network_bytes_per_second = profile.uplink_mbps * 1_000_000 / 8
    effective_bytes = profile.mean_chunk_bytes * max(0.05, 1.0 - hit_rate)
    network_limit = network_bytes_per_second / effective_bytes
    capacity = min(cpu_limit, network_limit)
    return {
        "cpu_limit_rps": round(cpu_limit, 3),
        "network_limit_rps": round(network_limit, 3),
        "capacity_rps": round(capacity, 3),
    }


def service_metrics(
    profile: CapacityProfile,
    arrival_rps: float,
    queue_depth: int = 0,
    queue_rejected: int = 0,
    cache_hit_rate: float = 0.0,
) -> dict[str, Any]:
    limits = capacity_limits(profile, cache_hit_rate)
    capacity_rps = limits["capacity_rps"]
    utilization = float(arrival_rps) / max(capacity_rps, 1e-9)
    return {
        **limits,
        "arrival_rps": round(max(0.0, float(arrival_rps)), 3),
        "utilization": round(utilization, 3),
        "pressure": round(utilization, 3),
        "queue_depth": max(0, int(queue_depth)),
        "queue_rejected": max(0, int(queue_rejected)),
        "cache_hit_rate": round(max(0.0, min(1.0, float(cache_hit_rate))), 3),
        "model": "estimado por gargalo CPU/rede; fila e erros são observados no nó",
    }


def queue_wait_ms(profile: CapacityProfile, in_flight: int, queue_position: int) -> float:
    """Bounded deterministic wait used by the local node admission queue."""

    waves = ceil(max(0, in_flight) / max(1, profile.max_concurrent_requests))
    return round(min(5_000.0, (waves + max(0, queue_position)) * profile.processing_ms_per_request), 3)

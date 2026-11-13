from __future__ import annotations

import os
import math
from dataclasses import dataclass, field

from services.content_provider import default_content_id


MAX_SERVERS = 500
MAX_CLIENTS = 100_000


@dataclass(frozen=True)
class SimulationConfig:
    num_servers: int
    num_clients: int
    malicious_probability: float
    latency_factor: float
    secret_key: str
    base_node_port: int = 5101
    video_id: str = field(default_factory=default_content_id)
    tick_interval_seconds: float = 1.25
    base_client_port: int = 6101
    monthly_client_price_usd: float = 25.0
    monthly_server_cost_usd: float = 100.0
    monthly_fixed_cost_usd: float = 150.0
    node_tier: str = "basic"
    demand_rps_per_client: float = 0.25
    slo_p95_ms: float = 250.0
    slo_success_rate_pct: float = 99.0
    seed: int = 2026

    @classmethod
    def from_payload(cls, payload: dict) -> "SimulationConfig":
        try:
            num_servers = int(payload.get("num_servers", 3))
            num_clients = int(payload.get("num_clients", 10))
            malicious_probability = float(payload.get("malicious_probability", 0.25))
            latency_factor = float(payload.get("latency_factor", 1.0))
            base_node_port = int(payload.get("base_node_port", 5101))
            raw_tick_interval = payload.get("tick_interval_seconds")
            if raw_tick_interval is None:
                legacy_speed = float(payload.get("simulation_speed", 1.0))
                tick_interval_seconds = 1.25 / legacy_speed
            else:
                tick_interval_seconds = float(raw_tick_interval)
            base_client_port = int(payload.get("base_client_port", 6101))
            monthly_client_price_usd = float(payload.get("monthly_client_price_usd", payload.get("monthly_client_price_unit", 25.0)))
            monthly_server_cost_usd = float(payload.get("monthly_server_cost_usd", payload.get("monthly_server_cost_unit", 100.0)))
            monthly_fixed_cost_usd = float(payload.get("monthly_fixed_cost_usd", payload.get("monthly_fixed_cost_unit", 150.0)))
            node_tier = str(payload.get("node_tier", "basic"))
            demand_rps_per_client = float(payload.get("demand_rps_per_client", 0.25))
            slo_p95_ms = float(payload.get("slo_p95_ms", 250.0))
            slo_success_rate_pct = float(payload.get("slo_success_rate_pct", 99.0))
            seed = int(payload.get("seed", 2026))
        except (TypeError, ValueError) as exc:
            raise ValueError("Parâmetros numéricos inválidos") from exc
        if not 1 <= num_servers <= MAX_SERVERS:
            raise ValueError(f"num_servers deve estar entre 1 e {MAX_SERVERS}")
        if not 1 <= num_clients <= MAX_CLIENTS:
            raise ValueError(f"num_clients deve estar entre 1 e {MAX_CLIENTS:,}".replace(",", "."))
        if not 0 <= malicious_probability <= 1:
            raise ValueError("malicious_probability deve estar entre 0 e 1")
        if not 0 <= latency_factor <= 20:
            raise ValueError("latency_factor deve estar entre 0 e 20")
        if not 1024 <= base_node_port <= 64000:
            raise ValueError("base_node_port deve estar entre 1024 e 64000")
        if base_node_port + num_servers - 1 > 64000:
            raise ValueError("o intervalo de portas dos nós excede 64000")
        if not 0.5 <= tick_interval_seconds <= 5:
            raise ValueError("tick_interval_seconds deve estar entre 0.5 e 5 segundos")
        if not 1024 <= base_client_port <= 64000:
            raise ValueError("base_client_port deve estar entre 1024 e 64000")
        # Clientes acima do limite de processos locais são virtuais e não
        # consomem uma porta dedicada. A porta base continua sendo validada
        # para preservar compatibilidade com execuções pequenas.
        if not all(math.isfinite(value) for value in (malicious_probability, latency_factor, tick_interval_seconds, monthly_client_price_usd, monthly_server_cost_usd, monthly_fixed_cost_usd, demand_rps_per_client, slo_p95_ms, slo_success_rate_pct)):
            raise ValueError("parâmetros numéricos devem ser finitos")
        if monthly_client_price_usd < 0 or monthly_server_cost_usd < 0 or monthly_fixed_cost_usd < 0:
            raise ValueError("custos e preço mensal em USD não podem ser negativos")
        if node_tier not in {"basic", "standard", "pro", "enterprise"}:
            raise ValueError("node_tier deve ser basic, standard, pro ou enterprise")
        if not 0 <= demand_rps_per_client <= 100:
            raise ValueError("demand_rps_per_client deve estar entre 0 e 100")
        if not 1 <= slo_p95_ms <= 60_000 or not 0 <= slo_success_rate_pct <= 100:
            raise ValueError("limiares de SLO inválidos")
        if not -(2**31) <= seed <= 2**31 - 1:
            raise ValueError("seed deve estar entre -2147483648 e 2147483647")
        return cls(
            num_servers=num_servers,
            num_clients=num_clients,
            malicious_probability=malicious_probability,
            latency_factor=latency_factor,
            secret_key=str(payload.get("secret_key") or os.getenv("CDN_SECRET_KEY", "local-development-secret")),
            base_node_port=base_node_port,
            video_id=str(payload.get("video_id") or default_content_id()),
            tick_interval_seconds=tick_interval_seconds,
            base_client_port=base_client_port,
            monthly_client_price_usd=monthly_client_price_usd,
            monthly_server_cost_usd=monthly_server_cost_usd,
            monthly_fixed_cost_usd=monthly_fixed_cost_usd,
            node_tier=node_tier,
            demand_rps_per_client=demand_rps_per_client,
            slo_p95_ms=slo_p95_ms,
            slo_success_rate_pct=slo_success_rate_pct,
            seed=seed,
        )

    def to_dict(self) -> dict:
        return {
            "num_servers": self.num_servers,
            "num_clients": self.num_clients,
            "malicious_probability": self.malicious_probability,
            "latency_factor": self.latency_factor,
            "base_node_port": self.base_node_port,
            "video_id": self.video_id,
            "tick_interval_seconds": self.tick_interval_seconds,
            "base_client_port": self.base_client_port,
            "monthly_client_price_usd": self.monthly_client_price_usd,
            "monthly_server_cost_usd": self.monthly_server_cost_usd,
            "monthly_fixed_cost_usd": self.monthly_fixed_cost_usd,
            "node_tier": self.node_tier,
            "demand_rps_per_client": self.demand_rps_per_client,
            "slo_p95_ms": self.slo_p95_ms,
            "slo_success_rate_pct": self.slo_success_rate_pct,
            "seed": self.seed,
        }

    @property
    def simulation_speed(self) -> float:
        """Legacy derived value kept for callers that still use the old name."""
        return 2.5 / self.tick_interval_seconds


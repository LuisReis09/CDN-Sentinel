from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ManagementNode:
    server_id: str
    tier: str = "basic"
    lifecycle_status: str = "running"
    health_status: str = "healthy"
    cache_level: int = 0
    cache_hit_rate: float = 0.0
    monthly_cost_usd: float = 100.0
    metadata_indexed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManagementAction:
    action_id: str
    action_type: str
    parameters: dict[str, Any]
    status: str
    submitted_day: int
    apply_day: int
    investment_usd: float
    recurring_delta_usd: float
    rationale: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    applied_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManagementState:
    simulation_id: str = ""
    scenario_id: str = "free"
    seed: int = 2026
    day: int = 0
    paused: bool = False
    version: int = 0
    updated_at: float | None = None
    initial_cash_balance_usd: float = 10_000.0
    cash_balance_usd: float = 10_000.0
    monthly_price_per_client_usd: float = 25.0
    fixed_monthly_cost_usd: float = 150.0
    base_paying_clients: int = 0
    paying_clients: int = 0
    client_population_target: float = 0.0
    arrivals_today: int = 0
    departures_today: int = 0
    arrivals_total: int = 0
    departures_total: int = 0
    active_clients: int = 0
    churned_clients: int = 0
    reputation: float = 75.0
    customer_satisfaction: float = 75.0
    demand_rps: float = 0.0
    served_rps: float = 0.0
    capacity_rps: float = 0.0
    utilization: float = 0.0
    backlog: int = 0
    requests_rejected: int = 0
    latency_p95_ms: float = 0.0
    availability_pct: float = 100.0
    error_rate_pct: float = 0.0
    sla_compliance_pct: float = 100.0
    daily_revenue_usd: float = 0.0
    daily_opex_usd: float = 0.0
    daily_profit_usd: float = 0.0
    monthly_margin_pct: float = 0.0
    cache_monthly_cost_usd: float = 0.0
    balancing_monthly_cost_usd: float = 0.0
    metadata_monthly_cost_usd: float = 0.0
    objective: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, ManagementNode] = field(default_factory=dict)
    pending_actions: list[ManagementAction] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    load_balancing_policy: str = "nearest-healthy"
    metadata_tier: str = "linear"
    metadata_query_rps: float = 0.0
    metadata_lookup_ms: float = 0.0
    metadata_staleness_ms: float = 0.0
    feedback_score: float = 0.0
    feedback_count: int = 0
    feedback_latency_avg_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = {key: value.to_dict() for key, value in self.nodes.items()}
        payload["pending_actions"] = [action.to_dict() for action in self.pending_actions]
        return payload


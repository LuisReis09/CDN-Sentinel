from __future__ import annotations

import copy
import math
import time
import uuid
from threading import RLock
from typing import Any

from management.actions import ActionRegistry
from management.domain import ManagementAction, ManagementNode, ManagementState
from management.scenarios import SCENARIOS, list_scenarios
from repositories.in_memory import SimulationRepository
from services.capacity_service import CAPACITY_TIERS
from services.catalog_service import MetadataCatalog


class ManagementEngine:
    """Canonical in-memory business simulation layered over real CDN telemetry."""

    def __init__(self, repository: SimulationRepository, simulation_controller) -> None:
        self._repository = repository
        self._simulation_controller = simulation_controller
        self._registry = ActionRegistry()
        self._catalog = MetadataCatalog()
        self._state = ManagementState()
        self._lock = RLock()

    @property
    def registry(self) -> ActionRegistry:
        return self._registry

    def reset(self, scenario_id: str = "free", seed: int | None = None) -> dict:
        with self._lock:
            if scenario_id not in SCENARIOS:
                raise ValueError(f"cenário inválido: {scenario_id}")
            world = self._repository.snapshot()
            scenario = SCENARIOS[scenario_id]
            config = world.config
            observed_paying = sum(1 for client in world.clients.values() if client.active and not client.malicious)
            initial = scenario.get("initial", {})
            paying = int(initial.get("clients", observed_paying or int(config.get("num_clients", 24) or 24)))
            initial_cash = float(initial.get("cash_usd", 10_000.0))
            initial_price = float(initial.get("monthly_price_usd", config.get("monthly_client_price_usd", 25.0)))
            initial_reputation = float(initial.get("reputation", 75.0))
            initial_satisfaction = float(initial.get("satisfaction", 75.0))
            self._state = ManagementState(
                simulation_id=world.simulation_id,
                scenario_id=scenario_id,
                seed=int(seed if seed is not None else config.get("seed", 2026)),
                initial_cash_balance_usd=initial_cash,
                cash_balance_usd=initial_cash,
                monthly_price_per_client_usd=initial_price,
                fixed_monthly_cost_usd=float(config.get("monthly_fixed_cost_usd", 150.0)),
                base_paying_clients=paying,
                paying_clients=paying,
                reputation=initial_reputation,
                customer_satisfaction=initial_satisfaction,
                active_clients=sum(1 for client in world.clients.values() if client.active and client.online),
                objective=copy.deepcopy(scenario["objective"]),
                nodes={
                    server.server_id: ManagementNode(
                        server_id=server.server_id,
                        tier=server.capacity_tier or str(config.get("node_tier", "basic")),
                        lifecycle_status=server.lifecycle_status,
                        health_status=server.health_status or server.status,
                        monthly_cost_usd=CAPACITY_TIERS.get(server.capacity_tier or "basic", CAPACITY_TIERS["basic"]).cost_monthly_usd,
                    )
                    for server in world.servers.values()
                },
            )
            self._append_event("management_reset", {"scenario_id": scenario_id, "seed": self._state.seed})
            self._compute_metrics()
            return self.snapshot()

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._state.to_dict())

    def action_definitions(self) -> list[dict]:
        return self._registry.definitions()

    def scenarios(self) -> list[dict]:
        return list_scenarios()

    def history(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._state.history)

    def apply_action(self, payload: dict) -> dict:
        with self._lock:
            action_type = str(payload.get("action_type", ""))
            definition = self._registry.get(action_type)
            if self._state.paused:
                raise RuntimeError("o simulador de gestão está pausado")
            expected_version = payload.get("expected_version")
            if expected_version is not None and int(expected_version) != self._state.version:
                raise RuntimeError("estado de gestão mudou; atualize antes de confirmar a ação")
            parameters = payload.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("parameters deve ser um objeto")
            self._validate_cooldown(action_type, definition.cooldown_days)
            investment, recurring, rationale = self._validate_action(action_type, parameters, definition)
            if self._state.cash_balance_usd < investment:
                raise ValueError(f"saldo insuficiente: necessário ${investment:.2f}, disponível ${self._state.cash_balance_usd:.2f}")
            self._state.cash_balance_usd -= investment
            action = ManagementAction(
                action_id=f"mgt-{uuid.uuid4().hex[:12]}",
                action_type=action_type,
                parameters=copy.deepcopy(parameters),
                status="pending",
                submitted_day=self._state.day,
                apply_day=self._state.day + definition.lead_days,
                investment_usd=investment,
                recurring_delta_usd=recurring,
                rationale=rationale,
            )
            self._state.pending_actions.append(action)
            self._state.version += 1
            self._append_event("management_action_submitted", {"action_id": action.action_id, "action_type": action_type, "apply_day": action.apply_day, "investment_usd": investment})
            return {"action": action.to_dict(), "state": self.snapshot()}

    def tick(self) -> dict:
        with self._lock:
            if not self._state.simulation_id or self._state.paused:
                return self.snapshot()
            self._state.day += 1
            self._apply_pending_actions()
            self._compute_metrics()
            return self.snapshot()

    def pause(self, paused: bool) -> dict:
        with self._lock:
            self._state.paused = paused
            self._state.version += 1
            self._append_event("management_paused" if paused else "management_resumed", {})
            return self.snapshot()

    def _validate_cooldown(self, action_type: str, cooldown_days: int) -> None:
        recent = [item for item in self._state.events if item.get("type") == "management_action_applied" and item.get("action_type") == action_type]
        if recent and self._state.day - int(recent[-1].get("day", 0)) < cooldown_days:
            remaining = cooldown_days - (self._state.day - int(recent[-1].get("day", 0)))
            raise ValueError(f"ação em cooldown; aguarde {remaining} dia(s) simulado(s)")

    def _validate_action(self, action_type: str, parameters: dict, definition) -> tuple[float, float, str]:
        if action_type == "horizontal_scale":
            operation = parameters.get("operation", "add")
            if operation not in {"add", "remove"}:
                raise ValueError("operation deve ser add ou remove")
            if operation == "add":
                if len(self._state.nodes) + sum(1 for item in self._state.pending_actions if item.action_type == action_type and item.parameters.get("operation") == "add") >= 20:
                    raise ValueError("limite de 20 nós atingido")
                for key in ("latitude", "longitude"):
                    if not isinstance(parameters.get(key), (int, float)):
                        raise ValueError(f"{key} é obrigatório para adicionar um nó")
                return definition.investment_usd, definition.recurring_monthly_usd, "adicionar um nó aumenta capacidade/cobertura após a implantação"
            server_id = str(parameters.get("server_id", ""))
            if server_id not in self._state.nodes:
                raise ValueError("server_id não encontrado")
            if sum(1 for node in self._state.nodes.values() if node.lifecycle_status not in {"stopped", "draining"}) <= 1:
                raise ValueError("não é permitido retirar o último nó operacional")
            return 0.0, -self._state.nodes[server_id].monthly_cost_usd, "retirar um nó reduz opex, mas pode degradar cobertura e SLA"
        if action_type == "vertical_scale":
            server_id = str(parameters.get("server_id", ""))
            tier = str(parameters.get("tier", ""))
            if server_id not in self._state.nodes or tier not in CAPACITY_TIERS:
                raise ValueError("server_id ou tier inválido")
            current = self._state.nodes[server_id].tier
            if list(CAPACITY_TIERS).index(tier) <= list(CAPACITY_TIERS).index(current):
                raise ValueError("o tier escolhido deve ser superior ao atual")
            delta = CAPACITY_TIERS[tier].cost_monthly_usd - CAPACITY_TIERS[current].cost_monthly_usd
            investment = definition.investment_by_tier.get(tier) or {"standard": 280.0, "pro": 560.0, "enterprise": 1120.0}.get(tier, definition.investment_usd)
            return investment, delta, "upgrade vertical altera o gargalo do nó após uma janela de manutenção"
        if action_type == "price_adjustment":
            price = float(parameters.get("monthly_price_usd", 0))
            if not 1 <= price <= 200:
                raise ValueError("monthly_price_usd deve estar entre 1 e 200")
            return definition.investment_usd, 0.0, "preço aplicado gradualmente; elasticidade afeta churn e demanda"
        if action_type == "cache_upgrade":
            server_id = str(parameters.get("server_id", ""))
            level = int(parameters.get("level", 0))
            if server_id not in self._state.nodes or not 1 <= level <= 3:
                raise ValueError("server_id ou level de cache inválido")
            if level <= self._state.nodes[server_id].cache_level:
                raise ValueError("o nível de cache deve ser superior ao atual")
            return definition.investment_usd * level, definition.recurring_monthly_usd * level, "cache aumenta hits e reduz cold miss, consumindo memória e banda"
        if action_type == "load_balancing":
            policy = str(parameters.get("policy", ""))
            if policy not in {"nearest-healthy", "least-utilized", "hybrid-latency-capacity"}:
                raise ValueError("política de balanceamento inválida")
            return definition.investment_usd, definition.recurring_monthly_usd, "política redistribui pressão sem criar capacidade agregada"
        if action_type == "metadata_upgrade":
            tier = str(parameters.get("tier", ""))
            if tier not in {"linear", "indexed", "read-replica"}:
                raise ValueError("tier de metadados inválido")
            if tier == self._state.metadata_tier:
                raise ValueError("tier de metadados já está aplicado")
            return definition.investment_usd, definition.recurring_monthly_usd, "melhora apenas consultas de catálogo; não finge um banco externo"
        raise ValueError("ação não suportada")

    def _apply_pending_actions(self) -> None:
        for action in self._state.pending_actions:
            if action.status != "pending" or action.apply_day > self._state.day:
                continue
            try:
                if action.action_type == "horizontal_scale":
                    if action.parameters.get("operation", "add") == "add":
                        result = self._simulation_controller.add_server({"latitude": action.parameters["latitude"], "longitude": action.parameters["longitude"], "city": action.parameters.get("city", "gestão"), "capacity_tier": "basic"})
                        server_id = result["server_id"]
                        self._state.nodes[server_id] = ManagementNode(server_id=server_id, tier="basic", lifecycle_status=result.get("lifecycle_status", "starting"), health_status=result.get("health_status", result.get("status", "starting")), monthly_cost_usd=CAPACITY_TIERS["basic"].cost_monthly_usd)
                        action.result = {"server_id": server_id, "operation": "add"}
                    else:
                        server_id = str(action.parameters["server_id"])
                        action.result = self._simulation_controller.retire_server(server_id)
                        self._state.nodes[server_id].lifecycle_status = "stopped"
                elif action.action_type == "vertical_scale":
                    server_id = str(action.parameters["server_id"])
                    tier = str(action.parameters["tier"])
                    action.result = self._simulation_controller.update_server_capacity(server_id, tier)
                    node = self._state.nodes[server_id]
                    node.tier = tier
                    node.monthly_cost_usd = CAPACITY_TIERS[tier].cost_monthly_usd
                    node.lifecycle_status = "running"
                elif action.action_type == "price_adjustment":
                    self._state.monthly_price_per_client_usd = float(action.parameters["monthly_price_usd"])
                    action.result = {"monthly_price_usd": self._state.monthly_price_per_client_usd}
                elif action.action_type == "cache_upgrade":
                    node = self._state.nodes[str(action.parameters["server_id"])]
                    node.cache_level = int(action.parameters["level"])
                    node.cache_hit_rate = min(0.8, 0.2 * node.cache_level)
                    action.result = {"server_id": node.server_id, "cache_hit_rate": node.cache_hit_rate}
                elif action.action_type == "load_balancing":
                    self._state.load_balancing_policy = str(action.parameters["policy"])
                    self._repository.update_config({"load_balancing_policy": self._state.load_balancing_policy})
                    action.result = {"policy": self._state.load_balancing_policy}
                elif action.action_type == "metadata_upgrade":
                    self._state.metadata_tier = str(action.parameters["tier"])
                    action.result = {"tier": self._state.metadata_tier}
                action.status = "applied"
                action.applied_at = time.time()
                self._state.version += 1
                action.result = {
                    **action.result,
                    "investment_usd": action.investment_usd,
                    "recurring_delta_usd": action.recurring_delta_usd,
                    "cash_effect": f"-${action.investment_usd:.2f} agora; {action.recurring_delta_usd:+.2f}/mês após aplicação",
                }
                self._append_event("management_action_applied", {"action_id": action.action_id, "action_type": action.action_type, "day": self._state.day, "investment_usd": action.investment_usd, "recurring_delta_usd": action.recurring_delta_usd, "result": action.result})
            except Exception as exc:
                action.status = "failed"
                action.error = str(exc)
                self._state.cash_balance_usd += action.investment_usd
                self._append_event("management_action_failed", {"action_id": action.action_id, "action_type": action.action_type, "day": self._state.day, "error": action.error})

    def _compute_metrics(self) -> None:
        world = self._repository.snapshot()
        sim_status = self._simulation_controller.status()
        scale = sim_status.get("scalability", {})
        scenario = SCENARIOS[self._state.scenario_id]
        growth = float(scenario.get("growth_per_day", 0.0))
        price_ratio = self._state.monthly_price_per_client_usd / max(1.0, float(world.config.get("monthly_client_price_usd", 25.0)))
        base_population = max(0, self._state.base_paying_clients)
        feedbacks = [
            feedback
            for client in world.clients.values()
            for feedback in getattr(client, "feedback_history", [])
            if isinstance(feedback, dict)
        ]
        self._state.feedback_count = len(feedbacks)
        self._state.feedback_score = round(
            sum(float(item.get("rating", 0)) for item in feedbacks) / max(1, len(feedbacks)) * 20,
            2,
        ) if feedbacks else 0.0
        self._state.feedback_latency_avg_ms = round(
            sum(float(item.get("latency_ms", 0)) for item in feedbacks) / max(1, len(feedbacks)),
            2,
        ) if feedbacks else 0.0
        price_effect = max(0.25, min(1.35, 1.0 - 0.12 * (price_ratio - 1.0)))
        quality_effect = max(0.35, min(1.35, 0.75 + (self._state.customer_satisfaction - 50.0) / 100.0))
        reputation_effect = max(0.65, min(1.2, 0.8 + self._state.reputation / 200.0))
        capacity_hint = float(scale.get("capacity_rps", scale.get("total_capacity", 0.0)))
        demand_hint = max(1.0, base_population * float(world.config.get("demand_rps_per_client", 0.25)))
        capacity_ratio = capacity_hint / demand_hint
        capacity_effect = max(0.35, min(1.1, 0.55 + capacity_ratio * 0.55))
        latency_hint = float(scale.get("p95_latency_ms", 0.0))
        latency_effect = max(0.35, min(1.1, 1.05 - max(0.0, latency_hint - 120.0) / 700.0))
        network_effect = max(0.3, min(1.15, capacity_effect * latency_effect))
        if scenario.get("outage_day") and self._state.day >= int(scenario["outage_day"]):
            network_effect *= 0.65
        natural_growth = 1.0 + 0.025 * self._state.day
        target = base_population * natural_growth * (1.0 + growth * self._state.day)
        target *= float(scenario.get("demand_multiplier", 1.0)) * price_effect * quality_effect * reputation_effect * network_effect
        if self._state.day == 0:
            target = float(base_population)
        previous_paying_clients = self._state.paying_clients
        self._state.client_population_target = round(target, 2)
        response_rate = max(0.2, min(0.95, float(scenario.get("population_response", 0.72))))
        next_paying_clients = max(0, round(previous_paying_clients + (target - previous_paying_clients) * response_rate))
        self._state.paying_clients = next_paying_clients
        self._state.arrivals_today = max(0, next_paying_clients - previous_paying_clients)
        self._state.departures_today = max(0, previous_paying_clients - next_paying_clients)
        self._state.arrivals_total += self._state.arrivals_today
        self._state.departures_total += self._state.departures_today
        if self._state.arrivals_today:
            self._append_event("clients_arrived", {"count": self._state.arrivals_today, "population": next_paying_clients, "reason": "rede_saudavel_preco_satisfacao_reputacao_cenario"})
        if self._state.departures_today:
            self._append_event("clients_departed", {"count": self._state.departures_today, "population": next_paying_clients, "reason": "churn_por_latencia_preco_qualidade_ou_capacidade"})
        self._state.active_clients = sum(1 for client in world.clients.values() if client.active and client.online and not client.malicious)
        self._state.churned_clients = self._state.departures_total
        self._state.demand_rps = round(max(0.0, self._state.paying_clients * float(world.config.get("demand_rps_per_client", 0.25)) * (1.0 + growth * self._state.day)), 3)
        cache_bonus = 1.0 + (sum(node.cache_hit_rate for node in self._state.nodes.values()) / max(1, len(self._state.nodes))) * 0.15
        outage_factor = 0.65 if scenario.get("outage_day") and self._state.day >= int(scenario["outage_day"]) else 1.0
        self._state.capacity_rps = round(float(scale.get("capacity_rps", scale.get("total_capacity", 0.0))) * cache_bonus * outage_factor, 3)
        self._state.utilization = round(self._state.demand_rps / max(self._state.capacity_rps, 0.001), 3)
        self._state.served_rps = round(min(self._state.demand_rps, self._state.capacity_rps), 3)
        self._state.backlog = int(scale.get("queue_depth", 0)) + max(0, round(self._state.demand_rps - self._state.capacity_rps))
        self._state.requests_rejected = int(scale.get("queue_rejected", 0)) + max(0, round(self._state.demand_rps - self._state.capacity_rps))
        observed_p95 = float(scale.get("p95_latency_ms", 0.0))
        self._state.latency_p95_ms = round(observed_p95 if observed_p95 else 80.0 + max(0.0, self._state.utilization - 0.75) * 400.0, 1)
        self._state.error_rate_pct = round(100 * self._state.requests_rejected / max(self._state.demand_rps * 60, 1), 2)
        self._state.availability_pct = round(max(0.0, min(100.0, 100.0 - self._state.error_rate_pct)), 2)
        slo_p95 = float(world.config.get("slo_p95_ms", 250.0))
        slo_success = float(world.config.get("slo_success_rate_pct", 99.0))
        compliant = self._state.latency_p95_ms <= slo_p95 and self._state.availability_pct >= slo_success
        self._state.sla_compliance_pct = round((sum(1 for item in self._state.history[-29:] if item.get("sla_compliant")) + int(compliant)) / max(1, min(30, len(self._state.history) + 1)) * 100, 2)
        quality = max(0.0, 100.0 - max(0.0, self._state.latency_p95_ms - 100.0) * 0.08 - self._state.error_rate_pct * 1.5 - max(0.0, price_ratio - 1.0) * 25.0)
        if self._state.feedback_count:
            quality = quality * 0.75 + self._state.feedback_score * 0.25
            quality -= max(0.0, self._state.feedback_latency_avg_ms - 180.0) * 0.04
        self._state.customer_satisfaction = round(self._state.customer_satisfaction * 0.8 + quality * 0.2, 2)
        self._state.reputation = round(self._state.reputation * 0.95 + self._state.customer_satisfaction * 0.05, 2)
        self._state.daily_revenue_usd = round(self._state.paying_clients * self._state.monthly_price_per_client_usd / 30.0, 2)
        node_opex = sum(node.monthly_cost_usd for node in self._state.nodes.values() if node.lifecycle_status != "stopped")
        self._state.cache_monthly_cost_usd = round(sum(node.cache_level * 15 for node in self._state.nodes.values()), 2)
        self._state.balancing_monthly_cost_usd = 18.0 if self._state.load_balancing_policy != "nearest-healthy" else 0.0
        self._state.metadata_monthly_cost_usd = {"linear": 0.0, "indexed": 30.0, "read-replica": 80.0}[self._state.metadata_tier]
        self._state.metadata_query_rps = 50.0 if scenario.get("catalog_pressure") else 8.0
        catalog_metrics = self._catalog.workload(round(self._state.metadata_query_rps), self._state.metadata_tier)
        self._state.metadata_lookup_ms = catalog_metrics["lookup_ms"]
        self._state.metadata_staleness_ms = catalog_metrics["staleness_ms"]
        self._state.daily_opex_usd = round((node_opex + self._state.fixed_monthly_cost_usd + self._state.cache_monthly_cost_usd + self._state.balancing_monthly_cost_usd + self._state.metadata_monthly_cost_usd) / 30.0, 2)
        self._state.daily_profit_usd = round(self._state.daily_revenue_usd - self._state.daily_opex_usd, 2)
        # Day zero is the initial snapshot, not a paid accounting period.  The
        # first daily profit is posted after the first simulated day so the UI
        # can show a truthful starting balance and an explicit cash flow.
        if self._state.day > 0:
            self._state.cash_balance_usd = round(self._state.cash_balance_usd + self._state.daily_profit_usd, 2)
        monthly_revenue = self._state.daily_revenue_usd * 30
        monthly_profit = self._state.daily_profit_usd * 30
        self._state.monthly_margin_pct = round(100 * monthly_profit / max(monthly_revenue, 0.01), 2)
        for server in world.servers.values():
            node = self._state.nodes.get(server.server_id)
            if node:
                node.lifecycle_status = server.lifecycle_status
                node.health_status = server.health_status or server.status
        record = {"day": self._state.day, "cash_balance_usd": self._state.cash_balance_usd, "daily_profit_usd": self._state.daily_profit_usd, "paying_clients": self._state.paying_clients, "demand_rps": self._state.demand_rps, "served_rps": self._state.served_rps, "capacity_rps": self._state.capacity_rps, "backlog": self._state.backlog, "latency_p95_ms": self._state.latency_p95_ms, "availability_pct": self._state.availability_pct, "sla_compliant": compliant, "customer_satisfaction": self._state.customer_satisfaction, "feedback_score": self._state.feedback_score, "feedback_count": self._state.feedback_count, "feedback_latency_avg_ms": self._state.feedback_latency_avg_ms, "monthly_margin_pct": self._state.monthly_margin_pct, "metadata_query_rps": self._state.metadata_query_rps, "metadata_lookup_ms": self._state.metadata_lookup_ms, "metadata_staleness_ms": self._state.metadata_staleness_ms, "provenance": "observado dos nós HTTP + simulado para demanda/economia + feedback de clientes"}
        if self._state.day == 0 or not self._state.history or self._state.history[-1].get("day") != self._state.day:
            self._state.history.append(record)
            self._state.history = self._state.history[-60:]
        self._state.alerts = []
        if self._state.utilization >= 0.75:
            self._state.alerts.append({"severity": "warning", "message": f"Pressão de capacidade em {round(self._state.utilization * 100)}%; compare escala vertical e horizontal."})
        if not compliant:
            slo_reasons = []
            if self._state.latency_p95_ms > slo_p95:
                slo_reasons.append(f"o p95 excedeu a meta de {slo_p95:g} ms")
            if self._state.availability_pct < slo_success:
                slo_reasons.append(f"a disponibilidade ficou abaixo da meta de {slo_success:g}%")
            self._state.alerts.append({
                "severity": "critical",
                "message": (
                    f"SLO violado: p95 {self._state.latency_p95_ms} ms "
                    f"(meta ≤ {slo_p95:g} ms) / disponibilidade {self._state.availability_pct}% "
                    f"(meta ≥ {slo_success:g}%). "
                    "O p95 representa os 5% de entregas mais lentas; "
                    f"motivo: {'; '.join(slo_reasons)}."
                ),
            })
        if outage_factor < 1:
            self._state.alerts.append({"severity": "critical", "message": "Evento de cenário: queda de nó reduziu a capacidade agregada; verifique failover no Network Lab."})
        self._state.updated_at = time.time() if hasattr(self._state, "updated_at") else None

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self._state.events.append({"event_id": f"mgt-evt-{uuid.uuid4().hex[:10]}", "type": event_type, "at": time.time(), "day": self._state.day, **payload})
        self._state.events = self._state.events[-200:]


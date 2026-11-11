from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionDefinition:
    action_type: str
    label: str
    group: str
    description: str
    investment_usd: float
    recurring_monthly_usd: float
    lead_days: int
    cooldown_days: int
    parameters: list[dict[str, Any]]
    effects: list[str]
    tradeoffs: list[str]
    investment_by_tier: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.action_type == "vertical_scale":
            payload["investment_usd"] = min(self.investment_by_tier.values(), default=self.investment_usd)
            payload["investment_by_tier"] = dict(self.investment_by_tier)
        return payload


ACTION_DEFINITIONS = (
    ActionDefinition(
        "horizontal_scale", "Escalonamento horizontal", "Infraestrutura", "Adicionar ou retirar um nó CDN em uma localização escolhida.", 650, 100, 2, 1, [{"name": "operation", "kind": "select", "options": ["add", "remove"]}, {"name": "latitude", "kind": "number"}, {"name": "longitude", "kind": "number"}], ["capacidade agregada", "cobertura geográfica"], ["implantação e mensalidade", "mais nós aumentam opex"]
    ),
    ActionDefinition(
        "vertical_scale", "Escalonamento vertical", "Infraestrutura", "Mudar o tier de um nó existente com manutenção visível.", 220, 80, 1, 1, [{"name": "server_id", "kind": "server"}, {"name": "tier", "kind": "select", "options": ["basic", "standard", "pro", "enterprise"]}], ["CPU, concorrência e banda do nó"], ["custo e manutenção temporária"], {"standard": 280.0, "pro": 560.0, "enterprise": 1120.0}
    ),
    ActionDefinition(
        "price_adjustment", "Ajustar preço dos clientes", "Comercial", "Alterar preço mensal com elasticidade e cooldown didáticos; cada experimento tem custo operacional.", 25, 0, 1, 5, [{"name": "monthly_price_usd", "kind": "number", "min": 1, "max": 200}], ["receita por pagante"], ["taxa do experimento, churn e demanda com atraso"]
    ),
    ActionDefinition(
        "cache_upgrade", "Melhorar cache e prefetch", "Otimização", "Aumentar cache por nó/região com hits observáveis no modelo.", 180, 45, 1, 2, [{"name": "server_id", "kind": "server"}, {"name": "level", "kind": "number", "min": 1, "max": 3}], ["hit rate e cold miss"], ["RAM, armazenamento e banda de prefetch"]
    ),
    ActionDefinition(
        "load_balancing", "Melhorar balanceamento de carga", "Otimização", "Escolher a política de seleção entre nearest, least-utilized e híbrida.", 80, 18, 1, 3, [{"name": "policy", "kind": "select", "options": ["nearest-healthy", "least-utilized", "hybrid-latency-capacity"]}], ["distribuição de pressão"], ["política distante pode elevar latência"]
    ),
    ActionDefinition(
        "metadata_upgrade", "Otimizar camada de metadados", "Otimização", "Trocar busca linear por índice em memória ou réplica simulada.", 140, 30, 1, 2, [{"name": "tier", "kind": "select", "options": ["linear", "indexed", "read-replica"]}], ["throughput de consultas de catálogo"], ["memória, custo de escrita e staleness"]
    ),
)


class ActionRegistry:
    def __init__(self) -> None:
        self._definitions = {item.action_type: item for item in ACTION_DEFINITIONS}

    @property
    def action_types(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def get(self, action_type: str) -> ActionDefinition:
        try:
            return self._definitions[action_type]
        except KeyError as exc:
            raise ValueError(f"action_type inválido; use um dos seis tipos registrados: {', '.join(self.action_types)}") from exc

    def definitions(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self._definitions.values()]


from __future__ import annotations

SCENARIOS = {
    "free": {
        "label": "Modo livre",
        "description": "Aprenda a equilibrar caixa, capacidade e qualidade sem um evento obrigatório.",
        "demand_multiplier": 1.0,
        "population_response": 0.72,
        "initial": {"cash_usd": 10_000.0, "clients": 16, "monthly_price_usd": 25.0, "reputation": 75.0, "satisfaction": 75.0},
        "objective": {"days": 30, "sla_pct": 99.0, "margin_pct": 15.0, "satisfaction": 75.0},
    },
    "rapid-growth": {
        "label": "Crescimento rápido",
        "description": "A demanda cresce gradualmente; escalar cedo protege o SLA, mas reduz a margem.",
        "demand_multiplier": 1.35,
        "growth_per_day": 0.035,
        "population_response": 0.88,
        "initial": {"cash_usd": 12_500.0, "clients": 22, "monthly_price_usd": 24.0, "reputation": 72.0, "satisfaction": 72.0},
        "objective": {"days": 30, "sla_pct": 99.0, "margin_pct": 15.0, "satisfaction": 75.0},
    },
    "regional-peak": {
        "label": "Pico regional de audiência",
        "description": "Um pico de vídeos populares pressiona uma região e torna cache/prefetch relevantes.",
        "demand_multiplier": 2.0,
        "population_response": 0.82,
        "cache_opportunity": True,
        "initial": {"cash_usd": 8_500.0, "clients": 20, "monthly_price_usd": 30.0, "reputation": 68.0, "satisfaction": 66.0},
        "objective": {"days": 15, "sla_pct": 98.0, "margin_pct": 5.0, "satisfaction": 70.0},
    },
    "catalog-spike": {
        "label": "Explosão de consultas ao catálogo",
        "description": "Consultas de metadados sobem; otimizar índices ajuda esse workload, não o streaming inteiro.",
        "demand_multiplier": 1.15,
        "population_response": 0.76,
        "catalog_pressure": True,
        "initial": {"cash_usd": 10_500.0, "clients": 18, "monthly_price_usd": 25.0, "reputation": 78.0, "satisfaction": 78.0},
        "objective": {"days": 20, "sla_pct": 97.0, "margin_pct": 5.0, "satisfaction": 70.0},
    },
    "node-outage": {
        "label": "Queda de nó",
        "description": "Uma falha de laboratório reduz capacidade; failover é operacional, não uma ação econômica.",
        "demand_multiplier": 1.1,
        "population_response": 0.84,
        "outage_day": 3,
        "initial": {"cash_usd": 9_000.0, "clients": 16, "monthly_price_usd": 27.0, "reputation": 70.0, "satisfaction": 70.0},
        "objective": {"days": 15, "sla_pct": 97.0, "margin_pct": 0.0, "satisfaction": 65.0},
    },
}


def list_scenarios() -> list[dict]:
    return [{"scenario_id": key, **value} for key, value in SCENARIOS.items()]


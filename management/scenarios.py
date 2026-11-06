from __future__ import annotations

SCENARIOS = {
    "free": {
        "label": "Modo livre",
        "description": "Aprenda a equilibrar caixa, capacidade e qualidade sem um evento obrigatório.",
        "demand_multiplier": 1.0,
        "objective": {"days": 30, "sla_pct": 99.0, "margin_pct": 15.0, "satisfaction": 75.0},
    },
    "rapid-growth": {
        "label": "Crescimento rápido",
        "description": "A demanda cresce gradualmente; escalar cedo protege o SLA, mas reduz a margem.",
        "demand_multiplier": 1.35,
        "growth_per_day": 0.018,
        "objective": {"days": 30, "sla_pct": 99.0, "margin_pct": 15.0, "satisfaction": 75.0},
    },
    "regional-peak": {
        "label": "Pico regional de audiência",
        "description": "Um pico de vídeos populares pressiona uma região e torna cache/prefetch relevantes.",
        "demand_multiplier": 2.0,
        "cache_opportunity": True,
        "objective": {"days": 15, "sla_pct": 98.0, "margin_pct": 5.0, "satisfaction": 70.0},
    },
    "catalog-spike": {
        "label": "Explosão de consultas ao catálogo",
        "description": "Consultas de metadados sobem; otimizar índices ajuda esse workload, não o streaming inteiro.",
        "demand_multiplier": 1.15,
        "catalog_pressure": True,
        "objective": {"days": 20, "sla_pct": 97.0, "margin_pct": 5.0, "satisfaction": 70.0},
    },
    "node-outage": {
        "label": "Queda de nó",
        "description": "Uma falha de laboratório reduz capacidade; failover é operacional, não uma ação econômica.",
        "demand_multiplier": 1.1,
        "outage_day": 3,
        "objective": {"days": 15, "sla_pct": 97.0, "margin_pct": 0.0, "satisfaction": 65.0},
    },
}


def list_scenarios() -> list[dict]:
    return [{"scenario_id": key, **value} for key, value in SCENARIOS.items()]

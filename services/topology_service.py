from __future__ import annotations

import random
from typing import Dict, Tuple

from config import SimulationConfig
from models.entities import Client, CDNServer
from utils.geo import city_with_jitter, load_global_cities


class TopologyService:
    """Build a terrestrial topology and expose nearest-node routing."""

    def __init__(self, seed: int = 2026) -> None:
        self._seed = seed

    def build(self, config: SimulationConfig) -> Tuple[Dict[str, CDNServer], Dict[str, Client]]:
        rng = random.Random(config.seed)
        cities = list(load_global_cities())
        rng.shuffle(cities)
        servers: Dict[str, CDNServer] = {}
        regional_count = min(8, max(1, config.num_servers // 12)) if config.num_servers > 1 else 0
        for index in range(config.num_servers):
            city = cities[index % len(cities)]
            server_id = f"cdn-{index + 1:02d}"
            if index == 0:
                role = "origin"
                region = "origin"
            elif index <= regional_count:
                role = "regional"
                region = f"region-{index:02d}"
            else:
                role = "edge"
                region = f"region-{((index - regional_count - 1) % max(1, regional_count)) + 1:02d}" if regional_count else "origin"
            servers[server_id] = CDNServer(
                server_id=server_id,
                host="127.0.0.1",
                port=config.base_node_port + index,
                latitude=city.latitude,
                longitude=city.longitude,
                city=city.name,
                capacity_tier=config.node_tier,
                role=role,
                region=region,
            )

        clients: Dict[str, Client] = {}
        for index in range(config.num_clients):
            city = cities[(index + config.num_servers) % len(cities)]
            latitude, longitude = city_with_jitter(rng, city)
            malicious = rng.random() < config.malicious_probability
            clients[f"client-{index + 1:04d}"] = Client(
                client_id=f"client-{index + 1:04d}",
                latitude=latitude,
                longitude=longitude,
                city=city.name,
                malicious=malicious,
                activity_rate_rps=round(max(0.03, config.demand_rps_per_client * rng.uniform(0.35, 1.8)), 4),
                session_probability=round(rng.uniform(0.55, 0.98), 3),
                watch_interval_ticks=round(rng.uniform(0.5, 3.5), 2),
                next_activity_tick=rng.randint(0, 2),
                timezone_offset_hours=int(round(city.longitude / 15.0)),
                content_affinity=round(rng.uniform(0.7, 1.35), 3),
                piracy_intent_probability=round(rng.uniform(0.35, 0.95), 3) if malicious else 0.0,
                piracy_attempt_probability=round(rng.uniform(0.25, 0.8), 3) if malicious else 0.0,
                piracy_publish_probability=round(rng.uniform(0.3, 0.9), 3) if malicious else 0.0,
                piracy_detection_probability=round(rng.uniform(0.8, 1.0), 3) if malicious else 0.0,
            )
        return servers, clients


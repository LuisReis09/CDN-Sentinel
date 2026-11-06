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
        for index in range(config.num_servers):
            city = cities[index % len(cities)]
            server_id = f"cdn-{index + 1:02d}"
            servers[server_id] = CDNServer(
                server_id=server_id,
                host="127.0.0.1",
                port=config.base_node_port + index,
                latitude=city.latitude,
                longitude=city.longitude,
                city=city.name,
            )

        clients: Dict[str, Client] = {}
        for index in range(config.num_clients):
            city = cities[(index + config.num_servers) % len(cities)]
            latitude, longitude = city_with_jitter(rng, city)
            clients[f"client-{index + 1:04d}"] = Client(
                client_id=f"client-{index + 1:04d}",
                latitude=latitude,
                longitude=longitude,
                city=city.name,
                malicious=rng.random() < config.malicious_probability,
            )
        return servers, clients


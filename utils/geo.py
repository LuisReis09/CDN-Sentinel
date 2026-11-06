from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class City:
    name: str
    latitude: float
    longitude: float


@lru_cache(maxsize=1)
def load_global_cities() -> tuple[City, ...]:
    """Load the terrestrial city catalog from data/cities.json."""
    catalog_path = Path(__file__).resolve().parents[1] / "data" / "cities.json"
    with catalog_path.open("r", encoding="utf-8") as catalog_file:
        records = json.load(catalog_file)
    return tuple(
        City(name=record["name"], latitude=float(record["latitude"]), longitude=float(record["longitude"]))
        for record in records
    )


def haversine_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Return great-circle distance between two points in kilometres."""
    radius_km = 6371.0088
    lat_a, lat_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    return radius_km * 2 * math.asin(math.sqrt(value))


def rank_servers(latitude: float, longitude: float, servers: Iterable[object]) -> list[tuple[float, object]]:
    """Rank healthy candidates deterministically by distance and server id."""
    candidates: List[tuple[float, object]] = []
    for server in servers:
        if getattr(server, "status", "healthy") not in {"healthy", "degraded", "overloaded", "starting"}:
            continue
        distance = haversine_km(latitude, longitude, server.latitude, server.longitude)
        candidates.append((distance, server))
    return sorted(candidates, key=lambda item: (item[0], getattr(item[1], "server_id", "")))


def choose_server(latitude: float, longitude: float, servers: Iterable[object]) -> tuple[object, float]:
    """Choose the closest healthy server and return it with the distance."""
    candidates = rank_servers(latitude, longitude, servers)
    if not candidates:
        raise RuntimeError("Nenhum servidor CDN saudável está disponível")
    distance, server = candidates[0]
    return server, distance


def city_with_jitter(rng: random.Random, city: City, degrees: float = 0.35) -> tuple[float, float]:
    """Generate a nearby terrestrial coordinate around a known city."""
    return city.latitude + rng.uniform(-degrees, degrees), city.longitude + rng.uniform(-degrees, degrees)


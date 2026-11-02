from __future__ import annotations

from functools import lru_cache

import requests

from utils.geo import haversine_km, load_global_cities


class CityLookupService:
    """Resolve map coordinates to a nearby city with an external API fallback."""

    def __init__(self, timeout: float = 2.5) -> None:
        self._timeout = timeout

    @lru_cache(maxsize=256)
    def lookup(self, latitude: float, longitude: float) -> str:
        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": latitude, "lon": longitude, "format": "jsonv2", "zoom": 10, "accept-language": "pt-BR"},
                headers={"User-Agent": "cdn-security-simulator/1.0"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            address = response.json().get("address", {})
            return str(address.get("city") or address.get("town") or address.get("village") or address.get("municipality") or address.get("county") or "Mapa personalizado")
        except (requests.RequestException, ValueError, TypeError):
            return self._nearest_catalog_city(latitude, longitude)

    @staticmethod
    def _nearest_catalog_city(latitude: float, longitude: float) -> str:
        city, _ = min(
            ((city, haversine_km(latitude, longitude, city.latitude, city.longitude)) for city in load_global_cities()),
            key=lambda item: item[1],
        )
        return city.name


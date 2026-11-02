from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SimulationConfig:
    num_servers: int
    num_clients: int
    malicious_probability: float
    latency_factor: float
    secret_key: str
    base_node_port: int = 5101
    video_id: str = "bigbuckbunny"

    @classmethod
    def from_payload(cls, payload: dict) -> "SimulationConfig":
        try:
            num_servers = int(payload.get("num_servers", 3))
            num_clients = int(payload.get("num_clients", 10))
            malicious_probability = float(payload.get("malicious_probability", 0.25))
            latency_factor = float(payload.get("latency_factor", 1.0))
            base_node_port = int(payload.get("base_node_port", 5101))
        except (TypeError, ValueError) as exc:
            raise ValueError("Parâmetros numéricos inválidos") from exc
        if not 1 <= num_servers <= 20:
            raise ValueError("num_servers deve estar entre 1 e 20")
        if not 1 <= num_clients <= 1000:
            raise ValueError("num_clients deve estar entre 1 e 1000")
        if not 0 <= malicious_probability <= 1:
            raise ValueError("malicious_probability deve estar entre 0 e 1")
        if not 0 <= latency_factor <= 20:
            raise ValueError("latency_factor deve estar entre 0 e 20")
        if not 1024 <= base_node_port <= 64000:
            raise ValueError("base_node_port deve estar entre 1024 e 64000")
        return cls(
            num_servers=num_servers,
            num_clients=num_clients,
            malicious_probability=malicious_probability,
            latency_factor=latency_factor,
            secret_key=str(payload.get("secret_key") or os.getenv("CDN_SECRET_KEY", "local-development-secret")),
            base_node_port=base_node_port,
            video_id=str(payload.get("video_id", "bigbuckbunny")),
        )

    def to_dict(self) -> dict:
        return {
            "num_servers": self.num_servers,
            "num_clients": self.num_clients,
            "malicious_probability": self.malicious_probability,
            "latency_factor": self.latency_factor,
            "base_node_port": self.base_node_port,
            "video_id": self.video_id,
        }


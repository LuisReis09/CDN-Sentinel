from __future__ import annotations

import argparse
import os
import threading
from typing import Any

import requests
from flask import Flask, jsonify, request

from repositories.in_memory import NodeRepository
from services.watermark_service import WatermarkService
from utils.geo import haversine_km
from utils.latency import sleep_for_distance
from utils.video import encode_payload, get_video_chunk


class CDNNode:
    """State and HTTP handlers for one independent CDN process."""

    def __init__(self, server_id: str, host: str, port: int, latitude: float, longitude: float, city: str, secret_key: str, latency_factor: float) -> None:
        self.server_id = server_id
        self.host = host
        self.port = port
        self.latitude = latitude
        self.longitude = longitude
        self.city = city
        self.latency_factor = latency_factor
        self.repository = NodeRepository()
        self.watermark_service = WatermarkService(secret_key)
        self.peers: list[dict] = []
        self._lock = threading.RLock()

    def configure_peers(self, peers: list[dict]) -> None:
        with self._lock:
            self.peers = [peer for peer in peers if peer["server_id"] != self.server_id]

    def configure(self, values: dict) -> dict:
        if "latency_factor" in values:
            self.latency_factor = float(values["latency_factor"])
        return {"server_id": self.server_id, "latency_factor": self.latency_factor}

    def status(self) -> dict:
        return {
            "server_id": self.server_id,
            "host": self.host,
            "port": self.port,
            "city": self.city,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "status": "healthy",
            "load": self.repository.load(),
            "blacklist_size": len(self.repository.blacklist()),
            "peers": [peer["server_id"] for peer in self.peers],
        }

    def stream(self, client_id: str, chunk_number: int) -> dict:
        if self.repository.is_blacklisted(client_id):
            raise PermissionError(f"Cliente {client_id} bloqueado no nó {self.server_id}")
        self.repository.increment_load()
        try:
            token, claim = self.watermark_service.issue(client_id, self.server_id, chunk_number)
            content, content_type = get_video_chunk(chunk_number)
            watermarked = token.encode("utf-8") + b"\n" + content
            result = {
                "chunk_id": claim.chunk_id,
                "content_type": content_type,
                "payload": encode_payload(watermarked),
                "watermark_token": token,
                "server_id": self.server_id,
                "issued_at": claim.issued_at,
            }
        finally:
            self.repository.decrement_load()
        result["load"] = self.repository.load()
        return result

    def accept_blacklist(self, entry: dict, visited: list[str] | None = None) -> dict:
        visited = list(dict.fromkeys((visited or []) + [self.server_id]))
        is_new = self.repository.add_blacklist(entry)
        propagated_to = [self.server_id]
        if not is_new:
            return {"accepted": True, "already_present": True, "propagated_to": propagated_to}
        for peer in list(self.peers):
            peer_id = peer["server_id"]
            if peer_id in visited:
                continue
            try:
                distance = haversine_km(self.latitude, self.longitude, peer["latitude"], peer["longitude"])
                sleep_for_distance(distance, self.latency_factor)
                response = requests.post(
                    f"{peer['url']}/internal/blacklist",
                    json={"entry": entry, "visited": visited},
                    timeout=8.0,
                )
                response.raise_for_status()
                propagated_to.extend(response.json().get("propagated_to", []))
            except requests.RequestException:
                continue
        return {"accepted": True, "already_present": False, "propagated_to": list(dict.fromkeys(propagated_to))}


def create_node_app(node: CDNNode) -> Flask:
    app = Flask(f"cdn-node-{node.server_id}")

    @app.get("/health")
    def health() -> Any:
        """Health check for the controller and orchestration layer."""
        return jsonify({"ok": True, **node.status()})

    @app.get("/internal/status")
    def internal_status() -> Any:
        """Return local node state, including load and blacklist size."""
        return jsonify(node.status())

    @app.post("/internal/peers")
    def internal_peers() -> Any:
        """Configure the peer list used by HTTP gossip."""
        body = request.get_json(silent=True) or {}
        peers = body.get("peers", [])
        if not isinstance(peers, list):
            return jsonify({"error": "peers deve ser uma lista"}), 400
        node.configure_peers(peers)
        return jsonify({"configured": [peer["server_id"] for peer in peers]})

    @app.post("/internal/config")
    def internal_config() -> Any:
        """Update node-local runtime configuration received over HTTP."""
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(node.configure(body))
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/internal/stream")
    def internal_stream() -> Any:
        """Issue a video chunk with an embedded forensic watermark."""
        client_id = request.args.get("client_id", "")
        try:
            chunk_number = int(request.args.get("chunk", "0"))
        except ValueError:
            return jsonify({"error": "chunk deve ser inteiro"}), 400
        if not client_id:
            return jsonify({"error": "client_id é obrigatório"}), 400
        try:
            return jsonify(node.stream(client_id, chunk_number))
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403

    @app.post("/internal/blacklist")
    def internal_blacklist() -> Any:
        """Accept a validated blacklist entry and propagate it over HTTP gossip."""
        body = request.get_json(silent=True) or {}
        entry = body.get("entry", body)
        if not isinstance(entry, dict) or not entry.get("client_id"):
            return jsonify({"error": "entry de blacklist inválida"}), 400
        return jsonify(node.accept_blacklist(entry, body.get("visited", [])))

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Processo independente de um nó CDN")
    parser.add_argument("--node", action="store_true")
    parser.add_argument("--server-id", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--city", required=True)
    parser.add_argument("--latency-factor", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    secret_key = os.getenv("CDN_NODE_SECRET", "local-development-secret")
    node = CDNNode(
        server_id=args.server_id,
        host=args.host,
        port=args.port,
        latitude=args.latitude,
        longitude=args.longitude,
        city=args.city,
        secret_key=secret_key,
        latency_factor=args.latency_factor,
    )
    create_node_app(node).run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()


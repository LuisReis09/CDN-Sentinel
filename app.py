from __future__ import annotations

import atexit
import os

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_restx import Api

from controllers.api_controller import ApiController
from controllers.simulation_controller import SimulationController
from repositories.in_memory import SimulationRepository
from routes.api import register_api_routes
from services.blacklist_service import BlacklistService
from services.cdn_http_client import CDNHttpClient
from services.leak_service import LeakService
from services.monitor_service import MonitorService
from services.stream_service import StreamService
from services.watermark_service import WatermarkService
from services.watermark_demo_service import WatermarkDemoService
from services.client_activity_service import ClientActivityService
from management.engine import ManagementEngine


def create_app() -> Flask:
    app = Flask(__name__)
    configured_origins = os.getenv("CDN_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    CORS(app, resources={r"/api/*": {"origins": [origin.strip() for origin in configured_origins if origin.strip()]}})
    control_token = os.getenv("CDN_CONTROL_TOKEN", "").strip()

    @app.before_request
    def protect_control_plane():
        """Protect control mutations when a local operator token is configured."""
        if not control_token or not request.path.startswith("/api/"):
            return None
        protected = request.path.startswith("/api/control") or request.method in {"POST", "PATCH", "PUT", "DELETE"}
        if not protected:
            return None
        if request.headers.get("X-CDN-Control-Token", "") != control_token:
            return jsonify({"error": "autenticação de controle necessária", "hint": "use X-CDN-Control-Token; deixe CDN_CONTROL_TOKEN vazio apenas no modo demo local"}), 401
        return None
    api = Api(
        app,
        version="1.0",
        title="CDN Security Simulator API",
        description="Simulação distribuída de CDN de vídeo com watermarking forense e monitoramento de pirataria.",
        doc="/docs",
    )
    repository = SimulationRepository()
    http_client = CDNHttpClient()
    simulation_controller = SimulationController(repository, http_client)
    watermark_service = WatermarkService(os.getenv("CDN_SECRET_KEY", "local-development-secret"))
    stream_service = StreamService(http_client, repository)
    client_activity_service = ClientActivityService(repository, stream_service)
    blacklist_service = BlacklistService(repository, http_client, watermark_service)
    monitor_service = MonitorService(repository, watermark_service, blacklist_service)
    leak_service = LeakService(repository, stream_service)
    watermark_demo_service = WatermarkDemoService(watermark_service)
    management_engine = ManagementEngine(repository, simulation_controller)
    client_activity_service.set_on_tick(management_engine.tick)
    controller = ApiController(repository, simulation_controller, stream_service, monitor_service, leak_service, watermark_service, watermark_demo_service, client_activity_service, management_engine)
    register_api_routes(api, controller)

    @app.get("/")
    def index():
        """Return a small service descriptor with the documentation URL."""
        return jsonify({"service": "cdn-security-simulator", "docs": "/docs", "health": "/health"})

    @app.get("/health")
    def health():
        """Return controller liveness and initialization state."""
        return jsonify({"ok": True, "initialized": repository.snapshot_without_clients().initialized})

    app.extensions["cdn_controller"] = controller
    app.extensions["cdn_control_auth"] = {"configured": bool(control_token), "cors_origins": configured_origins}
    atexit.register(leak_service.stop)
    atexit.register(client_activity_service.stop)
    atexit.register(monitor_service.stop)
    atexit.register(simulation_controller.shutdown_nodes)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), threaded=True, use_reloader=False)



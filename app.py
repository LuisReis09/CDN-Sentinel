from __future__ import annotations

import atexit
import hmac
import os
import re

from flask import Flask, g, jsonify, request
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
from services.forensic_investigation_service import ForensicInvestigationService
from services.viewer_session_service import ViewerSessionService
from services.operator_auth_service import OperatorAuthService, SESSION_SECONDS
from management.engine import ManagementEngine
from media.hls_ab import HLSABService


def create_app() -> Flask:
    app = Flask(__name__)
    auth_mode = os.getenv("CDN_AUTH_MODE", "local").strip().lower()
    if auth_mode not in {"local", "secure"}:
        raise ValueError("CDN_AUTH_MODE must be local or secure")
    bind_host = os.getenv("CDN_BIND_HOST", "127.0.0.1" if auth_mode == "local" else "0.0.0.0")
    if auth_mode == "local" and bind_host in {"0.0.0.0", "::"} and os.getenv("CDN_LOCAL_BIND_ACK", "") != "I_UNDERSTAND_LOCAL_MODE_HAS_NO_AUTH":
        raise ValueError("local mode cannot bind all interfaces without CDN_LOCAL_BIND_ACK")
    configured_origins = os.getenv("CDN_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if auth_mode == "secure" and any(origin.strip() == "*" for origin in configured_origins):
        raise ValueError("wildcard CORS is forbidden in secure mode")
    CORS(app, resources={r"/api/*": {"origins": [origin.strip() for origin in configured_origins if origin.strip()]}})
    control_token = os.getenv("CDN_CONTROL_TOKEN", "").strip()
    viewer_auth_required = auth_mode == "secure" or os.getenv("CDN_REQUIRE_VIEWER_AUTH", "0").strip().lower() in {"1", "true", "yes", "on"}
    if viewer_auth_required and not control_token and auth_mode != "secure":
        raise ValueError("CDN_CONTROL_TOKEN é obrigatório quando CDN_REQUIRE_VIEWER_AUTH=1")
    if auth_mode == "secure" and len(os.getenv("CDN_SECRET_KEY", "")) < 32:
        raise ValueError("CDN_SECRET_KEY must have at least 32 characters in secure mode")
    operator_auth = OperatorAuthService(os.getenv("CDN_OPERATOR_ACCOUNTS", "")) if auth_mode == "secure" else None
    viewer_sessions = ViewerSessionService(os.getenv("CDN_VIEWER_SESSION_SECRET", "")) if viewer_auth_required else None

    @app.post("/api/auth/login")
    def operator_login():
        if not operator_auth:
            return jsonify({"error": "secure mode is disabled"}), 404
        if not operator_auth.allow_login(request.remote_addr or "unknown"):
            return jsonify({"error": "too many login attempts"}), 429
        body = request.get_json(silent=True) or {}
        session = operator_auth.login(str(body.get("username", "")), str(body.get("password", "")), request.user_agent.string)
        if not session:
            return jsonify({"error": "invalid credentials"}), 401
        response = jsonify({"username": session["username"], "role": session["role"], "csrf": session["csrf"], "expires_at": session["expires_at"]})
        response.set_cookie("cdn_operator_session", session["session_id"], max_age=SESSION_SECONDS, secure=True, httponly=True, samesite="Strict", path="/api")
        return response

    @app.get("/api/auth/session")
    def operator_session():
        if not operator_auth:
            return jsonify({"error": "secure mode is disabled"}), 404
        identity = g.operator_identity
        return jsonify({"username": identity["username"], "role": identity["role"], "csrf": identity["csrf"], "expires_at": identity["expires_at"]})

    @app.post("/api/auth/logout")
    def operator_logout():
        if operator_auth:
            operator_auth.revoke(request.cookies.get("cdn_operator_session", ""))
        response = jsonify({"ok": True})
        response.delete_cookie("cdn_operator_session", path="/api")
        return response

    @app.before_request
    def protect_control_plane():
        """Enforce backend identity and roles before any sensitive API handler."""
        if not request.path.startswith("/api/") or request.method == "OPTIONS":
            return None
        if auth_mode == "secure":
            if request.path == "/api/auth/login":
                return None
            data_plane = (
                request.method == "GET" and bool(re.fullmatch(
                    r"/api/clients/[^/]+/(?:media|stream|hls/[^/]+/index\.m3u8|hls/[^/]+/[0-9]+\.ts)",
                    request.path,
                ))
            ) or (
                request.method == "POST" and bool(re.fullmatch(r"/api/clients/[^/]+/hls/sessions", request.path))
            )
            if data_plane:
                if request.method == "POST" and request.path.endswith("/hls/sessions") and not operator_auth.allow_processing("viewer:" + (request.remote_addr or "unknown")):
                    return jsonify({"error": "processing rate limit exceeded"}), 429
                return None  # ViewerSessionService verifies the bearer in each handler.
            identity = operator_auth.session(request.cookies.get("cdn_operator_session", ""), request.user_agent.string)
            if not identity:
                return jsonify({"error": "operator session required or expired"}), 401
            g.operator_identity = identity
            if request.method in {"POST", "PATCH", "PUT", "DELETE"} and not hmac.compare_digest(request.headers.get("X-CDN-CSRF", ""), identity["csrf"]):
                return jsonify({"error": "invalid CSRF token"}), 403
            path = request.path
            role = identity["role"]
            investigator_access = path.startswith("/api/security/watermark/verify") or path.startswith("/api/security/watermark/detect") or path == "/api/monitor/investigations" or path == "/api/monitor/leaks"
            reviewer_access = path.startswith("/api/monitor/investigations/") and path.endswith("/review")
            if role != "operator" and not ((role == "investigator" and investigator_access) or (role == "reviewer" and reviewer_access) or path.startswith("/api/auth/")):
                return jsonify({"error": "role is not authorized"}), 403
            expensive = (investigator_access or reviewer_access or path in {"/api/security/watermark/demo", "/api/monitor/scan"} or path.endswith("/viewer-sessions"))
            if expensive and request.method in {"POST", "PATCH", "PUT", "DELETE"} and not operator_auth.allow_processing(identity["username"]):
                return jsonify({"error": "processing rate limit exceeded"}), 429
            return None
        g.operator_identity = {"username": "local-operator", "role": "operator"}
        if not control_token:
            return None
        viewer_hls_post = (
            viewer_auth_required and request.method == "POST"
            and request.path.startswith("/api/clients/") and request.path.endswith("/hls/sessions")
        )
        protected = request.path.startswith("/api/control") or (request.method in {"POST", "PATCH", "PUT", "DELETE"} and not viewer_hls_post)
        if not protected:
            return None
        if not hmac.compare_digest(request.headers.get("X-CDN-Control-Token", ""), control_token):
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
    stream_service = StreamService(http_client, repository, watermark_service)
    client_activity_service = ClientActivityService(repository, stream_service)
    blacklist_service = BlacklistService(repository, http_client, watermark_service)
    monitor_service = MonitorService(repository, watermark_service, blacklist_service)
    forensic_investigation_service = ForensicInvestigationService(watermark_service)
    hls_ab_service = HLSABService(watermark_service)
    leak_service = LeakService(repository, stream_service)
    watermark_demo_service = WatermarkDemoService(watermark_service)
    management_engine = ManagementEngine(repository, simulation_controller)
    client_activity_service.set_on_tick(management_engine.tick)
    controller = ApiController(repository, simulation_controller, stream_service, monitor_service, leak_service, watermark_service, watermark_demo_service, client_activity_service, forensic_investigation_service, hls_ab_service, management_engine)
    controller.viewer_sessions = viewer_sessions
    controller.viewer_auth_required = viewer_auth_required
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
    app.extensions["cdn_control_auth"] = {"mode": auth_mode, "configured": bool(control_token), "viewer_auth_required": viewer_auth_required, "cors_origins": configured_origins}
    atexit.register(leak_service.stop)
    atexit.register(client_activity_service.stop)
    atexit.register(monitor_service.stop)
    atexit.register(simulation_controller.shutdown_nodes)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=os.getenv("CDN_BIND_HOST", "127.0.0.1" if os.getenv("CDN_AUTH_MODE", "local") == "local" else "0.0.0.0"), port=int(os.getenv("PORT", "5000")), threaded=True, use_reloader=False)



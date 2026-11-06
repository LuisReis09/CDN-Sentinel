from __future__ import annotations

from flask import request, send_file
from flask_restx import Namespace, Resource, fields

from controllers.api_controller import ApiController
from services.stream_service import ClientOfflineError, SimulationPausedError
from utils.video import get_video_asset


def register_api_routes(api, controller: ApiController) -> None:
    """Register routes grouped by control plane, data plane and observability domain."""
    control = api.namespace("control", path="/api/control", description="Simulation lifecycle and configuration")
    topology = api.namespace("topology", path="/api/topology", description="Global CDN topology")
    clients = api.namespace("clients", path="/api/clients", description="Client data plane")
    security = api.namespace("security", path="/api/security", description="Forensic security and governance")
    monitor = api.namespace("monitor", path="/api/monitor", description="Piracy monitor")
    observability = api.namespace("observability", path="/api/observability", description="Events and traffic telemetry")
    management = api.namespace("management", path="/api/management", description="Simulador didático de gestão da CDN")

    init_model = api.model(
        "SimulationInit",
        {
            "num_servers": fields.Integer(description="Quantidade de nós CDN (1-20)", default=3, min=1, max=20),
            "num_clients": fields.Integer(description="Quantidade de clientes (1-1000)", default=10, min=1, max=1000),
            "malicious_probability": fields.Float(description="Probabilidade de cliente malicioso (0-1)", default=0.25, min=0, max=1),
            "latency_factor": fields.Float(description="Multiplicador da latência geográfica", default=1.0, min=0, max=20),
            "base_node_port": fields.Integer(description="Primeira porta dedicada aos nós", default=5101, min=1024, max=64000),
            "secret_key": fields.String(description="Chave HMAC da CDN", required=False),
            "video_id": fields.String(description="Identificador do conteúdo", default="bigbuckbunny"),
            "tick_interval_seconds": fields.Float(description="Intervalo real entre ticks do sistema, em segundos", default=2.5, min=0.5, max=5),
            "base_client_port": fields.Integer(description="Base opcional para processos de cliente", default=6101, min=1024, max=64000),
            "monthly_client_price_usd": fields.Float(description="Preço didático por cliente/mês em USD", default=25.0, min=0),
            "monthly_server_cost_usd": fields.Float(description="Custo didático por servidor/mês em USD", default=100.0, min=0),
            "monthly_fixed_cost_usd": fields.Float(description="Custo fixo didático/mês em USD", default=150.0, min=0),
            "node_tier": fields.String(description="Perfil de capacidade inicial dos nós", default="basic", enum=["basic", "standard", "pro", "enterprise"]),
            "demand_rps_per_client": fields.Float(description="Demanda virtual estimada por cliente, em req/s", default=0.25, min=0, max=100),
            "slo_p95_ms": fields.Float(description="Limiar didático do p95 em milissegundos", default=250.0, min=1),
            "slo_success_rate_pct": fields.Float(description="Limiar didático de sucesso percentual", default=99.0, min=0, max=100),
            "seed": fields.Integer(description="Seed reprodutível da topologia", default=2026),
        },
    )
    update_model = api.model(
        "SimulationUpdate",
        {
            "num_servers": fields.Integer(description="Alteração estrutural: recria os nós", min=1, max=20),
            "num_clients": fields.Integer(description="Alteração estrutural: recria os clientes", min=1, max=1000),
            "malicious_probability": fields.Float(description="Nova probabilidade de clientes maliciosos", min=0, max=1),
            "latency_factor": fields.Float(description="Novo multiplicador de latência", min=0, max=20),
            "base_node_port": fields.Integer(description="Nova porta inicial", min=1024, max=64000),
            "base_client_port": fields.Integer(description="Nova base dos processos de cliente", min=1024, max=64000),
            "video_id": fields.String(description="Novo conteúdo simulado"),
            "tick_interval_seconds": fields.Float(description="Intervalo real entre ticks do sistema, em segundos", min=0.5, max=5),
            "monthly_client_price_usd": fields.Float(description="Preço didático por cliente/mês em USD", min=0),
            "monthly_server_cost_usd": fields.Float(description="Custo didático por servidor/mês em USD", min=0),
            "monthly_fixed_cost_usd": fields.Float(description="Custo fixo didático/mês em USD", min=0),
            "node_tier": fields.String(description="Perfil de capacidade dos nós", enum=["basic", "standard", "pro", "enterprise"]),
            "demand_rps_per_client": fields.Float(description="Demanda virtual por cliente, em req/s", min=0, max=100),
            "slo_p95_ms": fields.Float(description="Limiar didático do p95", min=1),
            "slo_success_rate_pct": fields.Float(description="Limiar didático de sucesso", min=0, max=100),
            "seed": fields.Integer(description="Seed reprodutível da topologia"),
        },
    )
    stream_model = api.model(
        "VideoChunk",
        {
            "chunk_id": fields.String,
            "content_type": fields.String,
            "payload": fields.String(description="Bytes do chunk em Base64, precedidos pela watermark"),
            "watermark_token": fields.String,
            "server_id": fields.String,
            "client_id": fields.String,
            "issued_at": fields.Float,
            "latency_ms": fields.Float,
            "request_id": fields.String,
            "trace_id": fields.String,
            "artificial_latency_ms": fields.Float,
            "http_rtt_ms": fields.Float,
            "queue_wait_ms": fields.Float,
            "end_to_end_ms": fields.Float,
            "routing_candidates": fields.Raw,
            "routing_reason": fields.String,
        },
    )
    verify_model = api.model("WatermarkVerify", {"token": fields.String(required=True)})
    demo_model = api.model(
        "WatermarkDemo",
        {
            "client_id": fields.String(description="Identidade didática, opcional"),
            "server_id": fields.String(description="Origem didática, opcional"),
            "chunk": fields.Integer(description="Número do chunk, opcional", default=0, min=0),
            "video_id": fields.String(description="Exemplo real específico, opcional"),
            "exclude_video_id": fields.String(description="Evita repetir o exemplo anterior"),
        },
    )
    client_create_model = api.model(
        "ClientCreate",
        {
            "client_id": fields.String(description="ID opcional do cliente"),
            "latitude": fields.Float(required=True, min=-90, max=90),
            "longitude": fields.Float(required=True, min=-180, max=180),
            "city": fields.String(description="Nome exibido no mapa"),
            "malicious": fields.Boolean(default=False),
        },
    )
    server_create_model = api.model(
        "ServerCreate",
        {
            "server_id": fields.String(description="ID opcional do nó"),
            "latitude": fields.Float(required=True, min=-90, max=90),
            "longitude": fields.Float(required=True, min=-180, max=180),
            "city": fields.String(description="Nome exibido no mapa"),
            "port": fields.Integer(description="Porta dedicada opcional", min=1024, max=64000),
        },
    )
    fault_model = api.model(
        "NodeFault",
        {
            "offline": fields.Boolean(description="Simula indisponibilidade do nó"),
            "extra_latency_ms": fields.Float(description="Atraso artificial adicional", min=0, max=30000),
            "drop_rate": fields.Float(description="Probabilidade de perda de mensagem", min=0, max=1),
        },
    )

    @control.route("/simulation/init")
    class SimulationInitResource(Resource):
        @control.doc(description="Inicializa a topologia, clientes e processos HTTP dos nós CDN.")
        @control.expect(init_model, validate=True)
        def post(self):
            """Initialize a complete distributed simulation."""
            try:
                return controller.initialize(request.get_json(silent=True) or {}), 201
            except ValueError as exc:
                return {"error": str(exc)}, 400
            except OSError as exc:
                return {"error": f"Falha ao iniciar nós CDN: {exc}"}, 503

    @control.route("/simulation/config")
    class SimulationConfigResource(Resource):
        @control.doc(description="Atualiza parâmetros sem reiniciar ou recria a topologia quando necessário.")
        @control.expect(update_model, validate=True)
        def patch(self):
            """Update mutable simulation attributes."""
            try:
                return controller.update_simulation(request.get_json(silent=True) or {})
            except (ValueError, RuntimeError) as exc:
                return {"error": str(exc)}, 400 if isinstance(exc, ValueError) else 409

    @control.route("/simulation/pause")
    class SimulationPauseResource(Resource):
        @control.doc(description="Pausa streaming e vazamentos automáticos, preservando o estado atual.")
        def post(self):
            """Pause the simulation lifecycle."""
            try:
                return controller.pause()
            except RuntimeError as exc:
                return {"error": str(exc)}, 409

    @control.route("/simulation/resume")
    class SimulationResumeResource(Resource):
        @control.doc(description="Retoma streaming e geração automática de vazamentos.")
        def post(self):
            """Resume the simulation lifecycle."""
            try:
                return controller.resume()
            except RuntimeError as exc:
                return {"error": str(exc)}, 409

    @control.route("/simulation/end")
    class SimulationEndResource(Resource):
        @control.doc(description="Encerra a simulação, para workers/processos e arquiva o histórico observável.")
        def post(self):
            try:
                return controller.end()
            except RuntimeError as exc:
                return {"error": str(exc)}, 409

    @control.route("/simulation/status")
    class SimulationStatusResource(Resource):
        @control.doc(description="Retorna o estado de execução e os contadores da simulação.")
        def get(self):
            """Return simulation lifecycle status."""
            return controller.status()

    @control.route("/metrics/reset")
    class MetricsResetResource(Resource):
        @control.doc(description="Limpa eventos, tráfego e histórico de scans, preservando topologia e blacklist.")
        def post(self):
            return controller.reset_metrics()

    @control.route("/fault/<string:server_id>")
    @control.param("server_id", "ID do nó CDN")
    class FaultResource(Resource):
        @control.doc(description="Injeta falhas somente nos processos locais da simulação.")
        @control.expect(fault_model, validate=True)
        def post(self, server_id: str):
            try:
                return controller.inject_fault(server_id, request.get_json(silent=True) or {})
            except KeyError as exc:
                return {"error": str(exc)}, 404
            except ValueError as exc:
                return {"error": str(exc)}, 400

    @topology.route("/servers")
    class CDNServersResource(Resource):
        @topology.doc(description="Lista estado, coordenadas, portas, carga e blacklist local dos nós CDN.")
        def get(self):
            """List the current CDN node topology."""
            return {"servers": controller.servers()}

        @topology.doc(description="Adiciona um nó CDN em uma coordenada escolhida no mapa e inicia seu processo HTTP.")
        @topology.expect(server_create_model, validate=True)
        def post(self):
            """Create a dedicated CDN node at a map coordinate."""
            try:
                return controller.create_server(request.get_json(silent=True) or {}), 201
            except ValueError as exc:
                return {"error": str(exc)}, 400
            except RuntimeError as exc:
                return {"error": str(exc)}, 409

    @clients.route("")
    class ClientsResource(Resource):
        @clients.doc(description="Lista clientes, localização e classificação de risco.")
        def get(self):
            """List generated clients."""
            return {"clients": controller.clients()}

        @clients.doc(description="Adiciona um cliente em uma coordenada escolhida no mapa.")
        @clients.expect(client_create_model, validate=True)
        def post(self):
            """Create a client at a map coordinate."""
            try:
                return controller.create_client(request.get_json(silent=True) or {}), 201
            except ValueError as exc:
                return {"error": str(exc)}, 400
            except RuntimeError as exc:
                return {"error": str(exc)}, 409

    @clients.route("/<string:client_id>/stream")
    @clients.param("client_id", "ID do cliente cadastrado")
    class ClientStreamResource(Resource):
        @clients.doc(description="Roteia o cliente para o nó mais próximo e entrega um chunk watermarkado.")
        @clients.response(200, "Watermarked video chunk", stream_model)
        @clients.param("chunk", "Número do chunk", _in="query", type="integer", default=0)
        def get(self, client_id: str):
            """Simulate a client request with geospatial latency and forensic watermark."""
            try:
                chunk_number = int(request.args.get("chunk", "0"))
                if chunk_number < 0:
                    raise ValueError("chunk deve ser maior ou igual a zero")
                return controller.stream(client_id, chunk_number, request.headers.get("X-Request-ID"))
            except SimulationPausedError as exc:
                return {"error": str(exc)}, 409
            except ClientOfflineError as exc:
                return {"error": str(exc)}, 409
            except PermissionError as exc:
                return {"error": str(exc)}, 403
            except (KeyError, ValueError) as exc:
                return {"error": str(exc)}, 404 if isinstance(exc, KeyError) else 400
            except RuntimeError as exc:
                return {"error": str(exc)}, 503
            except Exception as exc:
                return {"error": "Falha temporária ao solicitar stream"}, 502

    @security.route("/blacklist")
    class BlacklistResource(Resource):
        @security.doc(description="Retorna clientes banidos após propagação HTTP entre nós CDN.")
        def get(self):
            """Return the current distributed blacklist."""
            return {"blacklist": controller.blacklist()}

    @security.route("/watermark/verify")
    class WatermarkVerifyResource(Resource):
        @security.doc(description="Decodifica e valida uma watermark HMAC para uso no laboratório de segurança.")
        @security.expect(verify_model, validate=True)
        def post(self):
            """Verify and decode a forensic watermark token."""
            try:
                return {"valid": True, "claim": controller.verify_watermark((request.get_json() or {}).get("token", ""))}
            except (ValueError, TypeError, KeyError) as exc:
                return {"valid": False, "error": str(exc)}, 400

    @security.route("/watermark/demo")
    class WatermarkDemoResource(Resource):
        @security.doc(description="Executa um teste autônomo de watermark, extração e validação sem inicializar a simulação.")
        @security.expect(demo_model, validate=True)
        def post(self):
            """Generate and verify a standalone forensic watermark example."""
            try:
                return controller.watermark_demo(request.get_json(silent=True) or {})
            except (TypeError, ValueError) as exc:
                return {"error": str(exc)}, 400

    @security.route("/watermark/demo/video")
    class WatermarkDemoVideoResource(Resource):
        @security.doc(description="Entrega o vídeo real Big Buck Bunny usado pelo laboratório independente.")
        def get(self):
            """Stream a valid local MP4 with HTML5 range support."""
            try:
                video_id = request.args.get("video_id", "cdn_sentinel_demo")
                variant = request.args.get("variant", "original")
                if variant not in {"original", "watermarked", "difference"}:
                    return {"error": "variant deve ser original, watermarked ou difference"}, 400
                path, content_type = get_video_asset(video_id, variant)
                response = send_file(path, mimetype=content_type, conditional=True, etag=True, download_name=path.name)
                response.headers["X-CDN-Content-Source"] = "versioned-local-demo" if video_id.startswith("cdn_sentinel_demo") else "scikit-video-local-opt-in"
                response.headers["X-CDN-Visual-Transform"] = variant
                return response
            except (FileNotFoundError, ValueError) as exc:
                return {"error": str(exc), "hint": "use o MP4 local versionado ou habilite explicitamente um dataset instalado"}, 503

    @monitor.route("/scan")
    class MonitorScanResource(Resource):
        @monitor.doc(description="Varre plataformas externas simuladas, valida HMAC e denuncia vazamentos.")
        def post(self):
            """Scan simulated external platforms and process valid evidence."""
            try:
                return controller.scan(request.args.get("server_id"))
            except RuntimeError as exc:
                return {"error": str(exc)}, 503

    @monitor.route("/status")
    class MonitorStatusResource(Resource):
        @monitor.doc(description="Estado do monitor automático e da última varredura.")
        def get(self):
            return controller.monitor_status()

    @monitor.route("/leaks")
    class LeaksResource(Resource):
        @monitor.doc(description="Inspeciona vazamentos capturados na plataforma externa simulada.")
        def get(self):
            """List simulated leaks."""
            return {"leaks": controller.leaks()}

    @observability.route("/events")
    class EventsResource(Resource):
        @observability.doc(description="Retorna eventos de inicialização, requisição, monitor e gossip.")
        def get(self):
            """List recent simulation events."""
            return {"events": controller.events()}

    @observability.route("/traffic")
    class TrafficResource(Resource):
        @observability.doc(description="Retorna requisições de clientes, servidor escolhido, distância e latência.")
        def get(self):
            """List recent client traffic."""
            return {"traffic": controller.traffic()}

    @observability.route("/overview")
    class OverviewResource(Resource):
        @observability.doc(description="Retorna um snapshot agregado para o dashboard administrativo.")
        def get(self):
            """Return dashboard data in one request."""
            return controller.overview()

    @observability.route("/history")
    class SimulationHistoryResource(Resource):
        @observability.doc(description="Lista históricos completos de simulações encerradas em memória.")
        def get(self):
            return {"histories": controller.history(request.args.get("simulation_id"))}

    @management.route("/state")
    class ManagementStateResource(Resource):
        @management.doc(description="Retorna o estado canônico do simulador de gestão: negócio, demanda, custos e nós.")
        def get(self):
            try:
                return controller.management_state()
            except RuntimeError as exc:
                return {"error": str(exc)}, 409

    @management.route("/actions")
    class ManagementActionsResource(Resource):
        @management.doc(description="Lista exatamente as seis categorias de ações econômicas e aceita uma decisão validada pelo backend.")
        def get(self):
            return {"actions": controller.management_actions()}

        def post(self):
            try:
                return controller.management_apply_action(request.get_json(silent=True) or {}), 202
            except (ValueError, RuntimeError, KeyError) as exc:
                return {"error": str(exc)}, 409

    @management.route("/scenarios")
    class ManagementScenariosResource(Resource):
        def get(self):
            return {"scenarios": controller.management_scenarios()}

    @management.route("/scenarios/start")
    class ManagementScenarioStartResource(Resource):
        def post(self):
            try:
                return controller.management_start_scenario(request.get_json(silent=True) or {}), 201
            except (ValueError, RuntimeError, KeyError) as exc:
                return {"error": str(exc)}, 409

    @management.route("/history")
    class ManagementHistoryResource(Resource):
        def get(self):
            return {"history": controller.management_history()}

    @management.route("/reset")
    class ManagementResetResource(Resource):
        def post(self):
            try:
                return controller.management_reset()
            except (ValueError, RuntimeError) as exc:
                return {"error": str(exc)}, 409


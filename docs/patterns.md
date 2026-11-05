# Padrões arquiteturais aplicados

A Entrega 2 pede pelo menos três padrões. O projeto aplica os seguintes padrões, com evidência no código:

| Padrão | Como aparece | Evidência |
|---|---|---|
| API Gateway / Backend for Frontend | O navegador acessa uma API única que organiza namespaces de control, topology, clients, security, monitor e observability. | `app.py`, `routes/api.py`, `frontend/src/api.ts` |
| Arquitetura distribuída com microsserviços/edge nodes | O control plane e cada CDN edge node são processos separados; o controller só conversa com o nó via HTTP. | `controllers/simulation_controller.py`, `node_app.py`, `services/cdn_http_client.py` |
| Service Discovery + roteamento por proximidade | A topologia mantém os nós saudáveis; o cliente escolhe o nó mais próximo com Haversine. | `services/topology_service.py`, `utils/geo.py::choose_server` |
| Messaging Fanout / gossip | Um `BLACKLIST_ALERT` recebido por um nó é registrado e propagado aos pares ainda não visitados; telemetria também cruza regiões. | `node_app.py::CDNNode.accept_blacklist`, `services/client_activity_service.py` |
| Aggregator / API Composition | O endpoint `overview` compõe status, servidores, clientes, blacklist, leaks, eventos, tráfego e monitor para uma leitura do dashboard. | `controllers/api_controller.py::overview`, `frontend/src/hooks/useDashboardData.ts` |
| Containerized deployment | Backend e frontend são imagens independentes e o Compose espera o health check antes de liberar o console. | `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` |

## Áreas técnicas cobertas

- **Segurança:** API Gateway, prova HMAC, segregação da chave por variável de ambiente, auditoria de eventos e blacklist propagada.
- **Escalabilidade/desempenho:** múltiplos edge nodes, roteamento geográfico, medição de latência média/p95, capacidade por nó e fanout de mensagens.
- **Deployment:** imagens reproduzíveis, Docker Compose, health check, CI e proxy reverso Nginx.

# Stack tecnológico e justificativas

| Camada | Tecnologia | Justificativa para o projeto |
|---|---|---|
| API/control plane | Python 3.12, Flask 3.1, Flask-RESTX | Permite expor uma API REST pequena, documentada com Swagger, e manter a orquestração legível para a demonstração. |
| Comunicação entre processos | HTTP/1.1 + JSON + `requests` | Torna explícitos health checks, chamadas cliente–CDN e gossip CDN–CDN; também facilita inspeção durante a apresentação. |
| Frontend | React 18, TypeScript, Vite | Entrega um console tipado, rápido de desenvolver e com build reprodutível. |
| Visualização | React-Leaflet/Leaflet e Recharts | Mostra topologia geográfica, fluxos entre nós e métricas de latência/escalabilidade. |
| Segurança | HMAC-SHA256, `secrets`/variável `CDN_SECRET_KEY` | Autentica os claims da watermark e evita colocar a chave secreta no navegador. |
| Dados do protótipo | Repositório em memória, JSON de cidades | Reduz dependências para a Entrega 2 e deixa o fluxo distribuído observável; persistência é um trade-off explícito. |
| Empacotamento | Docker, Docker Compose, Nginx, Makefile | Caminho principal de execução reproduzível; `make docker-smoke` valida build/health/proxy e `make dev` inicia backend e frontend juntos sem containers. |
| Qualidade | `unittest`, `compileall`, TypeScript, GitHub Actions | Valida lógica, sintaxe, build e regressões básicas a cada push/PR. |

## Limites assumidos

Este stack é adequado ao protótipo hands-on e à demonstração local. Não pretende substituir, nesta entrega, um broker de mensagens, banco durável, service mesh, cofre de segredos ou orquestrador de produção. Esses limites e seus impactos estão registrados nos ADRs e no plano para a Entrega 3.

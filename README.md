# CDN-Sentinel

Protótipo acadêmico de uma control room para Engenharia de Sistemas Distribuídos e Segurança Computacional. A aplicação torna observáveis, em processos locais reais, roteamento por distância, failover, watermarking forense HMAC, monitoramento de vazamentos, blacklist idempotente, gossip HTTP, retry e métricas de requisição.

> Escopo da Entrega 2: execução local, armazenamento em memória, Big Buck Bunny real versionado para a demonstração e conteúdo fallback determinístico. Não há Supabase/PostgreSQL, dataset Hugging Face, broker, Kubernetes, serviço externo ou credencial paga.

## O que existe

- **Backend Flask/RESTX**: control plane, data plane, segurança, monitor e observabilidade em `/docs`.
- **Processos CDN independentes**: `node_app.py` inicia um processo HTTP por nó, com PID, porta, health, métricas e estado local.
- **Frontend React/TypeScript**: console em `frontend/`, com Command Center, Network Lab, Security Observatory e Watermark Studio.
- **Comunicação distribuída real**: controller↔nó e nó↔nó usam HTTP local assinado; o gossip possui `message_id`, deduplicação, hops, ACK e retry pendente.
- **Conteúdo desacoplado**: `ContentProvider`/`VideoCatalog` permitem trocar Big Buck Bunny ou o fallback por um catálogo futuro sem acoplar routing ou segurança.

As coordenadas das cidades e a latência de propagação são um modelo didático. Elas não representam presença geográfica real nem uma CDN de produção.

## Console e ciclo de vida

O console React cobre o fluxo completo: 'Command center' inicia e controla a simulação, o botão muda para 'Encerrar' enquanto ela está ativa e 'Simulation history' fica disponível depois do encerramento. O dashboard mostra séries temporais de blacklist, requisições acumuladas por servidor, latência média/p95 e saúde geral da CDN. O histórico arquivado preserva essas mesmas amostras e uma tabela final compacta dos processos.

O estado de cada CDN e observado como starting, healthy, degraded, offline ou stopped. Latencia/perda injetadas e erros consecutivos tornam o no degraded; falha de processo torna-o offline. O intervalo de tick e configuravel no slider de 0,5 a 5,0 segundos, e o preco por cliente/mes fica junto dos custos de infraestrutura no acordeao de precificacao.

Durante a propagacao de uma blacklist, o controller tenta os candidatos disponiveis em ordem deterministica. Um no que ja reconheceu o bloqueio responde 403 e o proximo no pode atender o cliente ate que todos os nos tenham recebido a evidencia. Quando todos rejeitam, a API retorna 403.

## Arquitetura

```text
React/TypeScript ── REST ──> Flask controller
                                  │
                     HTTP assinado│
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                CDN node 1    CDN node 2    CDN node N
                    │             │             │
                    └──── gossip HTTP + ACK/retry ────┘

LeakService → plataforma externa simulada → MonitorService → prova HMAC → blacklist
```

O repositório do controller e o repositório de cada nó são independentes e em memória. Snapshots públicos são cópias isoladas; eventos, tráfego, leaks e scans ficam limitados a 500 itens.

## Execução local

### Docker Compose (caminho principal)

Com Docker Desktop ou Docker Engine + Compose instalados:

```bash
docker compose up --build
```

Ou use o atalho equivalente:

```bash
make docker-up
```

O console fica em `http://127.0.0.1:8080`, o backend em `http://127.0.0.1:5000`, Swagger em `http://127.0.0.1:5000/docs` e o health check em `http://127.0.0.1:5000/health`. O frontend servido pelo Nginx encaminha `/api` para o serviço backend. Para validar automaticamente build, health, demo do watermark, proxy e encerramento, execute `make docker-smoke`.

Variáveis opcionais do Compose:

```bash
CDN_SECRET_KEY='chave-local-de-desenvolvimento' CDN_CONTROL_TOKEN='' docker compose up --build
```

O container inclui o clipe real local `data/media/bigbuckbunny.mp4` e o FFmpeg usado para gerar as variantes do Watermark Studio. O asset é atribuído à Blender Foundation sob CC-BY-3.0; nenhum download acontece no startup.

### Makefile / execução sem Docker

No Linux, `make dev` inicia backend e frontend juntos, usando `python3` e `npm`:

```bash
make install
make dev
```

O backend fica em `http://127.0.0.1:5000` e o Vite em `http://127.0.0.1:5173`. Outros comandos úteis são `make test`, `make build`, `make backend`, `make frontend` e `make docker-down`.

No Windows/PowerShell, a execução separada continua disponível:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:CDN_SECRET_KEY = "chave-local-de-desenvolvimento"
python app.py
```

Em outro terminal:

```powershell
Push-Location frontend
npm install
npm run dev
Pop-Location
```

O Vite usa `/api` por padrão. Para outro backend, use `VITE_API_BASE_URL`. Se o backend estiver com autenticação de controle, configure também `VITE_CONTROL_TOKEN`. Para habilitar exemplos adicionais já instalados pelo `scikit-video`, sem download automático, configure `USE_BIGBUCKBUNNY_DATASET=1`.

## Segurança e modo de demonstração

- Endpoints de controle/mutação aceitam `X-CDN-Control-Token` quando `CDN_CONTROL_TOKEN` está configurado. Com a variável vazia, o comportamento é explicitamente **demo local**; CORS continua limitado a `CDN_CORS_ORIGINS` (por padrão, localhost nas portas 5173).
- Mensagens internas usam HMAC sobre método, path e hash do corpo, com timestamp, nonce e TTL de 30 segundos. Nonces já usados são rejeitados.
- Uma blacklist só é aceita por um nó quando o token HMAC da prova corresponde a `client_id`, servidor emissor e assinatura. Mensagens sem credencial/prova são rejeitadas.
- HMAC protege integridade/autenticidade do claim; não cifra o vídeo, e o token de watermark, isoladamente, pode ser reapresentado. O estúdio também aplica um sinal visual real de 64 bits derivado do HMAC nos frames do Big Buck Bunny e mede sua recuperação no primeiro frame após blur, ruído determinístico e quantização. Isso é uma demonstração didática, não uma garantia de robustez de produção. O anti-replay implementado é do protocolo interno, com nonce/TTL/estado local.

## Fluxo rápido da API

Inicializar uma rede pequena:

```powershell
$body = @{ num_servers = 3; num_clients = 4; malicious_probability = 0.35; latency_factor = 1.0; tick_interval_seconds = 2.5; seed = 2026 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/control/simulation/init -ContentType "application/json" -Body $body
```

Endpoints principais:

| Domínio | Endpoint | Finalidade |
|---|---|---|
| Controle | `POST /api/control/simulation/init` | cria topologia e processos |
| Controle | `PATCH /api/control/simulation/config` | altera configuração; mudanças estruturais recriam a simulação |
| Controle | `POST /api/control/simulation/pause` / `resume` | pausa/retoma workers |
| Controle | `POST /api/control/fault/{server_id}` | offline, latência extra ou perda local |
| Controle | `POST /api/control/metrics/reset` | zera telemetria sem apagar topologia/blacklist |
| Controle | `POST /api/control/simulation/end` | encerra processos/workers e arquiva a simulacao |
| Dados | `GET /api/clients/{id}/stream?chunk=0` | roteia, faz failover e entrega chunk watermarkado |
| Topologia | `GET/POST /api/topology/servers` | observa/adiciona nós |
| Segurança | `POST /api/security/watermark/verify` | valida token HMAC sem expor chave |
| Monitor | `POST /api/monitor/scan` | dispara varredura manual |
| Observabilidade | `GET /api/observability/overview` | snapshot agregado para o console |
| Observabilidade | `GET /api/observability/history` | lista historicos completos arquivados |

Uma resposta de stream distingue `artificial_latency_ms`, `http_rtt_ms` e `end_to_end_ms`, além de `request_id`, `trace_id`, candidatos e razão de routing.

## Experimentos didáticos

1. Faça um stream e abra a decisão de routing no Command Center/Network Lab.
2. Desligue o nó selecionado no Network Lab; a próxima chamada deve escolher o próximo candidato saudável e registrar a razão.
3. Injete latência ou perda; observe requests, erros, in-flight, retry e eventos.
4. No Security Observatory, acompanhe cliente → chunk → plataforma simulada → monitor → prova → blacklist → gossip/ACK.
5. No Watermark Studio, reproduza o Big Buck Bunny original, o MP4 com sinal HMAC real e a diferença amplificada; confira a recuperação de 64/64 bits nos filtros e depois altere um caractere do token. A prova adulterada deve ser rejeitada.

O roteiro completo está em [`docs/demo-script.md`](./docs/demo-script.md).

## Testes e verificações

```powershell
python -m compileall app.py config.py client_app.py node_app.py controllers models repositories routes services utils tests
python -m unittest discover -s tests -v
Push-Location frontend
npm.cmd run build
Pop-Location
```

O smoke E2E local inicia processos CDN e verifica inicialização, stream e overview. `make docker-config` valida o Compose; `make docker-smoke` sobe as imagens, aguarda `/health`, verifica o frontend via Nginx e encerra os containers ao final.

## Decisões e limitações

- A persistência é em memória; interfaces permitem um adaptador futuro para Supabase/PostgreSQL, que não faz parte desta etapa.
- O Big Buck Bunny é um asset local de demonstração, atribuído à Blender Foundation sob CC-BY-3.0; o download é mantido fora do runtime. Uma futura integração com `kishan51/youtube_clipped_videos` precisa tratar licença, cache, armazenamento e reprodução antes de ser implementada.
- Clientes são poucos processos locais e carga virtual limitada; não são milhares de processos ociosos.
- Custos mensais, capacidade por nó e latência de fila são cenários didáticos estimados, nunca fatos de produção.
- O monitor é separado por escopo de nó, mas continua coordenado pelo controller no mesmo aplicativo Flask.
- O watermark visual é um canal experimental derivado do HMAC e aplicado com FFmpeg sobre frames reais; o prefixo nos bytes continua sendo a prova de transporte. A série `metrics_history` é limitada a 500 amostras e fica em memória junto com o restante da simulação.

Checklist, C4, ADR, padrões, plano de testes e pendência de equipe:

- [`docs/delivery-2-checklist.md`](./docs/delivery-2-checklist.md)
- [`docs/c4.md`](./docs/c4.md)
- [`docs/adrs/0001-protocolo-interno-e-failover.md`](./docs/adrs/0001-protocolo-interno-e-failover.md)
- [`docs/patterns.md`](./docs/patterns.md)
- [`docs/test-plan.md`](./docs/test-plan.md)
- [`docs/responsibilities.md`](./docs/responsibilities.md)

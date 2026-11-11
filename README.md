# CDN-Sentinel

## Dataset de clipes do YouTube

O backend e o Watermark Studio usam automaticamente os vídeos locais do
dataset [`kishan51/youtube_clipped_videos`](https://huggingface.co/datasets/kishan51/youtube_clipped_videos)
quando ele estiver disponível. O snapshot fica em
`data/datasets/youtube_clipped_videos/`, que está no `.gitignore`.

Depois de instalar as dependências, execute o downloader na raiz do projeto:

```powershell
python tools/download_youtube_clipped_videos.py
```

O download pode ser repetido para continuar uma transferência interrompida.
Por padrão, o backend descobre os arquivos de vídeo recursivamente nesse
diretório e usa o dataset automaticamente. O seletor
`video_id = "youtube_clipped_videos"` continua disponível para deixar essa
escolha explícita; para o Watermark Studio, os clipes baixados também são
escolhidos automaticamente. Sem o dataset, o Big Buck Bunny local continua
sendo o fallback.

Se o backend estiver em Docker, o Compose monta esse diretório como somente
leitura. Para usar outro local, defina `CDN_DATASET_DIR` antes de subir os
serviços.

Protótipo acadêmico de uma control room para Engenharia de Sistemas Distribuídos e Segurança Computacional. A aplicação torna observáveis, em processos locais reais, roteamento por distância, failover, watermarking forense AES-GCM/HMAC, monitoramento de vazamentos, blacklist idempotente, gossip hierárquico cifrado, retry e métricas de requisição.

> Escopo da Entrega 2: execução local, armazenamento em memória, Big Buck Bunny real versionado para a demonstração e conteúdo fallback determinístico. O dataset Hugging Face é opcional e baixado explicitamente; não há Supabase/PostgreSQL, broker, Kubernetes, serviço externo ou credencial paga obrigatória.

## O que existe

- **Backend Flask/RESTX**: control plane, data plane, segurança, monitor e observabilidade em `/docs`.
- **Processos CDN independentes**: `node_app.py` inicia um processo HTTP por nó, com PID, porta, health, métricas e estado local.
- **Frontend React/TypeScript**: console em `frontend/`, com Command Center, Network Lab, Security Observatory e Watermark Studio.
- **Modos operacionais**: o seletor do topo alterna entre **Orquestração**, que mantém o dashboard da main, e **Gamificação**, que usa o simulador de gestão da branch `feat/cdn-management-simulator`.
- **Comunicação distribuída real**: controller↔nó e nó↔nó usam HTTP local assinado; o gossip possui `message_id`, deduplicação, hops, ACK e retry pendente.
- **Conteúdo desacoplado**: `ContentProvider`/`VideoCatalog` permitem trocar Big Buck Bunny ou o fallback por um catálogo futuro sem acoplar routing ou segurança.

As coordenadas das cidades e a latência de propagação são um modelo didático. Elas não representam presença geográfica real nem uma CDN de produção.

O fator de latência não é mais editável no frontend: o atraso de propagação é calculado pela distância até o servidor escolhido. Mantido o mesmo caminho e sem saturação do limite didático, 2N km produz aproximadamente o dobro do atraso de N km; fila, RTT HTTP e falhas continuam sendo métricas separadas.

### Modo de gamificação

O modo de gamificação começa com caixa, preço, clientes pagantes, nós e custos visíveis no painel **Como o modo começa**. Cada tick representa um dia: a população do jogo pode receber clientes ou perder clientes por preço, satisfação, reputação, capacidade e cenário. Ações de escala horizontal/vertical, cache, balanceamento, metadados e preço debitam investimento quando aplicável e alteram custos recorrentes, receita ou margem; ações pendentes respeitam lead time e cooldown.

## Console e ciclo de vida

O console React cobre o fluxo completo: 'Command center' inicia e controla a simulação, o botão muda para 'Encerrar' enquanto ela está ativa e 'Simulation history' fica disponível depois do encerramento. O dashboard mostra séries temporais de blacklist, requisições acumuladas por servidor, latência média/p95 e saúde geral da CDN. O histórico arquivado preserva essas mesmas amostras e uma tabela final compacta dos processos.

O estado de cada CDN e observado como starting, healthy, degraded, overloaded, offline ou stopped. Pressao de capacidade a partir de 90% aparece como alerta/sobrecarregado; latencia/perda injetadas e erros consecutivos tornam o no degraded; falha de processo torna-o offline. O intervalo de tick e configuravel no slider de 0,5 a 5,0 segundos, e o preco por cliente/mes fica junto dos custos de infraestrutura no acordeao de precificacao.

Durante a propagacao de uma blacklist, o controller tenta os candidatos disponiveis em ordem deterministica. Um no que ja reconheceu o bloqueio responde 403 e o proximo no pode atender o cliente ate que todos os nos tenham recebido a evidencia. Quando todos rejeitam, a API retorna 403.

### Escala e leitura do mapa

A configuracao aceita ate 500 servidores e 100.000 clientes. Para nao transformar a demonstracao em uma colecao de processos ociosos, a execucao mantem limites configuraveis de processos reais (`CDN_REAL_NODE_LIMIT`, padrao 64; `CDN_REAL_CLIENT_LIMIT`, padrao 32) e representa nos/clientes adicionais como capacidade e trafego virtuais agregados. O overview e o historico visual retornam uma amostra limitada de clientes, preservando os totais e as metricas completas do control plane.

O mapa usa uma arvore geradora minima entre os servidores como backbone visual, mais as arestas de mensagens ativas, failover, capacidade e blacklist. Isso reduz o desenho de O(n²) para O(n) no backbone sem esconder os eventos importantes; o trafego cliente-servidor tambem e amostrado e agregado em escalas grandes.

Os servidores conversam por saltos autenticados e cifrados com AES-256-GCM. A topologia limita os vizinhos em uma hierarquia origem → regionais → edges: uma edge busca conteúdo/telemetria em regionais próximos, regionais sincronizam com a origem, e blacklist/gossip podem atravessar vários saltos com deduplicação, limite de hops e retry. A distância geográfica entra no atraso didático; em uma CDN real, DNS/Anycast escolhe o edge, o backbone privado interliga regiões e o conteúdo é puxado por hierarquia/cache shield, em vez de cada edge manter uma conversa full-mesh com o planeta. A árvore do mapa continua sendo uma simplificação visual, não a rota exata usada em cada requisição.

## Arquitetura

```text
React/TypeScript ── REST ──> Flask controller
                                  │
              AES-GCM + HTTP assinado│
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                CDN node 1    CDN node 2    CDN node N
                    │             │             │
                    └── gossip hierárquico cifrado + ACK/retry ──┘

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

O Vite usa `/api` por padrão. Para outro backend, use `VITE_API_BASE_URL`. Se o backend estiver com autenticação de controle, configure também `VITE_CONTROL_TOKEN`. O mapa usa tiles MapTiler Streets com rótulos em português quando `frontend/.env` define `VITE_MAPTILER_KEY`; o código mantém OpenStreetMap como fallback visual quando a chave ainda não foi configurada. Para habilitar exemplos adicionais já instalados pelo `scikit-video`, sem download automático, configure `USE_BIGBUCKBUNNY_DATASET=1`.

Após uma mutação no mapa, o console faz uma leitura nova do control plane mesmo que uma consulta periódica esteja em andamento. Assim, clientes e servidores criados por clique aparecem no próximo snapshot, sem depender de uma requisição antiga.

## Segurança e modo de demonstração

- Endpoints de controle/mutação aceitam `X-CDN-Control-Token` quando `CDN_CONTROL_TOKEN` está configurado. Com a variável vazia, o comportamento é explicitamente **demo local**; CORS continua limitado a `CDN_CORS_ORIGINS` (por padrão, localhost nas portas 5173).
- Mensagens internas usam envelope AES-256-GCM e HMAC sobre o ciphertext, método e path, com timestamp, nonce e TTL de 30 segundos. Nonces já usados são rejeitados; payloads POST internos sem envelope cifrado são recusados.
- Uma blacklist só é aceita por um nó quando o token HMAC da prova corresponde a `client_id`, servidor emissor e assinatura. Mensagens sem credencial/prova são rejeitadas.
- O claim do watermark usa AES-256-GCM para confidencialidade e HMAC-SHA256 para a assinatura do envelope; o sinal visual de 40 bits é derivado do digest e aplicado com portadora adaptativa de baixa frequência nos frames reais. O estúdio gera amostras MP4 H.264 com blur, ruído, resize e diferentes CRFs, depois mede a recuperação pelo detector independente. A auditoria de imperceptibilidade está em `docs/watermark-security-validation.md`; isso é uma demonstração didática, não uma garantia de robustez de produção. O anti-replay implementado é do protocolo interno, com nonce/TTL/estado local.

## Fluxo rápido da API

Inicializar uma rede pequena:

```powershell
$body = @{ num_servers = 3; num_clients = 4; malicious_probability = 0.35; tick_interval_seconds = 2.5; seed = 2026 } | ConvertTo-Json
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
| Dados | `POST /api/clients/{id}/feedback` | registra like/nota e relaciona a percepção à latência observada |
| Topologia | `GET/POST /api/topology/servers` | observa/adiciona nós |
| Segurança | `POST /api/security/watermark/verify` | descriptografa e valida token AES-GCM/HMAC sem expor chave |
| Monitor | `POST /api/monitor/scan` | dispara varredura manual |
| Observabilidade | `GET /api/observability/overview` | snapshot agregado para o console |
| Observabilidade | `GET /api/observability/realtime/stream` | stream SSE persistente para estado, telemetria e gestão |
| Observabilidade | `GET /api/observability/history` | lista historicos completos arquivados |

Uma resposta de stream distingue `artificial_latency_ms`, `http_rtt_ms` e `end_to_end_ms`, além de `request_id`, `trace_id`, candidatos e razão de routing.

## Experimentos didáticos

1. Faça um stream e abra a decisão de routing no Command Center/Network Lab.
2. Desligue o nó selecionado no Network Lab; a próxima chamada deve escolher o próximo candidato saudável e registrar a razão.
3. Injete latência ou perda; observe requests, erros, in-flight, retry e eventos.
4. No Security Observatory, acompanhe cliente → chunk → plataforma simulada → monitor → prova → blacklist → gossip/ACK.
5. No Watermark Studio, reproduza o Big Buck Bunny original, o MP4 entregue ao cliente e a diferença em escala de cinza; confira a descriptografia do claim e as amostras reais de resistência. Depois altere um caractere do token: a prova adulterada deve ser rejeitada.

O roteiro completo está em [`docs/demo-script.md`](./docs/demo-script.md).

## Testes e verificações

```powershell
python -m compileall app.py config.py client_app.py node_app.py controllers models repositories routes services utils tools tests
python -m unittest discover -s tests -v
Push-Location frontend
npm.cmd run build
Pop-Location
```

O smoke E2E local inicia processos CDN e verifica inicialização, stream e overview. `make docker-config` valida o Compose; `make docker-smoke` sobe as imagens, aguarda `/health`, verifica o frontend via Nginx e encerra os containers ao final.

## Decisões e limitações

- A persistência é em memória; interfaces permitem um adaptador futuro para Supabase/PostgreSQL, que não faz parte desta etapa.
- O Big Buck Bunny é um asset local de demonstração, atribuído à Blender Foundation sob CC-BY-3.0; ele continua como fallback. O dataset `kishan51/youtube_clipped_videos` é baixado explicitamente pelo script documentado acima e fica fora do Git; licenças e termos de uso dos clipes devem ser verificados antes de uma distribuição pública.
- Clientes pequenos podem ter processos locais observaveis; populacoes grandes usam clientes virtuais e lotes de telemetria, evitando milhares de processos ociosos.
- Custos mensais, capacidade por nó e latência de fila são cenários didáticos estimados, nunca fatos de produção.
- O monitor é separado por escopo de nó, mas continua coordenado pelo controller no mesmo aplicativo Flask.
- O watermark visual é um canal experimental keyed de 40 bits, derivado do digest do token e aplicado com mascaramento perceptual e portadora de baixa frequência sobre frames reais; o prefixo nos bytes carrega o claim AES-GCM/HMAC cifrado. A série `metrics_history` é limitada a 500 amostras e fica em memória junto com o restante da simulação.

Checklist, C4, ADR, padrões, plano de testes e pendência de equipe:

- [`docs/delivery-2-checklist.md`](./docs/delivery-2-checklist.md)
- [`docs/c4.md`](./docs/c4.md)
- [`docs/adrs/0001-protocolo-interno-e-failover.md`](./docs/adrs/0001-protocolo-interno-e-failover.md)
- [`docs/patterns.md`](./docs/patterns.md)
- [`docs/test-plan.md`](./docs/test-plan.md)
- [`docs/responsibilities.md`](./docs/responsibilities.md)

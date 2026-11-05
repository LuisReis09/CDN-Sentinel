# CDN Security Simulator

Backend em Python/Flask para simular uma CDN de vídeo distribuída, watermarking forense HMAC e monitoramento de pirataria. O console React fica separado em [frontend/](./frontend/).

## Equipe e proposta

Esta implementação é a evolução da [proposta original](./docs/project-proposal.md) registrada no repositório `LuisReis09/CDN-Sentinel`:

- Josué Guedes Ferreira
- Lael Gustavo Batista Ribeiro de Lima
- Luis Gustavo Lacerda Reis

## Arquitetura

- `app.py`: controlador HTTP na porta `5000`, documentação Swagger em `/docs`.
- `node_app.py`: processo independente de cada nó CDN, em uma porta dedicada (`5101`, `5102`, ...).
- `models/`: entidades de domínio.
- `services/`: topologia, streaming, watermarking, monitor, blacklist, gossip e vazamento.
- `controllers/`: orquestração de casos de uso.
- `routes/`: endpoints REST documentados.
- `repositories/`: estado local de cada processo.
- `utils/`: Haversine, latência, HMAC e conteúdo de vídeo.
- `data/cities.json`: catálogo terrestre com 137 cidades para distribuir nós e clientes.

O controlador nunca acessa a memória de um nó CDN para entregar conteúdo ou aplicar blacklist: usa HTTP para streaming, saúde, configuração e denúncias. O gossip também é HTTP entre os processos dos nós. O backend usa o dataset real `scikit-video` `bigbuckbunny` por padrão; o chunk watermarkado continua sendo uma amostra leve do arquivo.

## Entrega 2 — 06/11/2026

Os artefatos de arquitetura e setup solicitados pelo professor estão em [`docs/`](./docs/):

- [Checklist de conformidade](./docs/delivery-2-checklist.md), com evidência de cada requisito.
- [Diagramas C4 níveis 1 e 2](./docs/architecture.md), com fontes PlantUML editáveis.
- [ADRs](./docs/adr/), [stack e justificativas](./docs/stack.md) e [padrões aplicados](./docs/patterns.md).
- [Divisão de responsabilidades](./docs/responsibilities.md), [plano de testes](./docs/test-plan.md) e [roteiro de apresentação](./docs/presentation-plan.md).

## Execução

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:CDN_SECRET_KEY = "troque-esta-chave-em-producao"
python app.py
```

Abra `http://127.0.0.1:5000/docs` para a Swagger UI.

Para executar o console React, veja [frontend/README.md](./frontend/README.md).

## Execução com Docker Compose

Com Docker Desktop em execução:

```powershell
$env:CDN_SECRET_KEY = "troque-esta-chave-em-producao"
docker compose up --build
```

Abra o console em `http://127.0.0.1:8080`, a API em `http://127.0.0.1:5000` e a documentação Swagger em `http://127.0.0.1:5000/docs`. O frontend servido pelo Nginx encaminha `/api` para o backend. A imagem usa `USE_BIGBUCKBUNNY_DATASET=0` por padrão para que o smoke test não dependa de download externo; para usar o dataset local/real, defina essa variável como `1` e garanta que o ambiente tenha o asset disponível.

Para validar apenas a configuração sem iniciar containers:

```powershell
docker compose config --quiet
```

Para encerrar os serviços:

```powershell
docker compose down
```

## Fluxo rápido

Inicializar a rede:

```powershell
$body = @{
  num_servers = 3
  num_clients = 8
  malicious_probability = 0.35
  latency_factor = 1.0
  base_node_port = 5101
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5000/api/control/simulation/init `
  -ContentType "application/json" -Body $body
```

Endpoints principais, organizados por domínio:

- `POST /api/control/simulation/init`: inicializa a simulação.
- `PATCH /api/control/simulation/config`: modifica parâmetros; mudanças estruturais recriam a topologia.
- `POST /api/control/simulation/pause` e `/resume`: pausa/retoma o ciclo.
- `GET /api/control/simulation/status`: estado atual.
- `GET /api/topology/servers`: estado, porta, carga e tamanho da blacklist por nó.
- `GET /api/clients/{id}/stream?chunk=0`: roteamento geográfico, atraso simulado e chunk watermarkado.
- `POST /api/monitor/scan` e `GET /api/monitor/leaks`: monitoramento externo.
- `GET /api/security/blacklist`, `POST /api/security/watermark/verify` e `POST /api/security/watermark/demo`: governança, prova forense e laboratório independente.
- `GET /api/security/watermark/demo/video`: vídeo real Big Buck Bunny servido pelo backend para o laboratório.
- `GET /api/observability/overview`, `/events` e `/traffic`: dados agregados para o dashboard.

## Watermark forense

Cada chunk contém um prefixo `CDNWM1.<payload-base64url>.<hmac-sha256>` dentro dos bytes simulados e também expõe `watermark_token` na resposta. O payload assinado contém `client_id`, `server_id`, `issued_at` e `chunk_id`. O monitor valida o HMAC com a chave secreta, identifica o cliente e o servidor, registra a prova e inicia a propagação da blacklist.

Clientes ativos geram requisições periodicamente, alternam entre online/offline e clientes maliciosos criam vazamentos simulados. O status expõe o perfil de escalabilidade (`gargalo`, `equilibrada` ou `sobredimensionada`), capacidade, utilização, custo estimado e latência de fila.

O endpoint `POST /api/security/watermark/demo` executa um teste autônomo de watermark, extração e validação, sem inicializar a simulação.

## Operação observável

- Cada servidor CDN é um processo independente em uma porta dedicada; cada cliente simulado também recebe um processo independente e PID próprio.
- Cada servidor mantém seu próprio monitor; o endpoint de scan manual existe apenas para compatibilidade e testes.
- `tick_interval_seconds` define o intervalo real do relógio do sistema; em cada tick, cada cliente tem 20% de chance de alternar login/logout.
- A cada tick, mensagens de novo conteúdo e sincronização de metadados podem ser emitidas entre regiões conforme probabilidades próprias; `BLACKLIST_ALERT` continua sendo disparado pelo monitor.
- O diagnóstico expõe latência média/p95, capacidade, custo mensal em USD, receita projetada, ponto de equilíbrio e preço mínimo com margem.
- Mensagens `BLACKLIST_ALERT`, `NEW_CONTENT_DELIVERY`, `METADATA_UPDATE` e `CONTENT_PLAYBACK_TELEMETRY` aparecem na trilha de eventos com origem, destino, payload resumido, probabilidade e ACK.

## Limite do watermark e filtros

O prefixo `CDNWM1.<claim>.<hmac>` é uma prova de transporte: HMAC-SHA256 autentica e protege a integridade do claim, mas não cifra o vídeo e não sobrevive por si só a blur/re-encode que reescreva os bytes. O Watermark Studio também executa um protótipo de sinal robusto spread-spectrum/QIM sobre luminância, medindo blur, ruído e quantização. Esse canal é uma demonstração de viabilidade; uma implantação real precisa operar sobre frames Y decodificados, detector cego calibrado por codec e testes de compressão em escala.

## Testes

```powershell
python -m compileall -q app.py client_app.py node_app.py controllers models repositories routes services tests utils
python -m unittest discover -s tests -v
cd frontend
npm ci
npm run build
cd ..
docker compose config --quiet
```

O CI em [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) repete a compilação, os testes Python, o build do frontend e a validação do Compose.

Ao reinicializar a simulação, os processos CDN iniciados pela instância atual são encerrados e recriados. Os nós não devem ser expostos diretamente à Internet em um ambiente real; esta implementação é uma simulação local de protocolos distribuídos.

## Ferramentas de IA utilizadas

- **ChatGPT/Codex (OpenAI):** apoiou a leitura das especificações, a auditoria do repositório, a redação de C4/ADRs/checklists e a criação do setup Docker Compose, Nginx e CI.
- **Contexto fornecido:** PDF do professor, código-fonte existente e instrução para conferir cada exigência da Entrega 2, dockerizar e validar com terminais.
- **Revisão humana:** a equipe deve conferir os diagramas, substituir os rótulos dos integrantes pelos nomes reais, revisar trade-offs e ensaiar a apresentação. Os testes e builds executados no ambiente são a fonte de verdade; sugestões automáticas que não se aplicavam ao código foram descartadas.

O relato completo está em [`docs/ai-tools.md`](./docs/ai-tools.md).


# CDN Security Simulator

Backend em Python/Flask para simular uma CDN de vídeo distribuída, watermarking forense HMAC e monitoramento de pirataria. O console React fica separado em [frontend/](./frontend/).

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

## Testes

```powershell
python -m compileall .
python -m unittest discover -s tests -v
```

Ao reinicializar a simulação, os processos CDN iniciados pela instância atual são encerrados e recriados. Os nós não devem ser expostos diretamente à Internet em um ambiente real; esta implementação é uma simulação local de protocolos distribuídos.


# Plano do frontend — CDN Security Control Room

## Objetivo

Construir um console administrativo React para observar a simulação CDN como uma operação distribuída: topologia, tráfego, eventos de segurança e ciclo de vida ficam no mesmo contexto operacional.

## Telas e rotas

### `/` — Command center

- Mapa Leaflet mundial com servidores CDN em verde, clientes normais em azul, clientes maliciosos em laranja e clientes banidos em vermelho.
- Linhas animadas/tracejadas de tráfego recente entre clientes e nós.
- Pincel de edição com modos “usuário” e “servidor”; o clique no mapa abre um formulário contextual e persiste a nova entidade no backend.
- Cards de nós saudáveis, clientes, latência média e blacklist.
- Saúde e carga individual dos nós.
- Central única de logs gerais e específicos, com filtro por servidor/cliente.
- Formulário para iniciar ou alterar número de nós, clientes, probabilidade de malícia, fator de latência, intervalo do tick em segundos e preços em USD.
- Botões de pausar e retomar; a varredura é automática e contínua.

### `/security` — Security observatory

- Lista de identidades banidas e quantidade de nós sincronizados.
- Fila de evidências e histórico de varreduras.
- Exposição do mesmo cliente em plataformas externas simuladas, vinculando plataforma, CDN de origem e monitor detector.
- Estado de cada monitor automático por servidor, pendências, último ciclo e cadeia de custódia.

### `/watermark` — Watermark studio

- Explicação visual do pipeline emitir → assinar → extrair → governar.
- Seleção de cliente e geração de um chunk real pela API.
- Exibição do payload Base64, token `CDNWM1` e claim decodificado.
- Validação HMAC feita pelo backend, sem expor a chave secreta no navegador.
- Passo a passo do claim, Base64URL, assinatura, prefixo, fingerprint da chave e teste experimental contra filtros.

### Observabilidade distribuída

- Cada servidor tem porta/PID e cada cliente tem PID próprio.
- Linhas CDN↔CDN são azuis e destacadas; linhas cliente↔CDN são verdes e discretas.
- O mapa usa duas legendas gráficas: entidades/traçados e tipos de comunicação.
- A central de logs mostra `BLACKLIST_ALERT`, `NEW_CONTENT_DELIVERY`, `METADATA_UPDATE` e `CONTENT_PLAYBACK_TELEMETRY`, incluindo origem, destino, resumo do payload e ACK.
- Cada tick registra a chance de churn de sessão; cada cliente alterna login/logout com probabilidade de 0,2 por tick.

## Contrato de dados

O frontend usa `GET /api/observability/overview` como snapshot agregado e atualiza a cada três segundos. Ações de controle usam `/api/control/*`; dados de topologia usam `/api/topology/*`; streaming usa `/api/clients/*`; segurança usa `/api/security/*`; monitor usa `/api/monitor/*`.

## Evoluções previstas

- WebSocket/SSE para eventos sem polling.
- Replay temporal da topologia e do tráfego.
- Heatmap de latência por região.
- Comparação de snapshots de configuração.
- Exportação de evidências e relatório de incidentes.
- RBAC para separar operador, analista de segurança e auditor.


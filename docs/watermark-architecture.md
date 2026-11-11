# Arquitetura atual do watermark forense

Estado experimental da branch `codex/forensic-watermark-reengineering`, derivada de `761e64a`. O simulador continua oferecendo rotas legadas, mas a investigação forense usa o fluxo abaixo.

```text
catálogo local ──> nó CDN ──> claim CDNWM4 ──> ledger SQLite
       │                           │               │
       ├── QIM2 (>=640x360) ───────┤               │
       └── spread (<640x360) ──────┘               │
                └── MP4 entregue, sem token no data plane

upload autorizado ──> SHA-256 ──> detector keyed ──> marcador exato
                                          │                │
                                          └── ledger + AES-GCM/HMAC
                                                   │
                                     comparação de conteúdo alegado
                                                   │
                                      evidência + revisão humana
```

## Identidades e criptografia

`watermark/claims.py` define `CDNWM4`: `watermark_id`, sessão pseudônima, cliente, nó, conteúdo, intervalo, validade, algoritmo, esquema e `kid`. O token usa nonce aleatório de 96 bits, AES-256-GCM e HMAC-SHA256 com subchaves HKDF por finalidade; só o ledger armazena o token. O canal visual carrega um marcador de 48 bits derivado do token, com oito bits de sincronismo. Esse comprimento mantém o custo visual baixo, mas a probabilidade de colisão de aniversário cresce com o número de emissões; o registry rejeita colisões detectadas. Não é um identificador suficiente para uma CDN de milhões de sessões sem uma análise de capacidade mais ampla.

O registry `services/watermark_registry.py` persiste claims, marcador exato, eventos HMAC encadeados por `key_id` e sessões A/B em SQLite WAL. A inclusão de eventos usa transação `BEGIN IMMEDIATE` para serializar a cadeia por chave. Claims novos têm chave única por sessão, conteúdo, segmento, algoritmo e nó; outra requisição da mesma sessão reutiliza token e cache de MP4, enquanto outro nó pode emitir claim próprio no failover. Claims antigos sem esses campos indexados não ganham reutilização retroativa. A verificação histórica depende de manter as chaves antigas no processo. Existe migração aditiva de tabelas; eventos criados antes da coluna `key_id` não entram na nova verificação por chave e exigem auditoria manual. Não há PostgreSQL, retenção automática, backup coordenado ou verificação distribuída. O encadeamento detecta edição local quando verificado desde o início; não fornece imutabilidade contra administrador que controla banco e chave.

## Sinal e distribuição

`utils/qim_watermark.py` aplica DCT/QIM keyed em blocos 8×8 de geometria canônica 640 px, distribui 56 bits entre blocos e agrega até 24 frames no detector. Passo padrão 20. A decisão visual exige sete de oito bits de sincronismo e correlação média de pelo menos 0,15. É um limiar experimental, calibrado em 128 vídeos e conferido em outros 128 negativos locais. O algoritmo não tem sincronismo confiável para crop/rotação, nem máscara perceptual validada por pessoas. Para fontes abaixo de 640×360, o nó usa o spread adaptativo legado. `watermark/algorithms.py` registra os adaptadores; VideoSeal é opcional e não foi executado neste ambiente.

`media/hls_ab.py` prepara offline duas variantes físicas por segmento, A e B, preserva áudio AAC/H.264 em TS, reutiliza o cache e escolhe a playlist por sessão. A sequência é persistida com HMAC e, quando a autenticação de espectador está ativa, usa o mesmo identificador de sessão autorizado. O extractor dos segmentos é experimental: três segmentos curtos retornaram inconclusivos e nenhuma atribuição A/B foi aprovada. A rota MP4 ainda transcodifica uma vez por sessão/conteúdo/segmento/nó; requisições repetidas dessa combinação reutilizam o cache. HLS permanece uma opção separada e não substituiu totalmente a entrega MP4. Não há múltiplas renditions de bitrate, DASH, cache distribuído nem ensaio de concorrência em escala.

## Investigação e governança

`services/forensic_investigation_service.py` recebe mídia por upload limitado a 64 MiB, 180 s, 4K e 60 fps, calcula SHA-256, extrai o marcador sem original nem identidade esperada, consulta o ledger, autentica o claim e compara o arquivo com o conteúdo **alegado pelo claim** por hashes ordenados de frames. A comparação limita transplantes simples de marca, mas não é identificação independente de todo o catálogo nem foi calibrada para milhares de títulos. Só uma comparação positiva gera `PENDING_REVIEW`; `ACCEPT` registra uma revisão, sem blacklist. O monitor simulado mantém evidências inconclusivas como `needs_reanalysis`, com intervalo de cinco minutos para nova tentativa automática e reanálise manual imediata. O operador pode configurar `CDN_CONTROL_TOKEN`; sem ele, a aplicação permanece em modo demo local e não deve ser exposta publicamente.

`services/viewer_session_service.py` acrescenta um modo opt-in para vincular a entrega a uma autorização de espectador. `CDN_REQUIRE_VIEWER_AUTH=1` exige `CDN_CONTROL_TOKEN` e `CDN_VIEWER_SESSION_SECRET`; o operador emite um bearer temporário depois de autenticar a conta fora do simulador. O token está vinculado a cliente, conteúdo e execução da simulação, e seu `session_id` é assinado na chamada interna ao nó e incluído no claim CDNWM4. `/media`, `/stream` e HLS exigem o bearer nesse modo. Isso reforça o vínculo técnico, mas **não implementa um provedor de identidade** nem prova quem segurava a conta.

O Watermark Studio mantém o experimento didático e as APIs antigas para compatibilidade. Seus status `VALID` significam associação exata do marcador e token no fluxo legado; não significam que o conteúdo foi conferido. Para uma decisão forense, use `/api/monitor/investigations` e o relatório de revisão.

## Decisão de engenharia

QIM2 é o padrão **provisório** para fontes >=640×360 por ter PSNR/SSIM maiores que o spread nos clipes medidos e recuperação limpa exata nos três clipes comparados. Após H.264/resize/blur sua recuperação variou por cena. A escolha não equivale a aprovação perceptual nem robustez geral. Mantenha a matriz e a validação humana antes de uso punitivo ou produção.

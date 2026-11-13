# Relatório de implementação da reengenharia forense

> **Registro histórico:** este relatório descreve a rodada anterior. As correções posteriores, a autenticação de operador e os critérios ainda bloqueantes estão em [watermark-finalization-status.md](watermark-finalization-status.md). Nenhuma afirmação de prontidão de produção deve ser inferida dos testes locais aqui registrados.

Branch `codex/forensic-watermark-reengineering`, derivada do commit auditado `761e64a89d2d63ea2334566ff852a5da27b8c2be`, 2026-11-11. Este relatório descreve código e ensaios desta branch; os números históricos estão separados em [watermark-security-validation.md](watermark-security-validation.md).

## Problemas encontrados e correções

| Problema da auditoria | Mudança realizada | Estado |
|---|---|---|
| Token/claim em headers e JSON de entrega | `node_app.py`, `controllers/api_controller.py`, `routes/api.py` e `services/leak_service.py` retiram token do data plane e das URLs/leaks | Corrigido para as rotas testadas |
| Associação por marcador parcial e blacklist automática | `services/watermark_service.py` exige marcador exato; `services/forensic_investigation_service.py` acrescenta claim, conteúdo e revisão; monitor não pune automaticamente | E2E local validado; taxas de erro não calibradas |
| Identidade visual, sessão e claim misturados | `watermark/claims.py` separa CDNWM4; `services/watermark_registry.py` persiste associação e eventos; rotação com `kid` | Funcional em SQLite local |
| Spread de qualidade e robustez variáveis | `utils/qim_watermark.py` adiciona DCT/QIM keyed com redundância espacial; comparado no mesmo benchmark | Padrão provisório >=640×360; ataques variam por cena |
| Transcodificação integral por entrega | `media/hls_ab.py` pré-prepara duas variantes por segmento e playlist por sessão | Opção HLS local, sem substituição total do caminho MP4 |
| Comparação visual dessincronizada e métricas confusas | `WatermarkLab.tsx` sincroniza play/seek/frame, aplica zoom e separa força visual de bits exatos; `NoiseVideoPreview.tsx` não reproduz sozinho | Build executado; sem teste de usabilidade |
| Monitor só conhece o vazamento simulado | Upload multipart independente, SHA-256 e comparação com conteúdo alegado | Funcional para o clipe E2E; sem busca independente de todo catálogo |

## Componentes e contratos

Novos módulos: `watermark/claims.py`, `watermark/algorithms.py`, `watermark/ecc.py`, `watermark/anticollusion.py`, `watermark/content_match.py`, `utils/qim_watermark.py`, `media/hls_ab.py`, `services/forensic_investigation_service.py`. Mudanças principais em `utils/video_watermark.py`, `services/watermark_service.py`, `services/watermark_registry.py`, `services/monitor_service.py`, `node_app.py`, `routes/api.py` e no frontend. `tools/forensic_benchmark.py`, `tools/qim_threshold_calibration.py` e `tools/human_blind_study.py` reproduzem experimentos e preparam estudo humano. O CI compila os novos módulos. `README.md` e os documentos de arquitetura, comparação, ameaça, benchmark e fluxo foram atualizados.

O contrato novo de investigação é `POST /api/monitor/investigations` → `PENDING_REVIEW`, `INCONCLUSIVE` ou `NO_WATERMARK`; a revisão é `POST /api/monitor/investigations/{id}/review`. A rota HLS é `POST /api/clients/{id}/hls/sessions`, seguida de playlist e segmentos TS. Nenhuma dessas rotas aplica blacklist. APIs legadas continuam didáticas, com semântica distinta de `VALID` e sem gate de conteúdo; devem permanecer isoladas de decisões administrativas.

## Evidência executada

- Baseline antes das mudanças: `python -m unittest discover -s tests -v` → 46 testes passaram.
- Após as mudanças, a primeira suíte de 52 testes detectou um erro de parse de `ffprobe` em MPEG-TS. O parser foi corrigido e `python -m unittest tests.test_hls_ab -v` passou.
- `python -m compileall -q app.py node_app.py controllers models routes services media watermark utils tools tests` passou.
- `npm.cmd run build` no frontend passou (aviso de bundle >500 kB).
- `python -m unittest discover -s tests -v` → **52 testes passaram** em 139,245 s, após o ajuste do fixture E2E para um clipe local de 6 s derivado do Big Buck Bunny. O E2E isolado também passou (50,810 s), incluindo dois clientes, recodificação, ingestão, associação, revisão e ausência de blacklist. Duas rodadas intermediárias falharam de modo informativo: parser MPEG-TS incorreto (corrigido) e recuperação visual variável em um clipe do dataset/fixture curto (registrada no benchmark). Uma tentativa concorrente de dois E2Es usou a mesma porta e produziu 503; as execuções finais foram isoladas.
- Uma checagem adicional após a suíte detectou que eventos assinados por chaves diferentes eram verificados como uma única cadeia. `forensic_events.key_id` separa agora as cadeias, e a inclusão usa `BEGIN IMMEDIATE`. O teste de integridade verifica duas chaves e adulteração. Depois do ajuste, `python -m unittest tests.test_forensic_claims tests.test_watermark_e2e_forensics -v` → **4 testes passaram** em 53,276 s, incluindo a revisão E2E. Eventos legados sem `key_id` precisam ser preservados e auditados separadamente.
- Benchmark dos três clipes e 256 negativos, com comandos e resultados por ataque em [watermark-benchmark-results.md](watermark-benchmark-results.md). Um teste Big Buck Bunny de 10 s foi repetido com o limiar atual e gerou hashes de artefatos.

## Pendências objetivas

1. Atribuição robusta em crop, rotação, blur, regravação de tela e múltiplos gêneros; os três clipes não bastam. Limiares de falso positivo/falso negativo e intervalos de confiança precisam de amostras maiores e chaves independentes.
2. Estudo cego com participantes segundo protocolo revisado; `tools/human_blind_study.py` gera somente os materiais. Falta também VMAF/LPIPS e flicker quantitativo.
3. VideoSeal e PixelSeal não foram executados neste ambiente; VideoSeal tem adaptador opcional. DWT, BCH/LDPC, RS corretor real e Tardos integrado à entrega não foram concluídos. A paridade RS atual detecta erro, não corrige.
4. HLS A/B precisa de extração confiável de segmentos curtos, teste de reprodução contínua em players variados, renditions adaptativas, cache distribuído e calibração anti-colusão. `attribution_ready` permanece falso por isso.
5. Ledger SQLite local não atende consistência entre múltiplos nós, retenção, backup ou imutabilidade forte. `CDN_CONTROL_TOKEN` protege POST quando configurado, mas o demo sem token não é um deployment seguro. Faltam RBAC e rate limiting.
6. A licença dos clipes `youtube_clipped_videos` não foi confirmada. O catálogo é apenas comparado após extrair um claim; identificação independente de conteúdo em grande escala está pendente.

**Veredito:** protótipo acadêmico com fluxo forense mais seguro e resultados reproduzíveis. Ainda não aprovado para atribuição punitiva, alegação de invisibilidade humana ou operação de CDN em escala.

## Revisão do checklist crítico recebido depois da primeira entrega

O checklist consultou `feat/watermark-e2e-forensics` no commit `761e64a`; os três commits da primeira reengenharia estão na branch local `codex/forensic-watermark-reengineering`. A consulta à branch remota antiga não cobre esse código. A branch local ainda precisa ser publicada para aparecer no GitHub; não há merge ou deploy nesta entrega.

As críticas que ainda se aplicavam levaram a mudanças adicionais: autorização temporária de espectador vinculada a cliente/conteúdo/execução e sessão no claim; reanálise de vazamentos inconclusivos sem marcar `processed`; omissão da identidade conhecida pelo simulador até atribuição confirmada; reutilização do claim/cache em requisições repetidas da mesma sessão; vinculação da playlist HLS à sessão autorizada. A autenticação depende de um operador externo que confirme a conta antes de emitir o bearer. Ela não é um serviço de login completo.

Continuam pendentes, com prioridade alta: recuperação confiável sob blur/crop/rotação em diferentes fontes, estudo perceptual cego com pessoas, VideoSeal/PixelSeal efetivamente executados no mesmo protocolo, estatística de falsas atribuições em escala, colusão real e uso de HLS como entrega principal com extração A/B validada. A rota MP4 ainda codifica uma vez para **cada nova sessão**; o novo cache elimina a recodificação apenas em requisições repetidas da mesma sessão. Isso não conclui a meta de escalabilidade da CDN.

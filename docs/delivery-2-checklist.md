# Entrega 2 — checklist rastreável

Este documento registra o recorte implementado sobre o código real disponível. Severidade: P0 bloqueia segurança/correção; P1 afeta demonstração; P2 é evolução posterior.

| ID | Problema observado | Severidade | Correção | Prova | Status |
|---|---|---:|---|---|---|
| P0-01 | Chamadas internas controller↔nó não tinham autenticação | P0 | HMAC de método/path/corpo com timestamp, nonce e TTL de 30 s | `test_internal_protocol_has_timestamp_nonce_and_replay_protection`, smoke E2E | concluído |
| P0-02 | `/internal/blacklist` aceitava identidade e assinatura arbitrárias | P0 | destino verifica token HMAC e correspondência client/server/signature | `test_node_rejects_unauthenticated_and_forged_blacklist` | concluído |
| P0-03 | Blacklist não tinha reconciliação para nó novo | P0 | endpoint de reconcile, validação no nó e envio após topologia | `CDNHttpClient.reconcile_blacklist`, smoke de inicialização | concluído |
| P0-04 | Snapshot entregava referências mutáveis | P0 | `SimulationRepository.snapshot()` usa cópia isolada; mutações internas são explícitas | `test_snapshot_does_not_expose_live_mutable_state` | concluído |
| P1-01 | Falha do destino podia derrubar o fluxo | P1 | candidatos saudáveis, failover determinístico e motivo no DTO | `test_stream_fails_over_to_next_healthy_candidate`, smoke com fault | concluído |
| P1-02 | Gossip síncrono não registrava retry | P1 | `message_id`, deduplicação, hops, ACK e fila de retry local | inspeção de `NodeRepository`/eventos de gossip | concluído |
| P1-03 | Métrica `load=0` era ambígua | P1 | requests totais, erros, in-flight, janela de 60 s e latências separadas | status `/api/control/simulation/status`, build e smoke | concluído |
| P1-04 | Não havia experimento de falha acionável | P1 | Network Lab e `POST /api/control/fault/{server_id}` | build frontend; smoke offline→failover | concluído |
| P1-05 | Dataset externo era requisito implícito | P1 | Big Buck Bunny real versionado + fallback determinístico; dataset adicional somente por opt-in | `make docker-smoke` sem download externo | concluído |
| P1-06 | Dashboard não mostrava evolução temporal | P1 | `metrics_history` bounded com blacklist, requisições por nó, latência e saúde; gráficos no dashboard/histórico | `docs/test-plan.md` / build frontend | concluído |
| P1-07 | Ruído visual não era derivado do claim | P1 | Detector independente aplica localizador keyed de 48 bits com sincronização, redundância e portadora de baixa frequência em frames reais; a auditoria mede bits recuperados após filtros | Watermark Studio / `assess_video_robustness` / `docs/watermark-security-validation.md` | concluído |
| P2-01 | Persistência durável e catálogo grande ainda não existem | P2 | interfaces `ContentProvider`/`VideoCatalog`; adaptador futuro documentado | revisão arquitetural | pendente — fora do limite |
| P2-02 | Cliente HTTP real em massa não é objetivo desta etapa | P2 | poucos processos locais + carga virtual limitada | documentação | pendente — fora do limite |

## Dependências e esforço

- P0/P1 implementados sem broker, banco, serviço externo ou credencial nova.
- O smoke E2E cria processos locais e precisa de portas livres.
- Persistência Supabase/PostgreSQL e dataset Hugging Face permanecem fora desta entrega; o sample Big Buck Bunny usado na demo é local e versionado.
- A equipe em `docs/responsibilities.md` precisa de confirmação humana antes da apresentação.

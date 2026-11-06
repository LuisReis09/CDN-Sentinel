# Padrões usados

- **Ports and adapters**: `CDNHttpClient`, `ContentProvider` e `SimulationRepository` isolam transporte, conteúdo e persistência.
- **Snapshot + mutation boundary**: leitores recebem cópias; workers usam `state_ref()` apenas em operações internas curtas.
- **Idempotência**: blacklist é indexada por `client_id`; mensagens têm `message_id` deduplicado.
- **Evidence feed**: monitores processam vazamentos pendentes do próprio `server_id`.
- **Bounded history**: eventos, tráfego, leaks e scans têm limite de 500 itens.
- **Honest telemetry**: `artificial_latency_ms`, `http_rtt_ms` e `end_to_end_ms` são campos distintos; percentis têm janela/denominador.

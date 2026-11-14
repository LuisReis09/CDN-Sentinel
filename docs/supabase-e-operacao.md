# Supabase, persistência e operação segura

## Configuração

O backend lê `.env` sem sobrescrever variáveis já definidas pelo ambiente. As variáveis necessárias são:

```dotenv
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SECRET_KEY=<chave-de-servidor-atual>
```

`SUPABASE_PUBLISHABLE_KEY` não é usada para gravar pelo backend. Ela não deve substituir a chave secreta. Não coloque nenhuma chave em `frontend/.env` com prefixo `VITE_`.

No Compose, apenas o serviço `backend` recebe `SUPABASE_URL` e `SUPABASE_SECRET_KEY`. A imagem do frontend não contém `.env` nem chaves de servidor.

## Esquema

| Tabela | Uso |
|---|---|
| `cdn_simulation_state` | checkpoint corrente do controlador em JSONB. |
| `cdn_simulation_history` | execuções encerradas e seus snapshots. |
| `cdn_watermark_registry` | marcador visual para token. |
| `cdn_forensic_claims` | claims, hashes e vinculação à sessão/conteúdo/nó. |
| `cdn_forensic_events` | cadeia de eventos de custódia. |
| `cdn_ab_sessions` | sessões e fingerprints A/B autenticados. |

A migração `20261114000000_cdn_sentinel.sql` ativa RLS nas seis tabelas, revoga permissões de `anon` e `authenticated` e concede operações apenas a `service_role`. A aplicação acessa as tabelas via Data API; o frontend não chama o banco.

## Aplicação e verificação da migração

```bash
supabase login
supabase link --project-ref <project-ref>
supabase db push --include-all
supabase migration list
```

Depois de iniciar a API, consulte `GET /api/control/simulation/status` ou o snapshot de observabilidade e confira:

```json
{"storage": {"backend": "supabase", "durable": true, "reason": null}}
```

`durable: false` indica credencial ausente/rejeitada ou indisponibilidade da Data API. A simulação continua deliberadamente com fallback local para não perder a demonstração, mas esse modo não substitui a persistência no Supabase.

O cabeçalho do console mostra `SUPABASE DURÁVEL`, `FALLBACK LOCAL` ou `STORAGE PENDENTE` com a mesma informação. Isso permite identificar uma configuração incorreta sem inspecionar logs ou expor a credencial.

## Recuperação e limites

Checkpoints e histórico são duráveis. O processo não ressuscita automaticamente os subprocessos de nó após reinício, pois restaurar PIDs/sockets inativos como se fossem nós saudáveis produziria telemetria falsa. Reinicie a simulação para criar os processos e use o histórico para auditoria.

O fallback SQLite é inicializado apenas como contingência forense local. Testes podem injetar um caminho explícito para garantir isolamento. Em operação com Supabase disponível, ledger de eventos e sessões A/B usam o backend remoto.

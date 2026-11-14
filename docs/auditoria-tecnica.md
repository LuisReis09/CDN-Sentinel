# Auditoria técnica — 14/11/2026

## Escopo

Foram revisados backend, frontend, migrações Supabase, Docker/Compose, Makefile, dependências e documentação. O objetivo foi remover compatibilidades sem consumidores atuais, tornar a infraestrutura executável em WSL e deixar a documentação compatível com o código.

## Achados e correções

| Achado | Correção |
|---|---|
| Captura forense elevava p95/SLO de clientes. | Tráfego `forensic_capture` foi separado de latência, RPS, mapa, feedback e contador de vídeos do cliente. |
| Cliente em quarentena não era sempre marcado no payload visual. | API informa `forensic_quarantined` para leases válidos; mapa renderiza cinza. |
| Compose não recebia credenciais Supabase. | `SUPABASE_URL` e `SUPABASE_SECRET_KEY` foram passadas exclusivamente ao backend. |
| Imagem backend executava como root. | Dockerfile agora cria e usa usuário de aplicação sem privilégios. |
| Compose podia deixar subprocessos órfãos. | Backend usa `init: true`; o Makefile deixou de usar `kill 0`. |
| NumPy era importado sem ser dependência direta. | `numpy` foi declarado em `requirements.txt`. |
| Compatibilidades de configuração não tinham consumidor atual. | Foram removidos `simulation_speed` e aliases `*_unit`; o contrato usa `tick_interval_seconds` e valores `*_usd`. |
| README apontava para documentos removidos. | README e documentos aprofundados foram reestruturados. |

## Validações executadas

- `python -m compileall` para backend, serviços, modelos, repositórios e rotas: aprovado.
- Testes direcionados de métricas, quarentena, ledger remoto simulado e histórico Supabase: aprovados.
- Módulos de segurança de entrega, claims forenses, estados forenses e gestão: aprovados.
- `npm.cmd run build`: aprovado; o Vite emite apenas o aviso de chunk acima de 500 kB.
- `supabase migration list`: a migração `20261114000000` foi confirmada no projeto vinculado.

O E2E de vídeo reencodado ultrapassa o limite de 30 segundos do executor desta sessão. Ele foi iniciado e liberou a porta temporária ao terminar, mas o executor não reteve o resultado final; portanto, a confirmação desse teste fica para o job `docker-validation` da CI ou para `make docker-test` em ambiente sem esse limite.

## Bloqueador de infraestrutura local

O Docker CLI está instalado, mas o daemon não estava acessível no ambiente desta auditoria (`//./pipe/docker_engine` inexistente) e o WSL retornou acesso negado. Por isso, `make docker-build`, `make docker-test` e `make docker-smoke` não puderam ser executados aqui e não são declarados como aprovados. Assim que Docker Desktop/Engine e a integração WSL estiverem ativos, execute os três comandos nessa ordem.

## Pendências humanas

1. Substituir `SUPABASE_SECRET_KEY` caso o status informe credencial rejeitada; não publicar a chave.
2. Preencher matrícula e confirmar a contribuição de todos os integrantes.
3. Versionar capturas reais da interface em `docs/imagens/` antes da entrega.
4. Rodar a validação Docker no ambiente com daemon ativo e registrar o resultado.

# Plano de testes da Entrega 2

## Objetivo

Demonstrar que o setup inicial é reproduzível e que as decisões arquiteturais principais têm validação automatizada ou observável.

## Matriz de validação

| Cenário | Tipo | Comando/critério | Resultado esperado |
|---|---|---|---|
| Sintaxe do backend | Unitário/estático | `python -m compileall -q .` | Nenhum erro de compilação. |
| Regras de watermark | Unitário | `python -m unittest discover -s tests -v` | HMAC identifica cliente/servidor/chunk e rejeita adulteração. |
| Latência geográfica | Unitário | Mesmo conjunto de testes | Haversine e multiplicador produzem atrasos ordenados. |
| Sinal robusto experimental | Unitário | Mesmo conjunto de testes | Blur, ruído e re-encode do protótipo mantêm confiança mínima. |
| Build do console | Build | `cd frontend; npm ci; npm run build` | TypeScript e Vite geram `frontend/dist`. |
| Contrato HTTP | Integração/smoke | `GET /health`, `GET /docs`, `GET /api/observability/overview` | Backend responde e a API documentada está disponível. |
| Topologia distribuída | Integração | Inicializar 2–3 nós e consultar `/api/topology/servers` | Nós possuem portas/PIDs e status `healthy`. |
| Propagação de segurança | Integração | Gerar leak, executar `/api/monitor/scan`, consultar blacklist | Evidência válida gera `BLACKLIST_ALERT` e peers recebem o registro. |
| Ambiente empacotado | Deployment | `docker compose config --quiet`; `docker compose up --build` | Compose válido, backend healthy e console acessível. |

## Testes previstos para a Entrega 3

- carga progressiva de clientes e medição de p95;
- falha/indisponibilidade de um nó e comportamento do roteamento;
- integração de ponta a ponta com blacklist e telemetria;
- persistência/reinício e comparação do estado antes/depois;
- varredura de dependências e imagem, caso o pipeline de segurança seja ampliado.

## Evidência de execução local

Os comandos executados pelo responsável por testes devem ser registrados no histórico da entrega, junto de data, duração, número de testes e eventuais correções. O workflow de CI repete automaticamente as verificações de compilação, testes, build frontend e configuração Compose.

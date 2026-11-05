# Roteiro da apresentação — 12 a 15 minutos

Roteiro sugerido com duração total de aproximadamente 13 minutos e 30 segundos:

| Tempo | Responsável | Conteúdo |
|---:|---|---|
| 0:00–1:30 | Integrante 1 | Problema: distribuição de vídeo, pirataria e necessidade de atribuição forense. Critérios de sucesso. |
| 1:30–4:00 | Integrante 1 | C4 níveis 1 e 2, fronteiras do control plane/edge nodes e ADRs principais. |
| 4:00–6:30 | Integrante 2 | Demonstração da inicialização, processos/PIDs, portas, roteamento Haversine e latência. |
| 6:30–9:00 | Integrante 3 | Console React, mapa, tráfego, logs e Watermark Studio. |
| 9:00–11:00 | Integrante 4 | `docker compose up --build`, health check, proxy Nginx e CI. |
| 11:00–12:30 | Integrante 5 | Testes, métricas, propagação de blacklist e limitações/trade-offs. |
| 12:30–13:30 | Todos | Lições aprendidas, próximos passos da Entrega 3 e perguntas. |

## Demonstração mínima

1. Abrir o console e mostrar o estado offline antes da inicialização.
2. Inicializar 3 servidores e 8 clientes.
3. Mostrar no mapa os nós, clientes, rotas e eventos entre servidores.
4. Abrir o laboratório de watermark e validar uma prova HMAC.
5. Executar ou aguardar um scan de leak e mostrar `BLACKLIST_ALERT`/ACK nos logs.
6. Mostrar `docker compose ps`, `/health` e `/docs` como evidência do setup.

O roteiro deve ser ensaiado para permanecer entre 12 e 15 minutos; a apresentação final presencial e a participação dos cinco integrantes permanecem como obrigação da Entrega 3.

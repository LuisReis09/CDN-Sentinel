# Checklist de conformidade — Projeto 02 (06/11/2026)

Este checklist separa os requisitos da Entrega 2 das obrigações da entrega final. Os itens marcados como implementados têm evidência no repositório; os itens de apresentação/histórico ainda dependem da equipe.

| Status | Exigência | Evidência / ação |
|---|---|---|
| [x] | C4 nível 1 — contexto | [`docs/c4-context.puml`](./c4-context.puml) e [`docs/architecture.md`](./architecture.md). |
| [x] | C4 nível 2 — containers | [`docs/c4-containers.puml`](./c4-containers.puml) e [`docs/architecture.md`](./architecture.md). |
| [x] | Pelo menos 2 ADRs iniciais | ADR-0001, ADR-0002 e ADR-0003 em [`docs/adr/`](./adr/). |
| [x] | Stack tecnológico e justificativas | [`docs/stack.md`](./stack.md). |
| [x] | Pelo menos 3 padrões arquiteturais | Seis padrões mapeados em [`docs/patterns.md`](./patterns.md). |
| [x] | Setup inicial com Docker Compose | [`docker-compose.yml`](../docker-compose.yml), `Dockerfile`, `frontend/Dockerfile` e proxy Nginx. |
| [x] | CI básico | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). |
| [x] | Divisão de responsabilidades | [`docs/responsibilities.md`](./responsibilities.md); substituir `Integrante 1–5` pelos nomes reais. |
| [x] | README documentado e instruções de execução | [`README.md`](../README.md), documentação da API em `/docs` e links para os artefatos. |
| [x] | Declaração obrigatória de IA no README | Seção “Ferramentas de IA utilizadas” no README e versão detalhada em [`docs/ai-tools.md`](./ai-tools.md). |
| [x] | Plano de testes | [`docs/test-plan.md`](./test-plan.md), testes existentes e CI. |
| [ ] | Apresentação de 12–15 minutos | [`docs/presentation-plan.md`](./presentation-plan.md) pronto; ensaiar e confirmar participação dos cinco integrantes. |

## Conferência da entrega final (Projeto 03)

Ainda não são critérios de conclusão desta revisão, mas devem ser acompanhados:

- repositório Git acessível ao professor;
- código funcional e testes de carga, resiliência e integração com resultados;
- ADRs e C4 atualizados após implementação;
- trade-offs finais e relatório de métricas;
- apresentação presencial de 12–15 minutos;
- histórico de commits demonstrando contribuição de todos os integrantes.

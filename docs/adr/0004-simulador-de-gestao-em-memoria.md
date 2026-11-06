# ADR-0004: simulador de gestão separado da telemetria

- Status: aceito
- Data: 2026-11-06

## Decisão

Adicionar `management/` como domínio independente, com `ManagementState`,
`ManagementEngine`, `ActionRegistry` e cenários determinísticos. O motor usa o
repositório em memória atual e recebe a `SimulationController` por composição;
assim, decisões econômicas consultam capacidade/saúde dos nós reais sem
misturar saldo e clientes pagantes com `SimulationState`.

Somente seis `action_type` são permitidos: `horizontal_scale`,
`vertical_scale`, `price_adjustment`, `cache_upgrade`, `load_balancing` e
`metadata_upgrade`.

## Motivos

- Separar fato observado, simulação didática e projeção financeira.
- Validar custo, cooldown, versão e pré-requisitos no servidor.
- Preparar um repositório futuro sem integrar Supabase/PostgreSQL agora.
- Manter Network Lab, Security Observatory, Watermark Studio e histórico sem
  transformar o produto em um jogo de cartas.

## Consequências

O backend passa a produzir eventos e ações pendentes com lead time; a tela de
gestão consulta o estado canônico e não aplica dinheiro no React. O estado é
volátil e os valores econômicos são deliberadamente didáticos.

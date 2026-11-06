# Simulador de gestão da CDN

## Escopo

O modo Gestão é uma camada de negócio didática sobre a topologia HTTP local.
`ManagementState` não substitui `SimulationState`, os estados locais dos nós ou
a telemetria. Ele consulta esses dados e mantém, em memória, saldo, clientes
pagantes, demanda virtual, custos, ações pendentes, objetivos e histórico.

Um tick do simulador de gestão representa um dia simulado. O intervalo real
continua sendo o configurado no Control Plane (0,5–5 s). O mês didático tem 30
dias; custos mensais são divididos por 30 uma vez por tick.

```text
daily_revenue = paying_clients * monthly_price / 30
daily_opex = (node_costs + fixed_cost + cache_cost
              + balancing_cost + metadata_cost) / 30
daily_profit = daily_revenue - daily_opex
cash_balance += daily_profit - investments_applied
monthly_margin = 100 * (daily_profit * 30) / max(daily_revenue * 30, epsilon)
```

Demanda e elasticidade são explicitamente simuladas. RTT HTTP, fila, erros,
p95 e estados de saúde são observados nos processos CDN locais. Quando não há
amostras suficientes, o p95 é indicado como estimado pelo modelo e não como
medição de produção.

## As seis ações econômicas

| Tipo | Investimento base | Efeito principal | Trade-off |
|---|---:|---|---|
| `horizontal_scale` | US$ 650 | adiciona/retira um nó e aumenta cobertura/capacidade | implantação, mensalidade e risco de cobertura |
| `vertical_scale` | US$ 220 | eleva Basic → Standard → Pro → Enterprise | manutenção e custo recorrente do tier |
| `price_adjustment` | US$ 0 | altera receita por pagante | elasticidade, churn e demanda gradual |
| `cache_upgrade` | US$ 180 × nível | melhora hit rate e cold miss | RAM, armazenamento e banda de prefetch |
| `load_balancing` | US$ 80 | nearest, least-utilized ou política híbrida | balancear para longe pode aumentar latência |
| `metadata_upgrade` | US$ 140 | linear → índice → réplica de leitura simulada | memória, custo de escrita e staleness |

Os valores são parâmetros didáticos, não preços de provedor cloud. Cada ação é
validada no backend por saldo, versão do estado, cooldown, tier, nó e limite.
Uma decisão fica `pending` até o dia de aplicação e gera eventos com
`simulation_id`, dia, `action_id`, custos e resultado.

## Cenários

`free`, `rapid-growth`, `regional-peak`, `catalog-spike` e `node-outage` usam
uma seed explícita. O primeiro pressiona crescimento; o segundo destaca
cache/prefetch; o terceiro cria workload de catálogo; o último representa uma
falha operacional de laboratório. Cenários não são ações econômicas e não
criam uma sétima categoria.

## API

- `GET /api/management/state`
- `GET /api/management/actions`
- `POST /api/management/actions`
- `GET /api/management/scenarios`
- `POST /api/management/scenarios/start`
- `GET /api/management/history`
- `POST /api/management/reset`

O armazenamento atual é um repositório em memória. Não há Supabase,
PostgreSQL, migrations remotas, dataset Hugging Face ou credenciais externas.
As interfaces de domínio permitem um repositório persistente futuro.

## Roteiro de apresentação

1. Inicie `rapid-growth` com seed fixa e observe saldo, p95, demanda e pressão.
2. Selecione um nó no mapa e compare as prévias vertical e horizontal.
3. Confirme uma ação; mostre `pending`, avance ticks e observe custo/capacidade.
4. Aumente o preço; acompanhe receita, churn e demanda ao longo de dias.
5. Em `regional-peak`, aplique cache e compare hits/custo com o cenário base.
6. Abra Network Lab para falha/failover; isso é laboratório operacional, não uma
   ação econômica adicional.

## Limitações honestas

- A demanda para milhares de usuários é virtual; as chamadas HTTP locais são
  amostras observáveis e não representam tráfego de Internet.
- A camada de metadados é uma comparação didática em memória; não existe banco
  externo conectado.
- O watermark visual usa MP4s locais versionados e transformações reais de
  frames, mas o detector robusto de produção continua fora do escopo.
- O estado de gestão é perdido ao reiniciar o backend; persistência e
  autenticação multiusuário ficam para uma etapa futura.

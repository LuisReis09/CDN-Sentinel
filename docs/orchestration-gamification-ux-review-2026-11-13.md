# Revisão crítica — Orquestração e Gamificação

Data: 2026-11-13

## Escopo e roteiro executado

Esta revisão usou uma instância local isolada, com três nós virtuais e o mesmo backend/API da aplicação. A separação evitou que processos antigos nas portas de desenvolvimento interferissem na medição.

1. Inicializei a orquestração com 3 nós, 72 clientes, `1,0 req/s` por cliente e tick de `1,25 s`.
2. Consultei o snapshot de observabilidade e confirmei 72/72 clientes ativos, `100%` de saúde e tick aplicado.
3. Elevei a carga para 216 clientes: `151%` de utilização, saúde global em `5%` e os 3 nós em `overloaded`.
4. Iniciei **Crescimento rápido** e confirmei 100 clientes reais no mapa/telemetria, 100 clientes ativos e as seis ações disponíveis.
5. Apliquei escala vertical em um nó. Após o prazo didático, a capacidade foi de `143,052` para `214,577 req/s` e a utilização do jogo caiu de `8,421` para `6,441`.
6. Compilei o front-end em produção. A tentativa de inspeção com navegador headless local alcançou a aplicação e o canal SSE, mas o ambiente não forneceu uma captura composta confiável; por isso, conclusões visuais abaixo são sustentadas também pela árvore React/CSS compilada e pelos fluxos de API exercitados, sem alegar cliques manuais que não ocorreram.

## Parecer como usuário

### Experiência geral e clareza

- A divisão **Orquestração / Gamificação** é conceitualmente boa: a primeira mostra a malha, a segunda transforma capacidade, preço e qualidade em decisões.
- O primeiro problema perceptível era enganoso: mesmo sob estresse o card global dizia 100% e os nós continuavam verdes. Isso anulava a utilidade do mapa como instrumento de decisão.
- Também havia ruído operacional: conexão/desconexão de clientes fazia o observador confundir sessão opcional de processo com disponibilidade do cliente e pressionava a máquina com trabalho de watermark em segundo plano.
- As ações são suficientes e coerentes. Escala horizontal/vertical, cache, balanceamento, metadados e preço cobrem as alavancas que o modelo realmente calcula. Adicionar botões sem nova causalidade só poluiria a tela. Um possível modo de contingência é uma ideia futura, não uma ação adicionada artificialmente agora.

### Ritmo e jogabilidade

- O tick de orquestração em `1,25 s` deixa telemetria e mapa responsivos.
- Porém, usar cada tick como um dia do jogo dava pouco tempo para ler um alerta, comparar trade-offs e confirmar uma ação. O calendário de gestão agora avança no máximo uma vez a cada `2,5 s` (ou mais devagar se o tick operacional for maior); a telemetria continua rápida.
- Os cenários passaram de 16–22 para 72–100 clientes iniciais. A carga deixa de parecer um protótipo vazio e permite que escala, cache e preço tenham impacto observável.

### Mapa e densidade de informação

- Cem marcadores ainda são legíveis em um mapa mundial, mas rotas individuais em excesso rapidamente escondem os nós. Foram limitadas as linhas de tráfego, pacotes e mensagens; a legenda ficou recolhida por padrão e foi removida a categoria de “cliente inativo”.
- Cores agora comunicam estado efetivo: verde saudável, laranja degradado, vermelho sobrecarregado, cinza indisponível. Pop-ups e cartões de nó incluem pressão, P95 e fila, em vez de exigir inferência pela cor.
- O mapa continua sendo um plano de exploração; os detalhes densos ficam no painel de nós e não em mais camadas visuais sobre o globo.

### Satisfação do cliente

- A satisfação já é a métrica central do jogador e precisava ficar explícita. O cartão dedicado relaciona satisfação a P95, erros, preço, feedback, reputação, chegadas e churn, além de fornecer sugestões condicionais: ampliar capacidade/cache/balanceamento quando há pressão e rever preço quando ele está acima da referência.
- Essa orientação é preferível a esconder a fórmula ou apresentar um único número de SLA, pois deixa claro *por que* a receita/população se move.

## Ajustes incorporados após a revisão

| Achado | Ajuste incorporado | Evidência de validação |
| --- | --- | --- |
| Sessões oscilavam entre online/offline | Todos os clientes ativos permanecem disponíveis; telemetria de demanda é agregada e não gera streams QIM/FFmpeg em background. | Teste dedicado sem eventos de conexão/desconexão. |
| Orquestração lenta e concorrendo com mídia | Tick padrão de 2,5 s para 1,25 s; monitores forenses ficam no mínimo a cada 2,5 s. | Configuração e API retornam 1,25 s; entrega real continua independente. |
| Cenários com poucos clientes | Bases dos cenários em 72–100 e cenário sincroniza população real/configuração ao iniciar. | “Crescimento rápido”: 100/100 ativos. |
| Saúde global fixada em 100% e nós verdes | Saúde combina disponibilidade de nós, pressão, P95 e sucesso; nós recebem estado observável no mesmo snapshot. | A 151%: saúde 5%, três nós `overloaded`. |
| Nó não podia recuperar visualmente após escala | Campos derivados de pressão não acumulam fila/rejeição histórica; contador cumulativo não mantém o nó vermelho sozinho. | Teste de recuperação após aliviar carga. |
| Calendário da gestão rápido demais | Dia da gestão independente, com intervalo mínimo de 2,5 s. | Teste de cadência 1,25/0,5/5,0 s. |
| Legenda e rotas competiam com os dados | Legenda recolhida e limites para overlays/linhas; estado inativo removido. | Compilação do front-end concluída. |

## Recomendações de uso

1. Comece pelo cenário e leia o objetivo/satisfação antes de agir.
2. Use P95, pressão, fila e saúde dos nós juntos. Saúde baixa não deve ser compensada apenas com preço.
3. Compare custos e prazo das seis ações no console; ações pendentes não são efeitos imediatos.
4. Use o mapa para localizar o problema e o painel de nós para confirmar P95/pressão antes de escalar.

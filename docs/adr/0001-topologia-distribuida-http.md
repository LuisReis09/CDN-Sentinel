# ADR-0001: topologia distribuída com processos HTTP independentes

- Status: aceito
- Data: 2026-11-05
- Decisores: equipe do projeto

## Contexto

O tema exige uma solução que demonstre comunicação distribuída, roteamento, latência e propagação de evidências. Um único processo com chamadas diretas entre objetos esconderia as fronteiras de rede e dificultaria a demonstração.

## Decisão

Manter um control plane Flask para orquestração e iniciar cada CDN como um processo Python separado (`node_app.py`), com uma porta HTTP dedicada. O control plane usa `CDNHttpClient`; os nós usam envelopes AES-256-GCM assinados com HMAC sobre HTTP para alertas e telemetria. A TopologyService organiza a conversa como origem, regionais e edges, com vizinhança limitada, enquanto clientes simulados continuam independentes para tornar a topologia observável.

## Consequências

### Positivas

- Demonstra comunicação entre processos, health checks, latência e falhas de nó de forma concreta.
- Mantém o control plane separado do estado local de cada edge node.
- Permite que a apresentação mostre PIDs, portas, mensagens e ACKs.

### Negativas e mitigação

- A inicialização local gerencia vários processos e portas; `SimulationController` encerra os processos criados pela instância.
- O protótipo usa memória, sem persistência após reinício; isso está explicitado como trade-off para a Entrega 3.
- Em produção, a descoberta e o ciclo de vida deveriam ser delegados a um orchestrator/service registry; no protótipo, o catálogo de topologia cumpre esse papel didático.

# ADR 0001 — protocolo interno mínimo e failover determinístico

## Decisão

Usar HTTP local existente, com HMAC compartilhado por simulação. Cada mensagem carrega timestamp, nonce e assinatura sobre método, path e hash do corpo. O receptor aplica TTL de 30 segundos e deduplicação de nonce. Gossip usa `message_id`, lista de visitados, limite de hops, ACK e fila de retry no processo.

O roteamento ordena candidatos saudáveis por distância Haversine e `server_id`. Erro HTTP marca o candidato offline e tenta o próximo. O DTO expõe candidatos e razão.

## Trade-off

É pequeno, auditável e não exige broker/PKI para a Entrega 2. Não substitui mTLS, rotação de chaves, autorização por papel ou persistência de fila em produção. O HMAC do watermark continua uma prova de integridade; replay do token fora do protocolo interno permanece possível e é documentado.

## Alternativas rejeitadas

Broker e mTLS aumentariam dependências e esforço sem melhorar a demonstração local proporcionalmente. Falhar fechado sem failover esconderia o comportamento distribuído que a entrega precisa mostrar.

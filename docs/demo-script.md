# Roteiro de demonstração (12–15 min)

1. **0:00–2:00 — escopo**: explicar que tudo roda localmente, em memória, e que coordenadas são simuladas.
2. **2:00–4:00 — inicialização**: iniciar Flask/console e mostrar processos, PID, porta, health e seed.
3. **4:00–6:00 — routing**: fazer um stream; abrir a decisão e separar atraso geográfico, RTT HTTP e E2E.
4. **6:00–8:30 — failover**: Network Lab → desligar o nó selecionado → repetir stream → mostrar candidato excluído, erro e novo destino → recuperar.
5. **8:30–11:00 — segurança**: Watermark Studio; verificar token íntegro, adulterar um caractere e mostrar rejeição. Reforçar que HMAC não é watermark visual resistente a re-encode.
6. **11:00–13:00 — evidência**: Security Observatory; explicar cliente → chunk → plataforma externa simulada → monitor → prova → blacklist → ACK.
7. **13:00–15:00 — gossip**: aplicar perda, observar retry/rejeição e restauração; terminar com limitações e roadmap.

Todos os resultados devem ser lidos da UI/API atual. Não usar números decorativos como se fossem observações.

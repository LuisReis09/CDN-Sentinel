# Plano de testes

## Automático

```powershell
python -m compileall app.py config.py client_app.py node_app.py controllers models repositories routes services utils tests
python -m unittest discover -s tests -v
Push-Location frontend
npm.cmd run build
Pop-Location
```

Os testes unitários não dependem de Internet nem de relógio fixo. O teste de nó usa Flask test client; o failover usa um adapter fake que injeta `ConnectionError`.

## Smoke E2E local

1. Inicializar dois nós e um cliente com portas efêmeras/livres.
2. Fazer `GET /api/clients/{id}/stream?chunk=0` e verificar `request_id`, `trace_id`, atraso artificial, RTT e E2E.
3. Aplicar `POST /api/control/fault/{server_id}` com `{"offline":true}`.
4. Repetir stream e verificar novo destino e razão de failover.
5. Restaurar com `{"offline":false,"extra_latency_ms":0,"drop_rate":0}`.

Docker Compose é validado com `make docker-config`. O smoke de containers usa `make docker-smoke`: constrói backend/frontend, aguarda `/health`, executa o demo do Watermark Studio com o Big Buck Bunny, acessa a página pelo Nginx e encerra o stack ao final. O teste manual completo usa `make docker-up`.

## Telemetria temporal

1. Inicializar uma simulação e aguardar pelo menos três ciclos de atualização do console.
2. Confirmar que `GET /api/observability/overview` retorna `metrics_history`.
3. Conferir as séries de blacklist, requisições acumuladas por servidor, latência média/p95 e saúde geral.
4. Encerrar a simulação e conferir que o histórico arquivado preserva `metrics_history`.

## Watermark Studio

1. Executar a demonstração sem `video_id` e confirmar `video_id=bigbuckbunny`.
2. Reproduzir original, sinal HMAC e diferença; confirmar que as variantes têm origem no MP4 real.
3. Conferir que cada filtro exibe `bits_correct / bits_total`, confiança igual à razão desses valores e limiar de 90%.

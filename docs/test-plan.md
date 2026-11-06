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

Docker Compose não está presente na árvore auditada; portanto startup/health de containers: **não verificado**.

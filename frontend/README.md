# CDN Security Control Room

Frontend React/Vite separado do backend Flask.

## Rodar

Na raiz do projeto, inicie o backend:

```powershell
python app.py
```

Em outro terminal:

```powershell
cd frontend
npm install
npm run dev
```

Abra `http://127.0.0.1:5173`.

O Vite encaminha automaticamente `/api` para `http://127.0.0.1:5000`. Portanto, mantenha o backend Flask rodando em outro terminal antes de abrir o console.

Para apontar para outro backend:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:5000/api"
npm run dev
```

Veja [PLAN.md](./PLAN.md) para a arquitetura de telas, rotas e próximas evoluções.


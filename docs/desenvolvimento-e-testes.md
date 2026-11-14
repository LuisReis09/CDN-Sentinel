# Desenvolvimento, testes e Docker

## Comandos locais

| Comando | Efeito |
|---|---|
| `make install` | instala dependências Python e usa `npm ci` no frontend. |
| `make backend` / `make frontend` | inicia somente um dos lados. |
| `make dev` | inicia backend e Vite; encerra apenas processos iniciados pelo alvo. |
| `make test-backend` | compila fontes Python e executa `unittest discover`. |
| `make test-frontend` | executa `npm run build`. |
| `make test` | executa backend e frontend. |
| `make docker-config` | valida a sintaxe e interpolação do Compose. |
| `make docker-build` | constrói imagens com Docker Compose. |
| `make docker-test` | roda os testes Python dentro da imagem backend. |
| `make docker-smoke` | valida stack, health, watermark e proxy, depois derruba os serviços. |

O Makefile pressupõe Bash, GNU Make, curl e Docker Compose v2; é destinado a WSL/Linux. No Windows sem WSL, rode os comandos equivalentes de Python, npm e Docker manualmente.

## Estratégia de testes

- **Unidade/domínio:** capacidade, seleção geográfica, criptografia, ECC, claims, catálogo, gestão e métricas.
- **Integração:** NodeRepository, protocolo interno, blacklist, sessões de espectador, HLS A/B e registry.
- **Forense/E2E local:** geração de MP4, reencodificação, detector visual, investigação e revisão.
- **Frontend:** `tsc -b` e build Vite em produção.
- **Contêiner:** imagem backend executa a suíte Python; smoke valida comunicação pelo Nginx.

## Dependências diretas

`requirements.txt` lista Flask, RESTX, CORS, Requests, NumPy, Pillow, SciPy, Cryptography, scikit-video e Hugging Face Hub. NumPy aparece explicitamente porque os algoritmos de watermark o importam diretamente, mesmo sendo dependência transitiva de outras bibliotecas.

## Boas práticas de execução

- Mantenha Docker Desktop ativo e com integração WSL habilitada antes de executar os alvos Docker.
- Não execute testes E2E concorrentes com uma simulação local que use a mesma faixa de portas.
- O dataset Hugging Face é opcional e fica fora do Git; Big Buck Bunny é o fallback local.
- Não use dados de produção, credenciais reais ou chaves no frontend durante a demonstração acadêmica.

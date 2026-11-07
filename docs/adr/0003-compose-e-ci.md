# ADR-0003: execução local padronizada com Docker Compose e CI

- Status: aceito
- Data: 2026-11-05
- Decisores: equipe do projeto

## Contexto

A Entrega 2 exige setup inicial do ambiente com Docker Compose e CI básico. O projeto precisa ser executável de forma repetível, com backend Python, frontend React e proxy entre os dois.

## Decisão

Usar duas imagens: backend Python/Flask e frontend compilado em uma imagem Node multi-stage servida por Nginx. O Nginx encaminha `/api` para o serviço `backend`; o Compose aguarda o health check do backend antes de iniciar o frontend. O `Makefile` fornece os comandos Linux `make docker-up`, `make docker-smoke` e `make dev`. O workflow `.github/workflows/ci.yml` executa compilação/testes Python, build TypeScript/Vite e validação da configuração Compose.

## Consequências

- `docker compose up --build` reproduz o ambiente completo em uma máquina com Docker.
- O frontend não precisa conhecer o endereço interno do backend; usa `/api` e o proxy do Nginx.
- A imagem Docker inclui o sample real local de Big Buck Bunny e desabilita somente o dataset adicional opcional por padrão; nenhum download externo é necessário para o smoke test.
- A infraestrutura ainda não inclui registry, assinatura de imagem ou deployment gradual; esses itens são candidatos à Entrega 3.

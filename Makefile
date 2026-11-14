SHELL := /bin/bash

PYTHON ?= python3
NPM ?= npm
COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help install dev backend frontend build test test-backend test-frontend docker-config docker-build docker-test docker-up docker-down docker-logs docker-smoke

help:
	@echo "CDN-Sentinel"
	@echo "  make install       instala dependências Python e frontend"
	@echo "  make dev           executa backend e frontend em terminais/processos locais"
	@echo "  make build         compila o frontend"
	@echo "  make test          roda compileall, unittest e build do frontend"
	@echo "  make docker-build  constrói as imagens Docker"
	@echo "  make docker-test   executa a suíte Python dentro da imagem backend"
	@echo "  make docker-up     sobe o stack completo com Docker Compose"
	@echo "  make docker-smoke  sobe, testa health/API/frontend e encerra os containers"
	@echo "  make docker-down   encerra o stack Docker"

install:
	$(PYTHON) -m pip install -r requirements.txt
	cd frontend && $(NPM) ci

dev:
	@set -euo pipefail; \
	$(PYTHON) app.py & backend_pid=$$!; \
	(cd frontend && $(NPM) run dev -- --host 0.0.0.0) & frontend_pid=$$!; \
	trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true; wait $$backend_pid $$frontend_pid 2>/dev/null || true' EXIT INT TERM; \
	wait $$backend_pid $$frontend_pid

backend:
	$(PYTHON) app.py

frontend:
	cd frontend && $(NPM) run dev -- --host 0.0.0.0

build:
	cd frontend && $(NPM) run build

test:
	$(MAKE) test-backend
	$(MAKE) test-frontend

test-backend:
	$(PYTHON) -m compileall -q app.py client_app.py node_app.py controllers models repositories routes services tests utils
	$(PYTHON) -m unittest discover -s tests -v

test-frontend:
	$(MAKE) build

docker-config:
	$(COMPOSE) config --quiet

docker-build:
	$(COMPOSE) build --pull

docker-test: docker-build
	$(COMPOSE) run --rm --no-deps backend python -m unittest discover -s tests -v

docker-up:
	$(COMPOSE) up --build

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f --tail=200

docker-smoke:
	@set -e; \
	trap '$(COMPOSE) down' EXIT; \
	$(COMPOSE) up -d --build; \
	for attempt in $$(seq 1 30); do \
		if curl --fail --silent http://127.0.0.1:$${BACKEND_PORT:-5000}/health >/dev/null; then break; fi; \
		if [ "$$attempt" = "30" ]; then $(COMPOSE) ps; $(COMPOSE) logs --tail=200; exit 1; fi; \
		sleep 2; \
	done; \
	curl --fail --silent http://127.0.0.1:$${BACKEND_PORT:-5000}/health; \
	curl --fail --silent --show-error \
		-H 'Content-Type: application/json' \
		-d '{"chunk":0}' \
		http://127.0.0.1:$${BACKEND_PORT:-5000}/api/security/watermark/demo >/dev/null; \
	for attempt in $$(seq 1 20); do \
		if curl --fail --silent http://127.0.0.1:$${FRONTEND_PORT:-8080}/ >/dev/null; then break; fi; \
		if [ "$$attempt" = "20" ]; then $(COMPOSE) ps; $(COMPOSE) logs --tail=200; exit 1; fi; \
		sleep 1; \
	done; \
	$(COMPOSE) ps

SHELL := /bin/bash

PYTHON ?= python3
NPM ?= npm
COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help install dev backend frontend build test docker-config docker-up docker-down docker-logs docker-smoke

help:
	@echo "CDN-Sentinel"
	@echo "  make install       instala dependências Python e frontend"
	@echo "  make dev           executa backend e frontend em terminais/processos locais"
	@echo "  make build         compila o frontend"
	@echo "  make test          roda compileall, unittest e build do frontend"
	@echo "  make docker-up     sobe o stack completo com Docker Compose"
	@echo "  make docker-smoke  sobe, testa health/API/frontend e encerra os containers"
	@echo "  make docker-down   encerra o stack Docker"

install:
	$(PYTHON) -m pip install -r requirements.txt
	cd frontend && $(NPM) ci

dev:
	@trap 'kill 0' INT TERM EXIT; \
	$(PYTHON) app.py & \
	(cd frontend && $(NPM) run dev -- --host 0.0.0.0) & \
	wait

backend:
	$(PYTHON) app.py

frontend:
	cd frontend && $(NPM) run dev -- --host 0.0.0.0

build:
	cd frontend && $(NPM) run build

test:
	$(PYTHON) -m compileall -q app.py client_app.py node_app.py controllers models repositories routes services tests utils
	$(PYTHON) -m unittest discover -s tests -v
	$(MAKE) build

docker-config:
	$(COMPOSE) config --quiet

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
	curl --fail --silent http://127.0.0.1:$${FRONTEND_PORT:-8080}/ >/dev/null; \
	$(COMPOSE) ps

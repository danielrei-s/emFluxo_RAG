SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

.PHONY: help setup setup-full lint test test-integration test-e2e eval eval-live \
	security licenses openapi fixtures migrate up down hooks

help: ## Lista os alvos disponíveis
	@grep -E '^[a-z][a-z0-9-]*:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "} {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Instala as dependências Python e JS (perfil base)
	uv sync --all-packages
	pnpm install

setup-full: ## Instala também todos os extras opcionais do core
	uv sync --all-packages --all-extras
	pnpm install

lint: ## ruff, mypy e lint JS/TS
	uv run ruff check .
	uv run mypy packages/core
	pnpm -r lint
	pnpm -r typecheck

test: ## Testes unitários (sem rede) Python e JS
	uv run pytest
	pnpm -r test

test-integration: ## Testes com Postgres (testcontainers)
	@echo "ainda não implementado (F7-T01)"

test-e2e: ## Testes end-to-end (Playwright)
	@echo "ainda não implementado (F10-T01)"

eval: ## Avaliação com fakes
	@echo "ainda não implementado (F5-T04)"

eval-live: ## Avaliação com modelos reais
	@echo "ainda não implementado (F5-T05)"

security: ## Deteção de segredos e análise estática de segurança
	@echo "ainda não implementado (F0-T09)"

licenses: ## Verificação de licenças por perfil (server e dev; shipped em F11-T12)
	uv run python scripts/check_licenses.py --profile server --profile dev

openapi: ## Gera o OpenAPI e o cliente TypeScript
	@echo "ainda não implementado (F8-T01)"

fixtures: ## Gera o corpus sintético
	@echo "ainda não implementado (F2-T01)"

migrate: ## Aplica as migrações da BD central
	@echo "ainda não implementado (F7-T01)"

up: ## Arranca o compose de desenvolvimento
	@echo "ainda não implementado (F0-T11)"

down: ## Pára o compose de desenvolvimento
	@echo "ainda não implementado (F0-T11)"

hooks: ## Instala os hooks de pre-commit
	@echo "ainda não implementado (F0-T09)"

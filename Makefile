SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE_DEV := infra/compose/docker-compose.dev.yml

.PHONY: help setup setup-full lint test test-integration test-e2e eval eval-live bench \
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
	uv run mypy packages/core packages/cli
	pnpm -r lint
	pnpm -r typecheck

test: ## Testes unitários (sem rede) Python e JS
	uv run pytest
	pnpm -r test

test-integration: ## Testes com Postgres (testcontainers)
	@echo "ainda não implementado (F7-T01)"

test-e2e: ## Testes end-to-end (Playwright)
	@echo "ainda não implementado (F10-T01)"

eval: ## Avaliação com fakes (compara com a baseline; falha se houver regressões)
	uv run rag eval --fake-models --golden evals/golden --report out/eval --baseline evals/baseline.fake.json

eval-live: ## Avaliação com modelos reais (precisa de models.yaml e do servidor de modelos)
	uv run rag eval --golden evals/golden --report out/eval-live

bench: ## Benchmark de modelos reais (F5-T05; precisa da Máquina 1)
	uv run python evals/bench/run_bench.py --out evals/bench/results-latest.md

security: ## Segredos no histórico git (gitleaks); semgrep e audits correm no CI
	uv run pre-commit run gitleaks-history --all-files --hook-stage manual

licenses: ## Verificação de licenças por perfil (server e dev; shipped em F11-T12)
	uv run python scripts/check_licenses.py --profile server --profile dev

openapi: ## Gera o OpenAPI e o cliente TypeScript
	@echo "ainda não implementado (F8-T01)"

fixtures: ## Gera o corpus sintético
	uv run python scripts/make_fixtures.py

migrate: ## Aplica as migrações da BD central
	@echo "ainda não implementado (F7-T01)"

up: ## Arranca o compose de desenvolvimento (postgres; perfis com COMPOSE_PROFILES)
	docker compose -f $(COMPOSE_DEV) up -d --wait

down: ## Pára o compose de desenvolvimento
	docker compose -f $(COMPOSE_DEV) down

hooks: ## Instala os hooks de pre-commit
	uv run pre-commit install

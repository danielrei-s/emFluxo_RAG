# ADR-0001 · Monorepo e stack

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

A plataforma tem dois produtos (portal web e app desktop) que partilham o mesmo core RAG, a mesma
identidade e o mesmo gateway de modelos. O desenvolvimento é feito por agentes com pouco contexto,
uma tarefa de cada vez, pelo que contratos e testes têm de ser partilhados e fáceis de encontrar.
O MVP corre em infraestrutura gratuita, mas tem de ter o nível de segurança do produto final.

## Decisão

Um único repositório (monorepo) com a estrutura da C3: `packages/` (core, cli, ui, web-common,
api-client), `services/` (gateway, central-api, parser-sandbox), `apps/` (web, backoffice,
local-engine, desktop), `modules/`, `evals/`, `fixtures/`, `infra/`, `scripts/` e `docs/`.

Stack: Python 3.12 com uv (workspace) e FastAPI; pydantic v2; httpx; structlog; psycopg 3;
pytest, ruff e mypy strict. Node 24 LTS com pnpm; Next.js (App Router), React, TypeScript strict,
Tailwind e shadcn/ui, Vitest e Playwright. Rust estável com Tauri v2 para a app desktop.
Postgres 17 com pgvector; SQLCipher 4 no dispositivo; Ollama para modelos locais.

## Alternativas consideradas

- **Vários repositórios** — dificulta alterar contratos do core e os testes que atravessam
  produtos; cada tarefa exigiria coordenar PRs entre repositórios.
- **Electron em vez de Tauri** — instalador e consumo de memória maiores; o Tauri permite
  capacidades mínimas por omissão.
- **Poetry/pip em vez de uv** — workspace e lockfile únicos são mais simples com uv.
- **Gestor JS npm/yarn** — pnpm dá workspaces estritos e instalações reproduzíveis.

## Consequências

- Uma só CI e um só `make lint test` validam tudo; o gate de invariantes (INV-xx) é global.
- O repositório cresce e a CI tem de ser seletiva (matriz multi-SO só quando muda o motor local
  ou o desktop, e à noite).
- Cada pacote Python novo entra nos membros do workspace uv e cada pacote JS no
  `pnpm-workspace.yaml`.
- O core (`rag_core`) nunca depende de apps ou serviços (INV-20).

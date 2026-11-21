#!/usr/bin/env bash
# Espera pelo healthcheck do postgres do compose de desenvolvimento e ativa o pgvector.
set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/../infra/compose/docker-compose.dev.yml"
COMPOSE=(docker compose -f "$COMPOSE_FILE")
TIMEOUT_S="${COMPOSE_SMOKE_TIMEOUT_S:-90}"

container_id="$("${COMPOSE[@]}" ps -q postgres)"
if [ -z "$container_id" ]; then
  echo "postgres não está a correr; corre 'make up' primeiro" >&2
  exit 1
fi

deadline=$((SECONDS + TIMEOUT_S))
until [ "$(docker inspect -f '{{.State.Health.Status}}' "$container_id")" = "healthy" ]; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "timeout à espera de postgres healthy (${TIMEOUT_S}s)" >&2
    exit 1
  fi
  sleep 1
done

"${COMPOSE[@]}" exec -T postgres psql -U rag -d rag -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS vector"
version="$("${COMPOSE[@]}" exec -T postgres psql -U rag -d rag -Atc \
  "SELECT extversion FROM pg_extension WHERE extname = 'vector'")"
echo "OK: postgres healthy, pgvector ${version}"

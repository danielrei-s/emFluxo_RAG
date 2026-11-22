# Central API (F8-T01). Contexto de construção: a raiz do repositório.
#   docker build -f services/central-api/Dockerfile -t rag-central-api .
FROM python:3.12-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.4
WORKDIR /app
# O workspace uv precisa de todos os membros presentes; o resto do repo fica de fora.
COPY pyproject.toml uv.lock ./
COPY packages/core packages/core
COPY packages/cli packages/cli
COPY services/central-api services/central-api
COPY services/gateway services/gateway
RUN uv sync --frozen --no-dev --no-editable --package rag-central-api

FROM python:3.12-slim
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /app/.venv /app/.venv
USER 10001
EXPOSE 8080
# Sem curl na imagem: a verificação usa o Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"]
# Compatível com sistema de ficheiros só de leitura (`docker run --read-only`): nada escreve em disco.
CMD ["uvicorn", "rag_central.main:app", "--host", "0.0.0.0", "--port", "8080"]

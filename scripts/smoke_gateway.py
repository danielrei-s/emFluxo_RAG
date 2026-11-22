"""Smoke do gateway em staging (F6-T07).

    python scripts/smoke_gateway.py --url https://gw.example.org --token-file token.txt

O token fica num ficheiro (nunca na linha de comandos nem no histórico do shell). O script só
imprime códigos e cabeçalhos; nunca o texto da resposta nem o token.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

PROMPT = {"messages": [{"role": "user", "content": "Responde apenas: ok"}], "max_tokens": 16}


def run_smoke(client: httpx.Client, token: str | None) -> list[str]:
    """Devolve a lista de falhas (vazia = tudo bem)."""
    failures: list[str] = []
    health = client.get("/healthz")
    if health.status_code != 200:
        failures.append(f"healthz: {health.status_code}")
    ready = client.get("/readyz")
    if ready.status_code != 200:
        failures.append(f"readyz: {ready.status_code}")
    anonymous = client.post("/v1/chat/completions", json=PROMPT)
    if anonymous.status_code != 401:
        failures.append(f"sem token devia dar 401, deu {anonymous.status_code}")
    if token is None:
        return failures
    headers = {"Authorization": f"Bearer {token}"}
    chat = client.post("/v1/chat/completions", json=PROMPT, headers=headers)
    if chat.status_code != 200:
        failures.append(f"chat: {chat.status_code}")
    elif not chat.headers.get("x-model-alias") or not chat.json().get("choices"):
        failures.append("chat: resposta sem alias ou sem choices")
    with client.stream(
        "POST", "/v1/chat/completions", json={**PROMPT, "stream": True}, headers=headers
    ) as stream:
        body = "".join(stream.iter_text())
    if stream.status_code != 200 or "data: [DONE]" not in body:
        failures.append(f"stream: {stream.status_code} sem [DONE]")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="URL base do gateway (https://gw.<domínio>)")
    parser.add_argument("--token-file", type=Path, help="ficheiro com um token de staging")
    args = parser.parse_args(argv)
    token = args.token_file.read_text(encoding="utf-8").strip() if args.token_file else None
    with httpx.Client(base_url=args.url, timeout=60.0) as client:
        failures = run_smoke(client, token)
    for failure in failures:
        print(f"FALHA: {failure}", file=sys.stderr)
    print("smoke OK" if not failures else f"smoke com {len(failures)} falha(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

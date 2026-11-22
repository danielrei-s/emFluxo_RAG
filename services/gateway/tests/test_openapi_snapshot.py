"""Testes de F6-T01: o ``openapi.json`` commitado coincide com o gerado (``make openapi``)."""

from __future__ import annotations

from rag_gateway.export_openapi import OPENAPI_PATH, build_openapi, render


def test_openapi_snapshot_matches() -> None:
    committed = OPENAPI_PATH.read_text(encoding="utf-8")
    assert committed == render(build_openapi()), (
        "o openapi.json mudou: corre `make openapi` e faz commit do resultado"
    )


def test_openapi_lists_only_the_ops_endpoints_for_now() -> None:
    schema = build_openapi()
    assert sorted(schema["paths"]) == ["/healthz", "/readyz"]
    assert schema["info"]["title"] == "RAG Inference Gateway"

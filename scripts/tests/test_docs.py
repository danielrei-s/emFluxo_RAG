"""Testes de F0-T12: ADRs iniciais, modelo de ameaças e documentação por produto."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "docs" / "adr"
INITIAL_ADRS = (
    "0001-monorepo-e-stack.md",
    "0002-supabase-mvp-atras-de-interfaces.md",
    "0003-vector-stores.md",
    "0004-llm-openai-compativel-e-ollama.md",
    "0005-autenticacao.md",
    "0006-perfis-de-parsing.md",
    "0007-politica-de-licencas.md",
    "0008-python-sincrono.md",
)
SECTIONS = ("## Contexto", "## Decisão", "## Alternativas consideradas", "## Consequências")


def test_adr_template_exists_with_all_sections() -> None:
    text = (ADR_DIR / "0000-template.md").read_text(encoding="utf-8")
    assert text.startswith("# ADR-NNNN · ")
    for section in SECTIONS:
        assert section in text
    assert "**Estado:**" in text


@pytest.mark.parametrize("name", INITIAL_ADRS)
def test_each_adr_has_required_sections(name: str) -> None:
    text = (ADR_DIR / name).read_text(encoding="utf-8")
    number = name[:4]
    assert re.match(rf"# ADR-{number} · \S", text), "título no formato ADR-NNNN · Título"
    assert "- **Estado:** aceite" in text
    assert re.search(r"\*\*Data:\*\* \d{4}-\d{2}-\d{2} · \*\*Tarefa:\*\* F\d+-T\d+", text)
    positions = [text.find(section) for section in SECTIONS]
    assert all(p >= 0 for p in positions), f"secções em falta: {positions}"
    assert positions == sorted(positions), "secções fora de ordem"
    for section in SECTIONS:
        body = text.split(section, 1)[1].split("\n## ", 1)[0]
        assert len(body.strip()) > 40, f"{section} está vazia"


def test_all_initial_adrs_exist_and_no_unexpected_gaps() -> None:
    numbers = sorted(p.name[:4] for p in ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert numbers[0] == "0000"
    assert {n[:4] for n in INITIAL_ADRS} <= set(numbers)


@pytest.mark.parametrize("product", ["product-web", "product-local"])
def test_product_docs_contain_sources_table(product: str) -> None:
    text = (ROOT / "docs" / product / "README.md").read_text(encoding="utf-8")
    assert "| Fonte de conhecimento | Produto A (Web) | Produto B (Local) |" in text
    assert "| Conhecimento geral do LLM | ✔ | ✔ |" in text
    assert "| Base documental da empresa (central) | ✔ | ✔ |" in text
    assert "| Documentos próprios da pasta autorizada | ✖ | ✔ |" in text
    assert "## O que não faz" in text


def test_threat_model_covers_stride_table_and_extra_threats() -> None:
    text = (ROOT / "docs" / "threat-model.md").read_text(encoding="utf-8")
    for threat in (
        "Fuga entre tenants",
        "Fuga dentro do tenant",
        "Prompt injection indireta",
        "Exfiltração via resposta",
        "Envenenamento do índice",
        "Ataque ao parser",
        "Roubo do dispositivo (B)",
        "Abuso do motor local",
        "Abuso de custos",
        "Retenção no fornecedor",
        "Supply chain",
    ):
        assert threat in text, threat
    for extra in ("Cloudflare", "Vercel", "Langfuse", "portátil"):
        assert extra in text, extra

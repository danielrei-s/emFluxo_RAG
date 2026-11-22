"""Testes de F3-T03: parsers TXT, MD e CSV, e utilitários de ``parsing.base``."""

from __future__ import annotations

import pytest
from rag_core.errors import UnsupportedType
from rag_core.interfaces import ParseLimits, Parser
from rag_core.parsing.base import PARSER_VERSION, markdown_table, split_paragraphs
from rag_core.parsing.text import TextParser
from rag_core.testing import corpus
from rag_core.types import DetectedType

LIMITS = ParseLimits()
PARSER = TextParser()


def _parse(data: bytes, detected: DetectedType, name: str = "f"):  # type: ignore[no-untyped-def]
    return PARSER.parse(data, filename=name, detected=detected, limits=LIMITS)


def test_parser_protocol_and_metadata() -> None:
    assert isinstance(PARSER, Parser)
    assert PARSER.supported == {DetectedType.TXT, DetectedType.MD, DetectedType.CSV}
    assert PARSER_VERSION == "lite-1"
    doc = _parse(b"ola", DetectedType.TXT)
    assert (doc.parser_name, doc.parser_version) == (PARSER.name, PARSER_VERSION)


def test_markdown_table_and_split_paragraphs() -> None:
    assert markdown_table([("a", "b"), ("1", "x|y"), ("2", "l1\nl2")]) == (
        "| a | b |\n| --- | --- |\n| 1 | x\\|y |\n| 2 | l1 l2 |"
    )
    assert markdown_table([]) == ""
    assert split_paragraphs("um\ndois\n\n\n  \ntres\n") == ["um dois", "tres"]
    assert split_paragraphs("") == []


def test_txt_paragraphs() -> None:
    doc = _parse(corpus.read_bytes("A11"), DetectedType.TXT, "faq_rgpd.txt")
    texts = [b.text for b in doc.blocks]
    assert all(b.kind == "paragraph" for b in doc.blocks)
    assert texts[0] == "FAQ RGPD"
    assert any("Rita Fernandes (dpo@aurora.example)" in t for t in texts)
    assert doc.page_count is None


def test_txt_decodes_cp1252_and_bom() -> None:
    assert _parse("café".encode("cp1252"), DetectedType.TXT).blocks[0].text == "café"
    assert _parse(b"\xef\xbb\xbfola", DetectedType.TXT).blocks[0].text == "ola"


def test_md_headings_levels_and_tables() -> None:
    doc = _parse(corpus.read_bytes("A05"), DetectedType.MD, "procedimento_faturacao.md")
    assert doc.title == "Procedimento de Faturação"
    assert doc.blocks[0].kind == "heading"
    assert doc.blocks[0].level == 1
    items = [b for b in doc.blocks if b.kind == "list_item"]
    assert len(items) == 4
    assert "software de faturação FaturaFácil" in items[0].text

    md = (
        "# Título\n\n## Secção\nlinha um\nlinha dois\n\n###### Fundo\n\n"
        "| Cargo | Preço |\n| --- | ---: |\n| A | 1 |\n| B | 2 |\n\n"
        "1. primeiro\n* segundo\n"
    )
    blocks = _parse(md.encode(), DetectedType.MD).blocks
    assert [(b.kind, b.level) for b in blocks] == [
        ("heading", 1),
        ("heading", 2),
        ("paragraph", None),
        ("heading", 6),
        ("table", None),
        ("list_item", None),
        ("list_item", None),
    ]
    assert blocks[2].text == "linha um linha dois"
    table = blocks[4]
    assert table.rows == (("Cargo", "Preço"), ("A", "1"), ("B", "2"))
    assert table.text == markdown_table(table.rows or ())
    assert [blocks[5].text, blocks[6].text] == ["primeiro", "segundo"]


def test_csv_semicolon_delimiter() -> None:
    doc = _parse(corpus.read_bytes("A13"), DetectedType.CSV, "contactos_fornecedores.csv")
    (block,) = doc.blocks
    assert block.kind == "table"
    assert block.rows == (
        ("fornecedor", "telefone", "iban"),
        ("Papelaria Norte", "+351 22 123 4567", "PT50 0002 0123 1234 5678 9015 4"),
    )


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_csv_sniffs_delimiters(delimiter: str) -> None:
    raw = delimiter.join(["a", "b"]) + "\n" + delimiter.join(["1", "2"]) + "\n"
    (block,) = _parse(raw.encode(), DetectedType.CSV).blocks
    assert block.rows == (("a", "b"), ("1", "2"))


def test_csv_splits_into_blocks_repeating_header() -> None:
    lines = ["id;valor", *[f"{i};{i * 2}" for i in range(120)]]
    blocks = _parse("\n".join(lines).encode(), DetectedType.CSV).blocks
    assert [len(b.rows or ()) for b in blocks] == [51, 51, 21]
    assert all(b.rows is not None and b.rows[0] == ("id", "valor") for b in blocks)
    assert blocks[1].rows is not None
    assert blocks[1].rows[1] == ("50", "100")


def test_csv_edge_cases() -> None:
    assert _parse(b"", DetectedType.CSV).blocks == ()
    assert _parse(b"\n\n", DetectedType.CSV).blocks == ()
    (block,) = _parse(b"so um valor\n", DetectedType.CSV).blocks  # Sniffer falha: usa vírgula
    assert block.rows == (("so um valor",),)


def test_wrong_type_is_rejected() -> None:
    with pytest.raises(UnsupportedType):
        _parse(b"%PDF-", DetectedType.PDF)


def test_md_paragraph_directly_followed_by_table() -> None:
    blocks = _parse(b"texto antes\n| a | b |\n| 1 | 2 |\n", DetectedType.MD).blocks
    assert [b.kind for b in blocks] == ["paragraph", "table"]

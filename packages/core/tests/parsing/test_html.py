"""Testes de F3-T03: parser HTML (remove conteúdo oculto e executável)."""

from __future__ import annotations

from rag_core.interfaces import ParseLimits, Parser
from rag_core.parsing.html import HtmlParser
from rag_core.testing import corpus
from rag_core.types import Block, DetectedType, StructuredDocument

PARSER = HtmlParser()


def _parse(html: str) -> StructuredDocument:
    return PARSER.parse(
        html.encode(), filename="f.html", detected=DetectedType.HTML, limits=ParseLimits()
    )


def _texts(blocks: tuple[Block, ...]) -> str:
    return "\n".join(b.text for b in blocks)


def test_html_removes_scripts_and_hidden() -> None:
    data = corpus.read_bytes("A12")
    doc = PARSER.parse(data, filename="r.html", detected=DetectedType.HTML, limits=ParseLimits())
    text = _texts(doc.blocks)
    assert "HIDDEN-HTML-3310" not in text
    assert "INSTRUÇÃO OCULTA" not in text
    assert "hidden_instruction" not in text
    assert "o estacionamento tem 20 lugares, atribuídos por ordem de chegada" in text
    assert doc.title == "Regulamento Interno"
    assert "hidden_text_removed" in doc.warnings
    assert any("hidden_text_removed" in b.flags for b in doc.blocks)
    assert isinstance(PARSER, Parser)


def test_hidden_variants_are_removed_and_flag_the_next_block() -> None:
    doc = _parse(
        "<body><p>antes</p>"
        '<p hidden>H1</p><p aria-hidden="true">H2</p>'
        '<span style="color:red; Display : None">H3</span>'
        '<div style="visibility:hidden">H4</div>'
        "<p>depois</p><p>fim</p></body>"
    )
    assert [b.text for b in doc.blocks] == ["antes", "depois", "fim"]
    assert [bool(b.flags) for b in doc.blocks] == [False, True, False]
    assert doc.blocks[1].flags == {"hidden_text_removed"}
    assert doc.warnings == ("hidden_text_removed",)


def test_non_executable_and_embedded_content_is_dropped() -> None:
    doc = _parse(
        "<body><style>p{}</style><noscript>NS</noscript><template>T</template>"
        "<iframe>IF</iframe><script>alert(1)</script><p>visível</p></body>"
    )
    assert [b.text for b in doc.blocks] == ["visível"]
    assert doc.warnings == ()


def test_structure_headings_lists_tables_and_inline() -> None:
    doc = _parse(
        "<html><head><title>T</title></head><body>"
        "<h1>Um</h1><h3>Três</h3><p>texto <b>forte</b> e <a href='x'>link</a><br>fim</p>"
        "<ul><li>item a</li><li>item b</li></ul>"
        "<div>solto <span>inline</span></div>"
        "<table><tr><th>Nome</th><th>Preço</th></tr><tr><td>A</td><td>1 €</td></tr>"
        "<tr><td></td><td></td></tr></table>"
        "</body></html>"
    )
    kinds = [(b.kind, b.level, b.text) for b in doc.blocks[:6]]
    assert kinds == [
        ("heading", 1, "Um"),
        ("heading", 3, "Três"),
        ("paragraph", None, "texto forte e link fim"),
        ("list_item", None, "item a"),
        ("list_item", None, "item b"),
        ("paragraph", None, "solto inline"),
    ]
    table = doc.blocks[6]
    assert table.kind == "table"
    assert table.rows == (("Nome", "Preço"), ("A", "1 €"))
    assert doc.title == "T"


def test_title_falls_back_to_first_h1_and_empty_html() -> None:
    assert _parse("<h1>Cabeçalho</h1><p>x</p>").title == "Cabeçalho"
    empty = _parse("")
    assert empty.blocks == ()
    assert empty.title is None


def test_nested_hidden_and_dropped_inside_blocks() -> None:
    doc = _parse("<body><p>a <span hidden>X</span><script>s()</script> b</p><p></p><p>c</p></body>")
    assert [b.text for b in doc.blocks] == ["a b", "c"]
    assert doc.blocks[0].flags == {"hidden_text_removed"}


def test_strip_hidden_html_handles_nested_hidden_and_reports_it() -> None:
    from rag_core.parsing.html import strip_hidden_html

    data, hidden = strip_hidden_html(
        b"<div hidden><p hidden>x</p><script>s()</script></div><script>y()</script><p>ok</p>"
    )
    assert hidden is True
    assert data == b"<p>ok</p>"
    only_script, hidden2 = strip_hidden_html(b"<p>a</p><script>s()</script>")
    assert (only_script, hidden2) == (b"<p>a</p>", False)
    same = b"<p>limpo</p>"
    assert strip_hidden_html(same) == (same, False)

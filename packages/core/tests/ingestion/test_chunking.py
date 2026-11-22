"""Testes de F3-T11: chunker estrutural."""

from __future__ import annotations

import itertools
import re
from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st
from rag_core.config import ChunkingSettings
from rag_core.ingestion.chunking import ChunkDraft, chunk_document, embedding_text
from rag_core.parsing.base import markdown_table
from rag_core.tokens import ApproxTokenCounter
from rag_core.types import Block, DetectedType, StructuredDocument

COUNTER = ApproxTokenCounter()
SMALL = ChunkingSettings(target_tokens=20, min_tokens=8, max_tokens=40, overlap_ratio=0.3)
NO_OVERLAP = ChunkingSettings(target_tokens=20, min_tokens=8, max_tokens=40, overlap_ratio=0.0)
DEFAULT = ChunkingSettings()


def _doc(*blocks: Block) -> StructuredDocument:
    return StructuredDocument(
        detected_type=DetectedType.TXT, blocks=blocks, parser_name="t", parser_version="1"
    )


def _p(text: str, page: int | None = None, flags: frozenset[str] = frozenset()) -> Block:
    return Block(kind="paragraph", text=text, page=page, flags=flags)


def _h(text: str, level: int = 1) -> Block:
    return Block(kind="heading", text=text, level=level)


def _li(text: str) -> Block:
    return Block(kind="list_item", text=text)


def _table(rows: list[list[str]], page: int | None = None) -> Block:
    tuples = tuple(tuple(r) for r in rows)
    return Block(kind="table", text=markdown_table(tuples), rows=tuples, page=page)


def _chunk(doc: StructuredDocument, cfg: ChunkingSettings = SMALL) -> list[ChunkDraft]:
    return chunk_document(doc, settings=cfg, counter=COUNTER)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


# --------------------------------------------------------------- propriedades (Hypothesis)

WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyzáãçé0123456789", min_size=1, max_size=12)
SENTENCE = st.lists(WORD, min_size=1, max_size=15).map(lambda w: " ".join(w) + ".")
TEXT = st.lists(SENTENCE, min_size=1, max_size=12).map(" ".join)
CELL = st.text(alphabet="abcdef0123456789 ", min_size=1, max_size=12).map(str.strip).filter(bool)
TABLE_ROWS = st.integers(1, 4).flatmap(
    lambda cols: st.lists(st.lists(CELL, min_size=cols, max_size=cols), min_size=2, max_size=14)
)

BLOCKS = st.one_of(
    st.builds(lambda t, lv: _h(t, lv), WORD, st.integers(1, 4)),
    st.builds(_p, TEXT, st.one_of(st.none(), st.integers(1, 9))),
    st.builds(_li, SENTENCE),
    st.builds(_table, TABLE_ROWS, st.one_of(st.none(), st.integers(1, 9))),
)
DOCS = st.lists(BLOCKS, max_size=14).map(lambda bs: _doc(*bs))


@settings(max_examples=150, deadline=None)
@given(DOCS, st.sampled_from([SMALL, NO_OVERLAP, DEFAULT]))
def test_chunks_never_exceed_max_tokens(doc: StructuredDocument, cfg: ChunkingSettings) -> None:
    for draft in _chunk(doc, cfg):
        assert COUNTER.count(draft.text) <= cfg.max_tokens
        assert draft.text.strip()


@settings(max_examples=150, deadline=None)
@given(DOCS, st.sampled_from([SMALL, NO_OVERLAP]))
def test_no_text_lost(doc: StructuredDocument, cfg: ChunkingSettings) -> None:
    drafts = _chunk(doc, cfg)
    expected = Counter(_squash("".join(b.text for b in doc.blocks if b.kind != "heading")))
    found = Counter(_squash("".join(d.text for d in drafts)))
    assert not expected - found  # nenhum carácter se perdeu (a sobreposição só acrescenta)


@settings(max_examples=150, deadline=None)
@given(DOCS)
def test_without_overlap_chunks_reassemble_the_document(doc: StructuredDocument) -> None:
    drafts = _chunk(doc, NO_OVERLAP)
    big_tables = [
        b for b in doc.blocks if b.kind == "table" and COUNTER.count(b.text) > NO_OVERLAP.max_tokens
    ]
    if big_tables:  # o cabeçalho repete-se em cada parte: só se verifica a cobertura
        return
    text = "".join(b.text for b in doc.blocks if b.kind != "heading")
    assert _squash("".join(d.text for d in drafts)) == _squash(text)


@settings(max_examples=60, deadline=None)
@given(DOCS)
def test_ordinals_increasing_and_deterministic(doc: StructuredDocument) -> None:
    first = _chunk(doc)
    assert [d.ordinal for d in first] == list(range(len(first)))
    assert first == _chunk(doc)


# ----------------------------------------------------------------------- exemplos


def test_heading_path_nested() -> None:
    long = " ".join(f"palavra{i}" for i in range(12)) + "."
    doc = _doc(
        _h("Manual"),
        _h("Férias", 2),
        _p(long),
        _h("Regras", 3),
        _p(long),
        _h("Teletrabalho", 2),
        _p(long),
        _h("Anexo"),
        _p(long),
    )
    paths = [d.heading_path for d in _chunk(doc)]
    assert paths == [
        ("Manual", "Férias"),
        ("Manual", "Férias", "Regras"),
        ("Manual", "Teletrabalho"),
        ("Anexo",),
    ]


def test_small_sections_are_merged_until_min_tokens() -> None:
    doc = _doc(_h("A"), _p("curto um."), _h("B"), _p("curto dois."), _h("C"), _p("fim."))
    drafts = _chunk(doc)
    assert len(drafts) == 1
    assert drafts[0].heading_path == ("A",)
    assert drafts[0].text == "curto um.\n\ncurto dois.\n\nfim."


def test_list_items_are_kept_on_consecutive_lines() -> None:
    doc = _doc(_p("intro"), _li("um"), _li("dois"), _p("fim"))
    assert _chunk(doc, DEFAULT)[0].text == "intro\n\num\ndois\n\nfim"


def test_table_kept_whole_when_small() -> None:
    table = _table([["Artigo", "Preço"], ["Agrafador", "12,50 €"]], page=2)
    doc = _doc(_h("Preços"), _p("texto antes."), table, _p("texto depois."))
    drafts = _chunk(doc, DEFAULT)
    assert [d.text for d in drafts] == ["texto antes.", table.text, "texto depois."]
    assert drafts[1].heading_path == ("Preços",)
    assert (drafts[1].page_start, drafts[1].page_end) == (2, 2)


def test_big_table_split_with_header_repeated() -> None:
    rows = [["id", "valor"], *[[str(i), str(i * 1000)] for i in range(40)]]
    drafts = _chunk(_doc(_table(rows)))
    assert len(drafts) > 2
    for draft in drafts:
        lines = draft.text.split("\n")
        assert lines[0] == "| id | valor |"
        assert lines[1] == "| --- | --- |"
        assert COUNTER.count(draft.text) <= SMALL.max_tokens
    body_lines = [ln for d in drafts for ln in d.text.split("\n")[2:]]
    assert body_lines == [f"| {i} | {i * 1000} |" for i in range(40)]


def test_huge_table_row_is_cut_by_characters() -> None:
    rows = [["a", "b"], ["x" * 400, "y"]]
    drafts = _chunk(_doc(_table(rows)))
    assert all(COUNTER.count(d.text) <= SMALL.max_tokens for d in drafts)
    assert "x" * 100 in drafts[1].text


def test_table_without_rows_is_treated_as_text() -> None:
    block = Block(kind="table", text="| a |\n| --- |\n| 1 |")
    assert _chunk(_doc(block))[0].text == block.text
    big = Block(kind="table", text=" ".join(["palavra"] * 80) + ".")
    assert all(COUNTER.count(d.text) <= SMALL.max_tokens for d in _chunk(_doc(big)))


def test_overlap_between_split_chunks_of_same_section() -> None:
    cfg = ChunkingSettings(target_tokens=30, min_tokens=8, max_tokens=60, overlap_ratio=0.3)
    sentences = [f"Frase {n} do texto." for n in range(30)]  # ~5 tokens cada
    doc = _doc(_h("Secção"), _p(" ".join(sentences)))
    drafts = _chunk(doc, cfg)
    assert len(drafts) >= 3
    budget = int(cfg.overlap_ratio * cfg.target_tokens)
    for previous, current in itertools.pairwise(drafts):
        last_sentence = previous.text.split(". ")[-1]
        assert current.text.startswith(last_sentence), (previous.text, current.text)
        carried = [s for s in sentences if s in previous.text and current.text.startswith(s)]
        assert carried
        assert COUNTER.count(" ".join(carried)) <= budget
        assert COUNTER.count(current.text) <= cfg.max_tokens
    # sem sobreposição, as partes não repetem texto
    no_overlap = ChunkingSettings(target_tokens=30, min_tokens=8, max_tokens=60, overlap_ratio=0.0)
    plain = _chunk(doc, no_overlap)
    assert _squash("".join(d.text for d in plain)) == _squash(" ".join(sentences))


def test_overlap_is_skipped_when_one_sentence_exceeds_the_budget() -> None:
    sentences = [f"Frase número {n} do texto longo desta secção." for n in range(12)]
    drafts = _chunk(_doc(_p(" ".join(sentences))))  # 11 tokens > orçamento de 6
    assert all(not b.text.startswith(a.text.split(". ")[-1]) for a, b in itertools.pairwise(drafts))


def test_no_overlap_across_headings_or_tables() -> None:
    long = " ".join(f"Frase {n} é aqui." for n in range(10))
    doc = _doc(_h("A"), _p(long), _h("B"), _p("Segunda secção começa limpa."))
    last = _chunk(doc)[-1]
    assert last.text == "Segunda secção começa limpa."


def test_long_paragraph_is_split_by_sentences_then_characters() -> None:
    sentence = "Uma frase normal e curta."
    monster = "z" * 500
    doc = _doc(_p(f"{sentence} {monster} {sentence}"))
    drafts = _chunk(doc, NO_OVERLAP)
    assert all(COUNTER.count(d.text) <= SMALL.max_tokens for d in drafts)
    assert drafts[0].text == sentence
    assert _squash("".join(d.text for d in drafts)) == _squash(f"{sentence}{monster}{sentence}")


def test_flags_propagate_and_pages_are_min_max() -> None:
    doc = _doc(
        _h("Título"),
        _p("um.", page=3, flags=frozenset({"hidden_text_removed"})),
        _p("dois.", page=5),
        _p("três.", page=None, flags=frozenset({"ocr"})),
    )
    (draft,) = _chunk(doc, DEFAULT)
    assert draft.flags == {"hidden_text_removed", "ocr"}
    assert (draft.page_start, draft.page_end) == (3, 5)
    nopage = _chunk(_doc(_p("sem páginas.")), DEFAULT)[0]
    assert (nopage.page_start, nopage.page_end) == (None, None)
    assert nopage.flags == frozenset()


def test_empty_and_heading_only_documents() -> None:
    assert _chunk(_doc()) == []
    assert _chunk(_doc(_h("Só título"), _p("   "), Block(kind="paragraph", text=""))) == []
    assert _chunk(_doc(Block(kind="heading", text="   "), _p("texto.")))[0].heading_path == ()


def test_embedding_text() -> None:
    draft = ChunkDraft(ordinal=0, text="O prazo é 30 dias.", heading_path=("Manual", "Prazos"))
    assert embedding_text(draft) == "Manual > Prazos\n\nO prazo é 30 dias."
    assert embedding_text(ChunkDraft(ordinal=0, text="solto")) == "solto"


def test_default_settings_fill_chunks_up_to_max_tokens() -> None:
    sentence = "Esta é uma frase de teste com vários termos. "
    doc = _doc(_p(sentence * 200))
    drafts = _chunk(doc, DEFAULT)
    assert len(drafts) > 2
    assert all(COUNTER.count(d.text) <= DEFAULT.max_tokens for d in drafts)
    assert all(COUNTER.count(d.text) >= DEFAULT.min_tokens for d in drafts[:-1])


class _WeightedCounter:
    """Letras acentuadas custam o triplo: a estimativa linear falha e obriga a encolher."""

    def count(self, text: str) -> int:
        return -(-sum(3 if ord(c) > 127 else 1 for c in text) // 4)


def test_hard_cut_shrinks_until_each_piece_fits() -> None:
    from rag_core.ingestion.chunking import _hard_cut

    text = "é" * 100 + "a" * 300
    pieces = _hard_cut(text, 40, _WeightedCounter())
    assert "".join(pieces) == text
    assert all(_WeightedCounter().count(p) <= 40 for p in pieces)


def test_huge_table_row_with_sentences_is_packed_by_sentences() -> None:
    cell = " ".join(f"Frase {n} da célula." for n in range(25))
    drafts = _chunk(_doc(_table([["a", "b"], [cell, "y"]])))
    assert len(drafts) > 2
    assert all(COUNTER.count(d.text) <= SMALL.max_tokens for d in drafts)
    assert _squash("".join(d.text for d in drafts)).count("Frase") >= 25


def test_overlap_is_dropped_when_it_would_not_fit_with_the_next_unit() -> None:
    first = "x" * 100 + "."  # 26 tokens
    short = "Ok."
    last = "y" * 156 + "."  # 40 tokens: com a sobreposição já não cabe
    drafts = _chunk(_doc(_p(f"{first} {short} {last}")), SMALL)
    assert [d.text for d in drafts] == [f"{first} {short}", last]

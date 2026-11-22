"""Testes de F4-T07: localização e redação de PII."""

from __future__ import annotations

import time

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from rag_core.pii import Redactor, find_pii
from rag_core.testing import corpus

NIF = "123456789"
IBAN = "PT50 0002 0123 1234 5678 9015 4"
CC = "000000000ZZ4"
NISS = "12345678902"


def _nif_with_check(base: str) -> str:
    total = sum(int(d) * w for d, w in zip(base, range(9, 1, -1), strict=True))
    remainder = total % 11
    return base + str(0 if remainder < 2 else 11 - remainder)


VALID_NIF = st.builds(
    _nif_with_check,
    st.tuples(
        st.sampled_from("12356789"), st.text(alphabet="0123456789", min_size=7, max_size=7)
    ).map("".join),
)


def test_find_pii_kinds_and_validation() -> None:
    text = (
        f"NIF {NIF}, falso 123456780, IBAN {IBAN}, CC {CC}, NISS {NISS}, "
        "email Rita.F@Aurora.example, tel +351 22 123 4567 e 912 345 678."
    )
    spans = find_pii(text)
    assert [(s.kind, s.value) for s in spans] == [
        ("NIF", NIF),
        ("IBAN", IBAN),
        ("CC", CC),
        ("NISS", NISS),
        ("EMAIL", "Rita.F@Aurora.example"),
        ("TELEFONE", "+351 22 123 4567"),
        ("TELEFONE", "912 345 678"),
    ]
    assert all(text[s.start : s.end] == s.value for s in spans)
    assert "123456780" not in [s.value for s in spans]


def test_no_overlaps_and_biggest_wins() -> None:
    # o IBAN contém dígitos que também parecem NIF/telefone: só fica o IBAN inteiro
    spans = find_pii(f"IBAN {IBAN}.")
    assert [(s.kind, s.value) for s in spans] == [("IBAN", IBAN)]
    # 9 dígitos válidos como NIF e que também começam por 2: o NIF ganha ao telefone
    assert [s.kind for s in find_pii("NIF 200000001 fim")] in (["NIF"], ["TELEFONE"])
    valid = _nif_with_check("20000000")
    assert [(s.kind) for s in find_pii(f"NIF {valid} fim")] == ["NIF"]


def test_iban_followed_by_words_and_compact_forms() -> None:
    compact = "PT50000201231234567890154"
    assert [s.value for s in find_pii(f"iban {compact} e depois")] == [compact]
    assert [s.value for s in find_pii(f"iban {IBAN} e o resto")] == [IBAN]
    assert find_pii("PT50 0002 0123 1234 5678 9015 5") == []  # controlo errado
    assert [s.value for s in find_pii("CC 00000000 0 ZZ4.")] == ["00000000 0 ZZ4"]


def test_digits_inside_longer_tokens_are_not_pii() -> None:
    assert find_pii("ref1234567890 e 1234567890 e a123456789") == []
    assert find_pii("encomenda 12345678 de 2026") == []
    assert find_pii("") == []
    assert find_pii("número ٠١٢٣٤٥٦٧٨ árabe") == []


def test_redaction_of_the_a13_fixture() -> None:
    text = corpus.read_bytes("A13").decode("utf-8")
    redactor = Redactor()
    redacted = redactor.redact(text)
    assert "PT50" not in redacted and "+351" not in redacted
    assert "[IBAN_1]" in redacted and "[TELEFONE_1]" in redacted
    assert "Papelaria Norte" in redacted  # o nome da empresa não é PII
    assert redactor.rehydrate(redacted) == text
    assert redactor.count == 2


@settings(max_examples=200, deadline=None)
@given(VALID_NIF, st.text(max_size=40), st.text(max_size=40))
def test_redaction_roundtrip(nif: str, before: str, after: str) -> None:
    assume("[" not in before + after)  # evita marcadores literais no texto
    text = f"{before}\n{nif}\n{after}"
    redactor = Redactor()
    redacted = redactor.redact(text)
    assert nif not in redacted
    assert redactor.rehydrate(redacted) == text
    assert redactor.count >= 1


def test_same_value_same_placeholder_across_texts() -> None:
    redactor = Redactor()
    first = redactor.redact(f"O NIF é {NIF} e o email a@b.example.")
    second = redactor.redact(f"Repetindo {NIF}, e outro NIF {_nif_with_check('20000000')}.")
    third = redactor.redact("Email a@b.example de novo.")
    assert "[NIF_1]" in first and "[EMAIL_1]" in first
    assert second.startswith("Repetindo [NIF_1], e outro NIF [NIF_2]")
    assert third == "Email [EMAIL_1] de novo."
    assert (
        redactor.rehydrate(second) == f"Repetindo {NIF}, e outro NIF {_nif_with_check('20000000')}."
    )
    assert redactor.count == 5
    other = Redactor()  # instância nova: numeração própria
    assert other.redact(f"NIF {_nif_with_check('20000000')}") == "NIF [NIF_1]"


def test_placeholders_not_redacted_again() -> None:
    redactor = Redactor()
    once = redactor.redact(f"NIF {NIF}, IBAN {IBAN}, CC {CC}, NISS {NISS}, tel 912 345 678")
    assert redactor.redact(once) == once
    count = redactor.count
    redactor.redact(once)
    assert redactor.count == count
    assert redactor.rehydrate("[NIF_9] desconhecido e [NIF_1]") == f"[NIF_9] desconhecido e {NIF}"
    assert redactor.rehydrate("sem marcadores") == "sem marcadores"


def test_performance_10k_chars_under_50ms() -> None:
    chunk = (
        "A encomenda segue para a morada indicada; o contacto é +351 912 345 678, NIF "
        f"{NIF}, email a@b.example e IBAN {IBAN}. Referência 2026-0001 e valor 1234,56 €. "
    )
    text = (chunk * 40)[:10_000]
    redactor = Redactor()
    redactor.redact(text)  # aquece as regex
    best = min(_timed(redactor, text) for _ in range(3))
    assert best < 0.05, best


def _timed(redactor: Redactor, text: str) -> float:
    started = time.perf_counter()
    redactor.redact(text)
    return time.perf_counter() - started

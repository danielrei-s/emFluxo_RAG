"""Testes de F4-T07: validadores de identificadores portugueses."""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st
from rag_core.pii.validators import valid_cc, valid_iban, valid_nif, valid_niss
from stdnum import iban as std_iban
from stdnum.pt import cc as std_cc
from stdnum.pt import nif as std_nif


def test_known_vectors() -> None:
    assert valid_nif("123456789")
    assert not valid_nif("123456780")
    assert valid_iban("PT50000201231234567890154")
    assert valid_iban("PT50 0002 0123 1234 5678 9015 4")
    assert not valid_iban("PT50000201231234567890155")
    assert valid_cc("000000000ZZ4")
    assert not valid_cc("000000000ZZ5")
    assert valid_niss("12345678902")
    assert not valid_niss("12345678903")


def test_format_rules() -> None:
    assert not valid_nif("12345678")  # curto
    assert not valid_nif("1234567890")  # comprido
    assert not valid_nif("12345678a")
    assert not valid_nif("٠٢٣٤٥٦٧٨٩")  # dígitos não ASCII
    assert not valid_nif("423456780")  # 1.º dígito 4 não é usado
    assert not valid_niss("32345678901")  # tem de começar por 1 ou 2
    assert not valid_niss("1234567890")
    assert not valid_cc("00000000ZZ4")  # 11 caracteres
    assert not valid_cc("0000000000ZZ")  # termina em letra
    assert valid_cc("000000000zz4")  # minúsculas aceites
    assert not valid_iban("PT50")
    assert not valid_iban("1234567890123456")
    assert not valid_iban("PT50" + "0" * 40)  # demasiado comprido


@given(st.text(alphabet=string.digits, min_size=9, max_size=9))
def test_validators_agree_with_stdnum_nif(number: str) -> None:
    if number[0] == "4":  # o stdnum aceita; a regra do plano exclui o prefixo 4
        assert not valid_nif(number)
    else:
        assert valid_nif(number) == std_nif.is_valid(number)


@given(
    st.text(alphabet=string.digits, min_size=9, max_size=9),
    st.text(alphabet=string.digits + string.ascii_uppercase, min_size=2, max_size=2),
    st.text(alphabet=string.digits, min_size=1, max_size=1),
)
def test_validators_agree_with_stdnum_cc(digits: str, letters: str, check: str) -> None:
    number = digits + letters + check
    assert valid_cc(number) == std_cc.is_valid(number)


@given(
    st.sampled_from([("PT", 21), ("ES", 20), ("DE", 18)]).flatmap(
        lambda c: st.tuples(
            st.just(c[0]), st.text(alphabet=string.digits, min_size=c[1], max_size=c[1])
        )
    )
)
def test_validators_agree_with_stdnum_iban(case: tuple[str, str]) -> None:
    country, body = case
    check = std_iban.calc_check_digits(country + "00" + body)
    number = country + check + body
    assert valid_iban(number)  # o módulo 97 está certo por construção
    if std_iban.is_valid(number):  # o stdnum valida mais (dígitos de controlo nacionais)
        assert valid_iban(number)
    broken = number[:-1] + str((int(number[-1]) + 1) % 10)
    assert not valid_iban(broken)
    assert not std_iban.is_valid(broken)


def test_generated_valid_values_are_accepted() -> None:
    # constrói valores válidos pelo oráculo e confirma que os nossos validadores os aceitam
    for base in ("12345678", "50000000", "98765432", "20123456"):
        assert valid_nif(base + std_nif.calc_check_digit(base))
    for base in ("00000000", "12345678"):
        for tail in ("AB", "Z9", "00"):
            number = base + "1" + tail
            assert valid_cc(number + std_cc.calc_check_digit(number)) is True

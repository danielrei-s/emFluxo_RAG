"""Validadores de identificadores portugueses (F4-T07): só contam valores com dígito de controlo."""

from __future__ import annotations

import re

_NIF_FIRST_DIGITS = frozenset("12356789")
_NISS_WEIGHTS = (29, 23, 19, 17, 13, 11, 7, 5, 3, 2)
_CC_RE = re.compile(r"[0-9]{9}[A-Z0-9]{2}[0-9]")
_IBAN_RE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")


def valid_nif(value: str) -> bool:
    """NIF: 9 dígitos, 1.º dígito em {1,2,3,5,6,7,8,9}, controlo módulo 11 com pesos 9..2."""
    if len(value) != 9 or not value.isascii() or not value.isdigit():
        return False
    if value[0] not in _NIF_FIRST_DIGITS:
        return False
    total = sum(int(d) * w for d, w in zip(value[:8], range(9, 1, -1), strict=True))
    remainder = total % 11
    check = 0 if remainder < 2 else 11 - remainder
    return check == int(value[8])


def valid_niss(value: str) -> bool:
    """NISS: 11 dígitos a começar por 1 ou 2; controlo ``9 - (Σ pesos·dígitos) % 10``."""
    if len(value) != 11 or not value.isascii() or not value.isdigit() or value[0] not in "12":
        return False
    total = sum(int(d) * w for d, w in zip(value[:10], _NISS_WEIGHTS, strict=True))
    return 9 - (total % 10) == int(value[10])


def _char_value(char: str) -> int:
    return int(char) if char.isdigit() else ord(char) - ord("A") + 10


def valid_cc(value: str) -> bool:
    """Número de documento do Cartão de Cidadão (12 caracteres), por Luhn alfanumérico."""
    compact = value.upper()
    if not _CC_RE.fullmatch(compact):
        return False
    total = 0
    for position, char in enumerate(reversed(compact)):
        number = _char_value(char)
        if position % 2 == 1:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def valid_iban(value: str) -> bool:
    """IBAN: formato, e inteiro (letras A=10…) com ``% 97 == 1`` depois de rodar 4 caracteres."""
    compact = value.replace(" ", "").upper()
    if not _IBAN_RE.fullmatch(compact) or len(compact) > 34:
        return False
    rotated = compact[4:] + compact[:4]
    return int("".join(str(_char_value(c)) for c in rotated)) % 97 == 1

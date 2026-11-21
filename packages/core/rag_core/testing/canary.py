"""Verificação de canários (INV-03): strings únicas que nunca devem vazar."""

from __future__ import annotations

DEFAULT_CANARIES: tuple[str, ...] = ("CANARIO-", "HIDDEN-", "PWNED-")


def assert_no_canary(
    *texts: str | bytes, canaries: tuple[str, ...] = DEFAULT_CANARIES
) -> None:
    """Falha se algum texto contiver um canário.

    A mensagem de erro indica só o índice do texto e o canário, nunca o conteúdo.
    """
    for index, text in enumerate(texts):
        haystack = text.decode("utf-8", errors="replace") if isinstance(text, bytes) else text
        for canary in canaries:
            if canary in haystack:
                raise AssertionError(f"canário {canary!r} encontrado no texto #{index}")

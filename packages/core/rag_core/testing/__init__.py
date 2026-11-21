"""Utilitários de teste partilhados (C10). Só para testes: importa ``pytest``."""

from rag_core.testing.canary import DEFAULT_CANARIES, assert_no_canary
from rag_core.testing.logs import captured_logs

__all__ = ["DEFAULT_CANARIES", "assert_no_canary", "captured_logs"]

"""Contagem aproximada de tokens (estimativa também usada em produção)."""

from __future__ import annotations

import math


class ApproxTokenCounter:
    """Estima tokens como ``ceil(len(texto) / 4)``."""

    def count(self, text: str) -> int:
        return math.ceil(len(text) / 4)

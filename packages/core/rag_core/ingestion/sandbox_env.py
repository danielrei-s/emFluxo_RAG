"""Ambiente mínimo do worker de parsing (INV-13).

É, com ``testing/sandbox_parsers.py``, uma das únicas leituras diretas do ambiente do processo
(``test_no_other_module_reads_environ_directly`` tem esta lista branca): copia só variáveis
de sistema indispensáveis e dos diretórios de cache de modelos, nunca segredos ``RAG_*``.
"""

from __future__ import annotations

import os

ALLOWED_KEYS = (
    "PATH",
    "SYSTEMROOT",
    "HF_HOME",
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "XDG_CACHE_HOME",
)


# Valores fixos (não lidos do pai): poucas threads nas bibliotecas numéricas mantêm o espaço de
# endereçamento pequeno, o que importa com RLIMIT_AS.
FIXED = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}


def sandbox_environment() -> dict[str, str]:
    """Ambiente do subprocesso: as chaves da lista branca presentes no pai mais ``FIXED``."""
    env = {key: os.environ[key] for key in ALLOWED_KEYS if key in os.environ}
    return {**env, **FIXED}

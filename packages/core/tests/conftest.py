"""Configuração partilhada dos testes de ``rag_core``."""

import pytest
from rag_core.testing import captured_logs  # noqa: F401  (exporta a fixture)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Os marcadores ``posix_only`` e ``windows_only`` saltam no SO errado."""
    import sys

    for item in items:
        if item.get_closest_marker("posix_only") and sys.platform == "win32":
            item.add_marker(pytest.mark.skip(reason="só corre em POSIX"))
        if item.get_closest_marker("windows_only") and sys.platform != "win32":
            item.add_marker(pytest.mark.skip(reason="só corre em Windows"))

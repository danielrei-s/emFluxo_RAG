"""``BlobStore`` em memória."""

from __future__ import annotations

from rag_core.errors import NotFound


class InMemoryBlobStore:
    """Dicionário de bytes por chave."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._data[key] = bytes(data)

    def get(self, key: str) -> bytes:
        try:
            return self._data[key]
        except KeyError:
            raise NotFound from None

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._data

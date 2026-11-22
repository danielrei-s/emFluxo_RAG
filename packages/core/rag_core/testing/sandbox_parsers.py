"""Parsers de teste do sandbox (F3-T10). Só são registados no worker com ``test_mode=True``.

Cada um ocupa um ``DetectedType`` que os testes de sandbox não usam para parsing real:

=========  ==================================================================
MSG        ``NetworkProbeParser``: tenta ligar, ouvir e resolver nomes (rede)
TIFF       ``SpawnProbeParser``: tenta lançar processos
PNG        ``SleepParser``: dorme (para o teste de timeout)
JPEG       ``MemoryHogParser``: consome memória sem parar
XLSX       ``EnvDumpParser``: devolve os nomes das variáveis de ambiente do worker
=========  ==================================================================
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

from rag_core.interfaces import ParseLimits
from rag_core.parsing.registry import ParserRegistry
from rag_core.types import Block, DetectedType, StructuredDocument


def _doc(detected: DetectedType, text: str, name: str) -> StructuredDocument:
    return StructuredDocument(
        detected_type=detected,
        blocks=(Block(kind="paragraph", text=text),),
        parser_name=name,
        parser_version="test",
    )


class NetworkProbeParser:
    name = "test-network-probe"
    version = "test"
    supported = frozenset({DetectedType.MSG})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        action = filename.split(".")[0]
        if action == "connect":
            socket.create_connection(("127.0.0.1", 9), timeout=1)
        elif action == "bind":
            socket.socket().bind(("127.0.0.1", 0))
        elif action == "dns":
            socket.getaddrinfo("example.com", 80)
        elif action == "swallow":  # apanha o erro: o worker tem de reportar na mesma
            try:  # noqa: SIM105 - o ponto é apanhar o erro
                socket.getaddrinfo("example.com", 80)
            except OSError:
                pass
        return _doc(detected, "rede acessível", self.name)


class SpawnProbeParser:
    name = "test-spawn-probe"
    version = "test"
    supported = frozenset({DetectedType.TIFF})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        action = filename.split(".")[0]
        if action == "subprocess":
            subprocess.run([sys.executable, "-c", "print(1)"], check=False)
        elif action == "system":
            os.system("echo 1")  # noqa: S605, S607
        elif action == "exec":
            os.execv(sys.executable, [sys.executable, "-c", "print(1)"])  # noqa: S606
        elif action == "spawn" and hasattr(os, "spawnv"):
            os.spawnv(os.P_WAIT, sys.executable, [sys.executable, "-c", "print(1)"])  # noqa: S606
        return _doc(detected, "processo lançado", self.name)


class SleepParser:
    name = "test-sleep"
    version = "test"
    supported = frozenset({DetectedType.PNG})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        time.sleep(60)
        return _doc(detected, "acordou", self.name)


class MemoryHogParser:
    name = "test-memory-hog"
    version = "test"
    supported = frozenset({DetectedType.JPEG})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        hoard: list[bytes] = []
        while True:  # blocos preenchidos (não zero) para o RSS subir de facto
            hoard.append(b"x" * (16 * 1024 * 1024))
            time.sleep(0.02)


class EnvDumpParser:
    name = "test-env-dump"
    version = "test"
    supported = frozenset({DetectedType.XLSX})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        names = sorted(os.environ)
        values = " ".join(os.environ.values())
        return _doc(detected, "\n".join([*names, "---", values]), self.name)


def register_test_parsers(registry: ParserRegistry) -> None:
    for parser in (
        NetworkProbeParser(),
        SpawnProbeParser(),
        SleepParser(),
        MemoryHogParser(),
        EnvDumpParser(),
    ):
        registry.register(parser)

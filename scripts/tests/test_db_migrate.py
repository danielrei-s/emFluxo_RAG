"""Testes unitários (sem BD) de F7-T01: descoberta, checksum e CLI das migrações."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import db_bootstrap_roles as roles  # noqa: E402
import db_migrate as dm  # noqa: E402


def test_real_migrations_are_contiguous_and_named() -> None:
    found = dm.discover()
    assert found[0].version == "0001"
    assert all(m.checksum and m.sql.strip() for m in found)


def test_checksum_ignores_line_endings() -> None:
    assert dm.checksum_of("a\r\nb\r\n") == dm.checksum_of("a\nb\n")
    assert dm.checksum_of("a") != dm.checksum_of("b")


def test_discover_rejects_bad_names_and_gaps(tmp_path: Path) -> None:
    (tmp_path / "0001_ok.sql").write_text("select 1;", encoding="utf-8")
    (tmp_path / "0003_gap.sql").write_text("select 1;", encoding="utf-8")
    with pytest.raises(dm.MigrationError, match="non_contiguous_versions"):
        dm.discover(tmp_path)
    (tmp_path / "0003_gap.sql").unlink()
    (tmp_path / "Mau-Nome.sql").write_text("select 1;", encoding="utf-8")
    with pytest.raises(dm.MigrationError, match="invalid_filename"):
        dm.discover(tmp_path)


def test_main_without_url_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.delenv("RAG_DATABASE_MIGRATOR_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # sem .env.local
    assert dm.main([]) == 2
    assert "RAG_DATABASE_MIGRATOR_URL" in capsys.readouterr().err
    assert roles.main() == 2


def test_connection_errors_never_print_the_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise psycopg.OperationalError("falhou postgresql://u:SEGREDO@127.0.0.1:1/x")

    monkeypatch.setattr(psycopg, "connect", refuse)  # sem rede: a ligação falha logo
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_DATABASE_MIGRATOR_URL", "postgresql://u:SEGREDO@127.0.0.1:1/x")
    assert dm.main([]) == 1
    out = capsys.readouterr()
    assert "SEGREDO" not in out.out + out.err
    monkeypatch.setenv("RAG_DB_API_PASSWORD", "p1")
    monkeypatch.setenv("RAG_DB_WORKER_PASSWORD", "p2")
    monkeypatch.setenv("RAG_DB_BACKOFFICE_PASSWORD", "p3")
    assert roles.main() == 1
    out = capsys.readouterr()
    assert "SEGREDO" not in out.out + out.err and "p1" not in out.out + out.err


def test_bootstrap_requires_passwords_before_connecting() -> None:
    with pytest.raises(ValueError, match="missing_passwords"):
        roles.bootstrap("postgresql://x", {})


def test_bootstrap_main_reports_missing_passwords(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RAG_DATABASE_MIGRATOR_URL", "postgresql://u:x@127.0.0.1:1/x")
    for var in ("RAG_DB_API_PASSWORD", "RAG_DB_WORKER_PASSWORD", "RAG_DB_BACKOFFICE_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    assert roles.main() == 2
    assert "missing_passwords" in capsys.readouterr().err

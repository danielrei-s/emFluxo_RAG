"""Testes de F0-T08: verificação de licenças por perfil (INV-21)."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / "data"
sys.path.insert(0, str(ROOT / "scripts"))

import check_licenses as cl  # noqa: E402


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    return cl.load_policy()


def _py(name: str) -> list[cl.Entry]:
    return cl.parse_python_json(json.loads((DATA / name).read_text(encoding="utf-8")))


def _js(name: str) -> list[cl.Entry]:
    return cl.parse_js_json(json.loads((DATA / name).read_text(encoding="utf-8")))


def test_gpl_in_shipped_fails(policy: dict[str, Any]) -> None:
    violations = cl.evaluate(_py("licenses_python_gpl.json"), "shipped", policy)
    assert [v.entry.name for v in violations] == ["extract-msg"]
    assert "proibida" in violations[0].reason


def test_gpl_in_server_fails_and_in_dev_passes(policy: dict[str, Any]) -> None:
    entries = _py("licenses_python_gpl.json")
    assert len(cl.evaluate(entries, "server", policy)) == 1
    assert cl.evaluate(entries, "dev", policy) == []


def test_lgpl_in_server_passes(policy: dict[str, Any]) -> None:
    entries = _py("licenses_python_lgpl.json")
    assert cl.evaluate(entries, "server", policy) == []
    assert [v.entry.name for v in cl.evaluate(entries, "shipped", policy)] == ["psycopg"]


def test_unknown_license_fails(policy: dict[str, Any]) -> None:
    for profile in ("shipped", "server", "dev"):
        violations = cl.evaluate(_py("licenses_python_unknown.json"), profile, policy)
        assert [v.reason for v in violations] == ["licença desconhecida"]


def test_exception_applies(policy: dict[str, Any]) -> None:
    custom = copy.deepcopy(policy)
    custom["exceptions"] = [
        {"package": "mystery-lib==0.1.0", "reason": "confirmada por email", "adr": "ADR-0099"}
    ]
    assert cl.evaluate(_py("licenses_python_unknown.json"), "shipped", custom) == []
    custom["exceptions"][0]["package"] = "mystery-lib==9.9.9"
    assert len(cl.evaluate(_py("licenses_python_unknown.json"), "shipped", custom)) == 1
    custom["exceptions"][0]["package"] = "mystery-lib"
    assert cl.evaluate(_py("licenses_python_unknown.json"), "shipped", custom) == []


def test_normalization_map(policy: dict[str, Any]) -> None:
    assert cl.normalize_license("MIT License", policy) == "MIT"
    assert cl.normalize_license("Apache Software License", policy) == "Apache-2.0"
    assert cl.normalize_license("BSD License", policy) == "BSD-3-Clause"
    assert cl.normalize_license("  mit license ", policy) == "MIT"
    assert cl.normalize_license("Python-2.0", policy) == "PSF-2.0"
    assert cl.normalize_license("Something Else", policy) == "Something Else"


def test_spdx_expressions(policy: dict[str, Any]) -> None:
    violations = cl.evaluate(_py("licenses_python_expressions.json"), "server", policy)
    assert sorted(v.entry.name for v in violations) == ["both-lib", "complex-lib"]


def test_own_workspace_packages_are_ignored(policy: dict[str, Any]) -> None:
    entries = [
        cl.Entry("python", "rag-core", "0.0.0", "UNKNOWN"),
        cl.Entry("js", "@rag/ui", "0.0.0", "UNLICENSED"),
    ]
    assert cl.evaluate(entries, "shipped", policy) == []


def test_js_entries_one_per_version(policy: dict[str, Any]) -> None:
    entries = _js("licenses_js_ok.json")
    assert [(e.name, e.version) for e in entries] == [
        ("react", "19.3.1"),
        ("lib-a", "1.0.0"),
        ("lib-a", "2.0.0"),
    ]
    assert cl.evaluate(entries, "shipped", policy) == []
    assert [v.entry.name for v in cl.evaluate(_js("licenses_js_gpl.json"), "server", policy)] == [
        "bad-js-lib"
    ]


def test_policy_file_is_well_formed(policy: dict[str, Any]) -> None:
    assert set(policy["profiles"]) == {"shipped", "server", "dev"}
    shipped, server, dev = (set(policy["profiles"][p]["allow"]) for p in policy["profiles"])
    assert shipped <= server <= dev
    assert not any("GPL" in lic and not lic.startswith("LGPL") for lic in server)
    assert "MIT" in shipped


def test_exceptions_require_reason_and_adr(tmp_path: Path) -> None:
    bad = tmp_path / "policy.yaml"
    original = (ROOT / "scripts" / "license_policy.yaml").read_text(encoding="utf-8")
    head = original[: original.index("exceptions:")]
    bad.write_text(head + "exceptions:\n  - package: foo\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reason"):
        cl.load_policy(bad)


def test_cli_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["--profile", "shipped", "--js-json", str(DATA / "licenses_js_ok.json")]
    assert cl.main([*args, "--python-json", str(DATA / "licenses_python_gpl.json")]) == 1
    assert "extract-msg" in capsys.readouterr().out
    assert cl.main([*args, "--python-json", str(DATA / "licenses_python_empty.json")]) == 0
    assert "Licenças OK" in capsys.readouterr().out


def test_current_repository_licenses_pass() -> None:
    """DoD: o estado atual do repositório cumpre os perfis server e dev."""
    assert cl.main(["--profile", "server", "--profile", "dev"]) == 0

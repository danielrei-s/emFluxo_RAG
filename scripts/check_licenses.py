#!/usr/bin/env python3
"""Verifica as licenças das dependências contra a política da C4 (INV-21).

Uso:
    python scripts/check_licenses.py [--profile server --profile dev]
    python scripts/check_licenses.py --profile shipped --python-json py.json --js-json js.json

Sem ``--python-json``/``--js-json`` recolhe os dados com ``pip-licenses`` e ``pnpm licenses``.
Perfis ``shipped`` e ``server`` só consideram dependências de produção. Sai com código 1 se
houver violações.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = Path(__file__).resolve().parent / "license_policy.yaml"
PROD_PROFILES = {"shipped", "server"}


@dataclass(frozen=True)
class Entry:
    """Uma dependência e a licença que declara."""

    ecosystem: str  # "python" | "js"
    name: str
    version: str
    license: str


@dataclass(frozen=True)
class Violation:
    entry: Entry
    profile: str
    reason: str


# --------------------------------------------------------------------------- política


def _flatten(items: list[Any]) -> list[str]:
    flat: list[str] = []
    for item in items:
        if isinstance(item, list):
            flat.extend(_flatten(item))
        else:
            flat.append(str(item))
    return flat


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    """Lê e valida ``license_policy.yaml``; normaliza listas aninhadas por âncoras YAML."""
    policy: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    for name, profile in policy["profiles"].items():
        profile["allow"] = _flatten(profile["allow"])
        if not profile["allow"]:
            raise ValueError(f"perfil {name} sem licenças permitidas")
    policy["normalize"] = {k.lower(): v for k, v in policy.get("normalize", {}).items()}
    policy.setdefault("exceptions", [])
    for exc in policy["exceptions"]:
        if not all(exc.get(key) for key in ("package", "reason", "adr")):
            raise ValueError("cada exceção precisa de package, reason e adr")
    return policy


# --------------------------------------------------------------------------- avaliação


def normalize_license(text: str, policy: dict[str, Any]) -> str:
    """Devolve o identificador SPDX para ``text`` (ou o próprio texto se não houver mapa)."""
    stripped = text.strip()
    return str(policy["normalize"].get(stripped.lower(), stripped))


def _atom_allowed(atom: str, allowed: set[str], policy: dict[str, Any]) -> bool:
    return normalize_license(atom, policy) in allowed


def _group_allowed(group: str, allowed: set[str], policy: dict[str, Any]) -> bool:
    """``A OR B``: basta uma alternativa; dentro de cada alternativa ``A AND B``: todas."""
    alternatives = re.split(r"\s+OR\s+", group.strip(), flags=re.I)
    for alternative in alternatives:
        atoms = re.split(r"\s+AND\s+", alternative.strip(), flags=re.I)
        if all(_atom_allowed(atom, allowed, policy) for atom in atoms):
            return True
    return False


def license_allowed(text: str, allowed: set[str], policy: dict[str, Any]) -> bool:
    """Indica se a expressão de licença ``text`` é permitida pelo conjunto ``allowed``."""
    if _atom_allowed(text, allowed, policy):  # inclui nomes completos com parênteses
        return True
    if "(" in text and normalize_license(text, policy) == text.strip():
        return False  # expressão complexa não mapeada
    return all(_group_allowed(group, allowed, policy) for group in text.split(";"))


def _is_own(name: str, policy: dict[str, Any]) -> bool:
    return any(fnmatch.fnmatch(name.lower(), pat.lower()) for pat in policy["own_packages"])


def _exception_applies(entry: Entry, policy: dict[str, Any]) -> bool:
    for exc in policy["exceptions"]:
        package = str(exc["package"])
        if package in (entry.name, f"{entry.name}=={entry.version}"):
            return True
    return False


def _reason(text: str, policy: dict[str, Any]) -> str:
    normalized = normalize_license(text, policy)
    if normalized.upper() in {"", "UNKNOWN"}:
        return "licença desconhecida"
    if any(re.search(p, normalized) for p in policy["forbidden_patterns"]):
        return f"licença proibida neste perfil ({normalized})"
    return f"licença fora da allowlist ({normalized})"


def evaluate(entries: list[Entry], profile: str, policy: dict[str, Any]) -> list[Violation]:
    """Devolve as violações de ``entries`` para o ``profile``."""
    allowed = set(policy["profiles"][profile]["allow"])
    violations: list[Violation] = []
    for entry in entries:
        if _is_own(entry.name, policy) or _exception_applies(entry, policy):
            continue
        if not license_allowed(entry.license, allowed, policy):
            violations.append(Violation(entry, profile, _reason(entry.license, policy)))
    return violations


# --------------------------------------------------------------------------- entrada


def parse_python_json(data: list[dict[str, str]]) -> list[Entry]:
    """Formato de ``pip-licenses --format=json``."""
    return [Entry("python", d["Name"], d["Version"], d["License"]) for d in data]


def parse_js_json(data: dict[str, list[dict[str, Any]]]) -> list[Entry]:
    """Formato de ``pnpm licenses list --json`` (licença -> pacotes)."""
    entries: list[Entry] = []
    for license_name, packages in data.items():
        for package in packages:
            for version in package.get("versions") or [""]:
                entries.append(Entry("js", package["name"], version, license_name))
    return entries


def _run(cmd: list[str]) -> str:
    result = subprocess.run(  # noqa: S603
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def collect_python(profile: str) -> list[Entry]:
    """Corre ``pip-licenses`` no ambiente atual; em perfis de produção filtra por ``uv export``."""
    entries = parse_python_json(
        json.loads(_run([sys.executable, "-m", "piplicenses", "--format=json"]))
    )
    if profile not in PROD_PROFILES:
        return entries
    uv = shutil.which("uv") or "uv"
    exported = _run(
        [uv, "export", "--no-dev", "--all-packages", "--no-hashes", "--no-emit-workspace"]
    )
    prod = {_canonical(m.group(1)) for m in re.finditer(r"^([A-Za-z0-9_.-]+)==", exported, re.M)}
    return [e for e in entries if _canonical(e.name) in prod]


def collect_js(profile: str) -> list[Entry]:
    """Corre ``pnpm licenses list --json`` (``--prod`` nos perfis de produção)."""
    pnpm = shutil.which("pnpm") or "pnpm"
    cmd = [pnpm, "licenses", "list", "--json"]
    if profile in PROD_PROFILES:
        cmd.append("--prod")
    out = _run(cmd).strip()
    return parse_js_json(json.loads(out)) if out else []


# --------------------------------------------------------------------------- CLI


def format_violations(violations: list[Violation]) -> str:
    rows = [("perfil", "ecossistema", "pacote", "versão", "motivo")]
    rows += [
        (v.profile, v.entry.ecosystem, v.entry.name, v.entry.version, v.reason) for v in violations
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)) for r in rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--profile", action="append", choices=["shipped", "server", "dev"])
    parser.add_argument("--python-json", type=Path, help="saída de pip-licenses (em vez de correr)")
    parser.add_argument("--js-json", type=Path, help="saída de pnpm licenses (em vez de correr)")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    violations: list[Violation] = []
    for profile in args.profile or ["server", "dev"]:
        if args.python_json:
            entries = parse_python_json(json.loads(args.python_json.read_text(encoding="utf-8")))
        else:
            entries = collect_python(profile)
        if args.js_json:
            entries += parse_js_json(json.loads(args.js_json.read_text(encoding="utf-8")))
        else:
            entries += collect_js(profile)
        found = evaluate(entries, profile, policy)
        print(f"[{profile}] {len(entries)} dependências, {len(found)} violações")
        violations += found

    if violations:
        print(format_violations(violations))
        return 1
    print("Licenças OK.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(main())

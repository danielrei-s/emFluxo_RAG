#!/usr/bin/env python3
"""Valida a consistência do plano (ficheiro único).

Uso: python check_plan.py PLANO.md [--spec docs/spec/especificacao-v0.1.md]
Sai com código 1 se encontrar problemas.

Verifica:
- cada cartão de tarefa tem os campos obrigatórios;
- IDs de tarefa únicos; dependências existem, não apontam para fases futuras e não têm ciclos;
- referências HR-xx existem na Parte E; INV-xx existem na C5; secções Cxx existem;
- contagem de tarefas por fase coincide com a tabela D0;
- nomes de teste test_invNN_ usam invariantes existentes;
- cada cartão tem pelo menos um teste nomeado.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

CARD_RE = re.compile(r"^#### (F(\d+)-T(\d+)) · (.+)$", re.M)
STOP_RE = re.compile(r"^(#{1,4}) ", re.M)
TASK_ID_RE = re.compile(r"\bF(\d+)-T(\d+)\b")
REQUIRED = [
    "**Objetivo:**",
    "**Depende de:**",
    "**Tamanho:**",
    "**Ler antes:**",
    "**Criar/alterar:**",
    "**Passos",
    "**Testes",
    "**DoD específico:**",
    "**🧑 Humano:**",
]


def strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.S)


def card_bodies(text: str) -> dict[str, tuple[int, str, str]]:
    cards: dict[str, tuple[int, str, str]] = {}
    matches = list(CARD_RE.finditer(text))
    for m in matches:
        start = m.end()
        nxt = STOP_RE.search(text, start)
        end = nxt.start() if nxt else len(text)
        task_id = m.group(1)
        if task_id in cards:
            raise SystemExit(f"ID duplicado: {task_id}")
        cards[task_id] = (int(m.group(2)), m.group(4), text[start:end])
    return cards


def check_spec_refs(text: str, spec_path: str, problems: list[str]) -> None:
    """Confirma que cada 'especificação X.Y' aponta para uma secção existente da especificação."""
    spec = Path(spec_path).read_text(encoding="utf-8")
    sections = set(re.findall(r"^#{2,4} (\d+(?:\.\d+)*)[ .]", spec, flags=re.M))
    for m in re.finditer(r"especificação ((?:\d+(?:\.\d+)*)(?:\s*[–-]\s*\d+(?:\.\d+)*)?(?:\s*e\s*\d+(?:\.\d+)*)?)", text):
        for ref in re.findall(r"\d+(?:\.\d+)*", m.group(1)):
            if ref not in sections:
                problems.append(f"'especificação {ref}' não existe em {spec_path}")


def main(path: str, spec_path: str | None = None) -> int:
    raw = Path(path).read_text(encoding="utf-8")
    text = strip_code_blocks(raw)
    problems: list[str] = []
    if spec_path:
        check_spec_refs(text, spec_path, problems)

    cards = card_bodies(text)
    if not cards:
        print("Nenhum cartão encontrado.")
        return 1

    # Campos obrigatórios e testes nomeados
    for tid, (_, _, body) in cards.items():
        for field in REQUIRED:
            if field not in body:
                problems.append(f"{tid}: falta o campo {field}")
        tests_part = body.split("**Testes", 1)[-1].split("**DoD", 1)[0]
        if "`" not in tests_part and "test" not in tests_part.lower():
            problems.append(f"{tid}: secção de testes sem testes nomeados")

    # Dependências
    graph: dict[str, list[str]] = {}
    for tid, (phase, _, body) in cards.items():
        dep_line = next((ln for ln in body.splitlines() if "**Depende de:**" in ln), "")
        dep_text = dep_line.split("**Depende de:**", 1)[-1].split("**Tamanho", 1)[0]
        deps = [f"F{a}-T{b}" for a, b in TASK_ID_RE.findall(dep_text)]
        graph[tid] = deps
        for d in deps:
            if d not in cards:
                problems.append(f"{tid}: depende de {d}, que não existe")
                continue
            if cards[d][0] > phase:
                problems.append(f"{tid}: depende de {d}, de uma fase posterior")
            if d == tid:
                problems.append(f"{tid}: depende de si próprio")

    # Ciclos (DFS)
    state: dict[str, int] = {}

    def visit(n: str, stack: list[str]) -> None:
        state[n] = 1
        for d in graph.get(n, []):
            if d not in cards:
                continue
            if state.get(d) == 1:
                problems.append("ciclo: " + " → ".join(stack + [n, d]))
            elif state.get(d) is None:
                visit(d, stack + [n])
        state[n] = 2

    for n in graph:
        if state.get(n) is None:
            visit(n, [])

    # HR definidos na Parte E
    part_e = raw.split("# PARTE E", 1)[-1].split("# PARTE F", 1)[0]
    hr_defined = set(re.findall(r"^\| (HR-\d\d) \|", part_e, flags=re.M))
    for hr in sorted(set(re.findall(r"\bHR-\d\d\b", text))):
        if hr not in hr_defined:
            problems.append(f"{hr} referido mas não definido na Parte E")
    for hr in sorted(hr_defined):
        if hr not in strip_code_blocks(raw.split("# PARTE E", 1)[0]):
            problems.append(f"{hr} definido na Parte E mas nunca referido nos cartões")

    # Invariantes
    c5 = raw.split("## C5.", 1)[-1].split("## C6.", 1)[0]
    inv_defined = set(re.findall(r"^\| (INV-\d\d) \|", c5, flags=re.M))
    for inv in sorted(set(re.findall(r"\bINV-\d\d\b", text))):
        if inv not in inv_defined:
            problems.append(f"{inv} referido mas não definido na C5")
    for num in sorted(set(re.findall(r"test_inv(\d\d)_", raw))):
        if f"INV-{num}" not in inv_defined:
            problems.append(f"test_inv{num}_ refere um invariante inexistente")
    inv_name_re = r"(?:test_|(?<![A-Za-z0-9]))inv(\d\d)_"
    for num in sorted(set(re.findall(inv_name_re, raw))):
        if f"INV-{num}" not in inv_defined:
            problems.append(f"inv{num}_ refere um invariante inexistente")
    covered = {f"INV-{n}" for n in re.findall(inv_name_re, raw)}
    for inv in sorted(inv_defined - covered):
        problems.append(f"{inv} não tem nenhum teste nomeado (test_invNN_/invNN_) nos cartões")

    # Secções C
    c_defined = set(re.findall(r"^## (C\d+)\.", raw, flags=re.M))
    for tid, (_, _, body) in cards.items():
        ler = next((ln for ln in body.splitlines() if "**Ler antes:**" in ln), "")
        for c in re.findall(r"\bC(\d+)\b", ler):
            if f"C{c}" not in c_defined:
                problems.append(f"{tid}: 'Ler antes' refere C{c}, que não existe")

    # Tabela D0
    d0 = raw.split("## D0.", 1)[-1].split("---", 1)[0]
    counts = defaultdict(int)
    for _, (phase, _, _) in cards.items():
        counts[phase] += 1
    for m in re.finditer(r"^\| F(\d+) \| [^|]+\| (\d+) \|", d0, flags=re.M):
        ph, n = int(m.group(1)), int(m.group(2))
        if counts.get(ph, 0) != n:
            problems.append(f"D0: F{ph} diz {n} tarefas, mas há {counts.get(ph, 0)} cartões")

    total = len(cards)
    if problems:
        print(f"{len(problems)} problema(s) em {total} cartões:")
        for p in problems:
            print(" -", p)
        return 1
    print(f"OK — {total} cartões, {len(hr_defined)} pedidos humanos, {len(inv_defined)} invariantes.")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    spec = None
    if "--spec" in args:
        i = args.index("--spec")
        spec = args[i + 1]
        del args[i : i + 2]
    sys.exit(main(args[0] if args else "PLANO.md", spec))

#!/usr/bin/env python3
"""Divide o plano (ficheiro único) numa pasta com um ficheiro por tarefa.

Uso: python split_plan.py PLANO.md SAIDA/

Gera:
  README.md                 índice e prompt de arranque
  00-avaliacao.md           cabeçalho + Parte A
  01-protocolo.md           Parte B
  02-contexto-global.md     Parte C
  03-roadmap.md             mapa das fases + introdução de cada fase + ligações para os cartões
  tarefas/<ID>.md           um cartão por ficheiro, com o contexto da fase
  04-pedidos-humanos.md     Parte E
  05-trilha-negocio.md      Parte F
  06-templates.md           Parte G
  STATUS.md                 todas as tarefas em ⬜ (copiar para docs/plan/STATUS.md)
  HUMAN_REQUESTS.md         pedidos previstos no formato G3 (copiar para docs/HUMAN_REQUESTS.md)

Edita sempre o ficheiro único e volta a correr este script.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

GENERATED = "<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->\n\n"


def headings(lines: list[str], levels: tuple[int, ...]) -> list[tuple[int, int, str]]:
    """Devolve (índice, nível, texto) dos títulos fora de blocos de código."""
    out: list[tuple[int, int, str]] = []
    fence = False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = re.match(r"^(#{1,6}) (.+?)\s*$", line)
        if m and len(m.group(1)) in levels:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def split_parts(raw: str) -> tuple[str, dict[str, str]]:
    lines = raw.splitlines(keepends=True)
    tops = [(i, t) for i, lvl, t in headings(lines, (1,)) if t.startswith("PARTE ")]
    header = "".join(lines[: tops[0][0]])
    parts: dict[str, str] = {}
    for n, (i, title) in enumerate(tops):
        end = tops[n + 1][0] if n + 1 < len(tops) else len(lines)
        parts[title.split()[1]] = "".join(lines[i:end])
    return header, parts


def parse_roadmap(part_d: str):
    lines = part_d.splitlines(keepends=True)
    hs = headings(lines, (2, 3, 4))
    phases = []  # dicts: title, intro, cards[(id, title, body)]
    d0_end = next(i for i, lvl, t in hs if lvl == 3)
    d0 = "".join(lines[:d0_end])
    idx = [h for h in hs if h[1] in (3, 4)]
    for n, (i, lvl, title) in enumerate(idx):
        end = idx[n + 1][0] if n + 1 < len(idx) else len(lines)
        block = "".join(lines[i + 1 : end])
        if lvl == 3:
            phases.append({"title": title, "intro": block, "cards": []})
        else:
            m = re.match(r"(F\d+-T\d+) · (.+)", title)
            if m and phases:
                phases[-1]["cards"].append((m.group(1), m.group(2), block))
            elif phases:
                phases[-1]["intro"] += "".join(lines[i:end])
    return d0, phases


def anchor(text: str) -> str:
    a = text.lower()
    a = re.sub(r"[^\w\s-]", "", a, flags=re.U)
    return re.sub(r"\s+", "-", a.strip())


def main(src: str, out_dir: str) -> int:
    raw = Path(src).read_text(encoding="utf-8")
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "tarefas").mkdir(parents=True)

    header, parts = split_parts(raw)
    (out / "00-avaliacao.md").write_text(GENERATED + header + parts["A"], encoding="utf-8")
    (out / "01-protocolo.md").write_text(GENERATED + parts["B"], encoding="utf-8")
    (out / "02-contexto-global.md").write_text(GENERATED + parts["C"], encoding="utf-8")
    (out / "04-pedidos-humanos.md").write_text(GENERATED + parts["E"], encoding="utf-8")
    (out / "05-trilha-negocio.md").write_text(GENERATED + parts["F"], encoding="utf-8")
    (out / "06-templates.md").write_text(GENERATED + parts["G"], encoding="utf-8")

    d0, phases = parse_roadmap(parts["D"])
    roadmap = [GENERATED, d0.rstrip().rstrip("-").rstrip() + "\n\n"]
    status = [
        GENERATED,
        "# STATUS\n\nLegenda: ⬜ por fazer · 🟨 em curso · ✅ concluída · ⛔ bloqueada (HR-xxx)\n",
    ]
    total = 0
    for ph in phases:
        intro = ph["intro"].strip().rstrip("-").strip()
        roadmap.append(f"### {ph['title']}\n\n{intro}\n\n")
        if ph["cards"]:
            status.append(f"\n## {ph['title']}\n\n| ID | Título | Estado | Ramo/PR | Notas |\n|---|---|---|---|---|\n")
        for tid, title, body in ph["cards"]:
            total += 1
            roadmap.append(f"- [{tid} · {title}](tarefas/{tid}.md)\n")
            status.append(f"| {tid} | {title} | ⬜ | | |\n")
            phase_ctx = "\n".join("> " + ln if ln.strip() else ">" for ln in intro.splitlines())
            card = (
                GENERATED
                + f"# {tid} · {title}\n\n"
                + f"**Fase:** {ph['title']}\n\n"
                + phase_ctx
                + "\n\n"
                + "Antes de começar: lê [`../01-protocolo.md`](../01-protocolo.md) e, de "
                + "[`../02-contexto-global.md`](../02-contexto-global.md), só as secções indicadas em "
                + '"Ler antes" (uma referência "especificação X.Y" é só essa secção de '
                + "`docs/spec/especificacao-v0.1.md`). Confirma as dependências em `STATUS.md`.\n\n"
                + body.strip().rstrip("-").strip()
                + "\n"
            )
            (out / "tarefas" / f"{tid}.md").write_text(card, encoding="utf-8")
        roadmap.append("\n")
    (out / "03-roadmap.md").write_text("".join(roadmap), encoding="utf-8")
    (out / "STATUS.md").write_text("".join(status), encoding="utf-8")

    # Pedidos humanos no formato G3
    hr_lines = [
        GENERATED,
        "# Pedidos humanos (HR)\n\nRegisto dos pedidos ao OLEK. Formato: Parte G3 do plano. "
        "Segredos nunca no chat.\n",
    ]
    for m in re.finditer(r"^\| (HR-\d\d) \| ([^|]+)\| ([^|]+)\| ([^|]+)\| ([^|]+)\|", parts["E"], flags=re.M):
        hid, what, tasks, blocks, how = (g.strip() for g in m.groups())
        hr_lines.append(
            f"\n### {hid} · {what}\n"
            f"- **Tarefa:** {tasks} · **Bloqueante:** {blocks}\n"
            f"- **Preciso de:** {what}\n"
            f"- **Como entregar:** {how}\n"
            f"- **Estado:** previsto\n"
        )
    (out / "HUMAN_REQUESTS.md").write_text("".join(hr_lines), encoding="utf-8")

    # README com o prompt de arranque (B1)
    b1 = re.search(r"## B1\..*?```text\n(.*?)```", parts["B"], flags=re.S)
    prompt = b1.group(1) if b1 else ""
    phase_list = "".join(
        f"- [{ph['title']}](03-roadmap.md#{anchor(ph['title'])}) — {len(ph['cards'])} tarefas\n"
        for ph in phases
        if ph["cards"]
    )
    readme = (
        GENERATED
        + "# Plano de implementação — versão dividida\n\n"
        + "No repositório esta pasta vive em `docs/plan/`. `HUMAN_REQUESTS.md` passa para `docs/` e a "
        + "especificação (`spec/especificacao-v0.1.md`, fora desta pasta) para `docs/spec/`.\n\n"
        + "## Prompt de arranque para o agente\n\n```text\n"
        + prompt
        + "```\n\n## Ficheiros\n\n"
        + "| Ficheiro | Para quem |\n|---|---|\n"
        + "| `00-avaliacao.md` | OLEK — avaliação do plano original, alterações, riscos |\n"
        + "| `01-protocolo.md` | Agente — ler sempre |\n"
        + "| `02-contexto-global.md` | Agente — só as secções indicadas no cartão |\n"
        + "| `03-roadmap.md` | Todos — fases, gates e ligações para os cartões |\n"
        + "| `tarefas/<ID>.md` | Agente — um cartão por sessão |\n"
        + "| `04-pedidos-humanos.md` | OLEK — o que te vão pedir e quando |\n"
        + "| `05-trilha-negocio.md` | OLEK — negócio, legal, contas |\n"
        + "| `06-templates.md` | Todos — cartão, ADR, HR, PR, checklist de segurança |\n"
        + "| `STATUS.md` | Todos — estado de cada tarefa |\n\n"
        + f"## Fases ({total} tarefas)\n\n"
        + phase_list
        + "\n## Manter o plano\n\nEdita o ficheiro único e corre:\n\n```bash\n"
        + "python _ferramentas/check_plan.py PLANO_RAG_MULTINEGOCIO_v1.md --spec docs/spec/especificacao-v0.1.md\n"
        + "python _ferramentas/split_plan.py PLANO_RAG_MULTINEGOCIO_v1.md docs/plan\n```\n"
    )
    (out / "README.md").write_text(readme, encoding="utf-8")

    tools = out / "_ferramentas"
    tools.mkdir()
    here = Path(__file__).resolve().parent
    for name in ("check_plan.py", "split_plan.py"):
        if (here / name).exists():
            shutil.copy2(here / name, tools / name)

    print(f"OK — {total} cartões em {out / 'tarefas'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))

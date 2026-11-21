<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# Plano de implementação — versão dividida

No repositório esta pasta vive em `docs/plan/`. `HUMAN_REQUESTS.md` passa para `docs/` e a especificação (`spec/especificacao-v0.1.md`, fora desta pasta) para `docs/spec/`.

## Prompt de arranque para o agente

```text
És um agente de desenvolvimento no monorepo da Plataforma RAG Multi-Negócio.
A tua tarefa é: <ID> (exemplo: F3-T06).

1. Lê docs/plan/01-protocolo.md por inteiro.
2. Lê o cartão docs/plan/tarefas/<ID>.md.
3. Lê só as secções de docs/plan/02-contexto-global.md indicadas em "Ler antes"
   (e, se o cartão referir "especificação X.Y", só essa secção de
   docs/spec/especificacao-v0.1.md) e os ficheiros do repositório listados no
   cartão. Não leias o resto do plano nem o resto da especificação.
4. Confirma em docs/plan/STATUS.md que todas as dependências estão ✅.
   Se alguma não estiver, pára e diz qual.
5. Implementa apenas esta tarefa. Escreve os testes primeiro sempre que possível.
6. Corre `make lint test` e os comandos extra do cartão até tudo passar.
7. Atualiza docs/plan/STATUS.md, faz commit no ramo task/<ID>-<slug> e escreve o
   resumo final no formato da secção B7 do protocolo.
Se precisares de algo do OLEK (contas, chaves, decisões, hardware), segue a secção B5.
```

## Ficheiros

| Ficheiro | Para quem |
|---|---|
| `00-avaliacao.md` | OLEK — avaliação do plano original, alterações, riscos |
| `01-protocolo.md` | Agente — ler sempre |
| `02-contexto-global.md` | Agente — só as secções indicadas no cartão |
| `03-roadmap.md` | Todos — fases, gates e ligações para os cartões |
| `tarefas/<ID>.md` | Agente — um cartão por sessão |
| `04-pedidos-humanos.md` | OLEK — o que te vão pedir e quando |
| `05-trilha-negocio.md` | OLEK — negócio, legal, contas |
| `06-templates.md` | Todos — cartão, ADR, HR, PR, checklist de segurança |
| `STATUS.md` | Todos — estado de cada tarefa |

## Fases (138 tarefas)

- [F0 — Fundações do repositório](03-roadmap.md#f0-fundações-do-repositório) — 12 tarefas
- [F1 — Contratos do core e fakes](03-roadmap.md#f1-contratos-do-core-e-fakes) — 5 tarefas
- [F2 — Corpus sintético e golden set](03-roadmap.md#f2-corpus-sintético-e-golden-set) — 2 tarefas
- [F3 — Ingestão (core)](03-roadmap.md#f3-ingestão-core) — 13 tarefas
- [F4 — Recuperação e geração (core)](03-roadmap.md#f4-recuperação-e-geração-core) — 8 tarefas
- [F5 — Store local, modelos reais, CLI e avaliação · Marco M1](03-roadmap.md#f5-store-local-modelos-reais-cli-e-avaliação-marco-m1) — 5 tarefas
- [F6 — Inference Gateway · Marco M2](03-roadmap.md#f6-inference-gateway-marco-m2) — 8 tarefas
- [F7 — BD central, tenancy e identidade](03-roadmap.md#f7-bd-central-tenancy-e-identidade) — 7 tarefas
- [F8 — Central API](03-roadmap.md#f8-central-api) — 12 tarefas
- [F9 — Back-office e extensibilidade (API) · Marco M3](03-roadmap.md#f9-back-office-e-extensibilidade-api-marco-m3) — 3 tarefas
- [F10 — Aplicações web (Portal do Produto A e UI do back-office) · Marco M4](03-roadmap.md#f10-aplicações-web-portal-do-produto-a-e-ui-do-back-office-marco-m4) — 10 tarefas
- [F11 — Motor local (Produto B)](03-roadmap.md#f11-motor-local-produto-b) — 12 tarefas
- [F12 — App desktop (Tauri v2) · Marco M5](03-roadmap.md#f12-app-desktop-tauri-v2-marco-m5) — 6 tarefas
- [F13 — Endurecimento, observabilidade e prontidão para piloto · Marco M6](03-roadmap.md#f13-endurecimento-observabilidade-e-prontidão-para-piloto-marco-m6) — 8 tarefas
- [F14 — Piloto real](03-roadmap.md#f14-piloto-real) — 4 tarefas
- [F15 — Conectores cloud (planeamento por ondas)](03-roadmap.md#f15-conectores-cloud-planeamento-por-ondas) — 6 tarefas
- [F16 — Email: pesquisa (planeamento por ondas)](03-roadmap.md#f16-email-pesquisa-planeamento-por-ondas) — 5 tarefas
- [F17 — Email: rascunhos assistidos (planeamento por ondas)](03-roadmap.md#f17-email-rascunhos-assistidos-planeamento-por-ondas) — 4 tarefas
- [F18 — Plataforma multi-negócio (planeamento por ondas)](03-roadmap.md#f18-plataforma-multi-negócio-planeamento-por-ondas) — 8 tarefas

## Manter o plano

Edita o ficheiro único e corre:

```bash
python _ferramentas/check_plan.py PLANO_RAG_MULTINEGOCIO_v1.md --spec docs/spec/especificacao-v0.1.md
python _ferramentas/split_plan.py PLANO_RAG_MULTINEGOCIO_v1.md docs/plan
```

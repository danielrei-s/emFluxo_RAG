# emFluxo RAG — Plataforma RAG Multi-Negócio

Plataforma de perguntas e respostas sobre documentos de uma empresa, sempre com fontes citadas.
Tem dois produtos: o **Produto A**, um portal web multi-tenant com repositório central, e o
**Produto B**, uma app desktop (Tauri) com motor local que lê só as pastas que o utilizador autoriza.
Os dados ficam perto do cliente, há isolamento forte entre tenants e a segurança é a omissão.
O desenvolvimento segue um plano de 138 tarefas pequenas, executadas uma de cada vez por agentes.

## Pré-requisitos

- Python 3.12, [uv](https://docs.astral.sh/uv/)
- Node.js LTS e pnpm
- Rust (só para a app desktop)
- Docker (compose de desenvolvimento)

As ferramentas são configuradas em F0-T02 a F0-T04; até lá só `python scripts/check_structure.py` e os testes em `scripts/tests` funcionam.

## Comandos

```bash
make setup   # instala dependências (disponível a partir de F0-T04)
make test    # corre os testes (disponível a partir de F0-T04)
python scripts/check_structure.py   # verifica a estrutura do repositório
```

## Onde está o plano

- `docs/plan/README.md` — prompt de arranque para o agente e índice das fases
- `docs/plan/STATUS.md` — estado de cada tarefa
- `docs/plan/01-protocolo.md` — regras de trabalho (ler sempre)
- `docs/HUMAN_REQUESTS.md` — pedidos pendentes ao dono do produto
- `docs/spec/especificacao-v0.1.md` — especificação de produto
- `docs/PLANO_RAG_MULTINEGOCIO_v1.md` — ficheiro único do plano (fonte de verdade; a pasta `docs/plan/` é gerada a partir dele)

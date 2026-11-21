<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# PARTE B — Protocolo do agente

Lê esta parte inteira antes de qualquer tarefa. É curta de propósito.

## B1. Prompt de arranque (copiar e colar no início de cada sessão)

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

Na versão de ficheiro único deste plano: "protocolo" = Parte B, "contexto global" = Parte C, "cartão" = o bloco da tarefa na Parte D.

## B2. Regras de trabalho

1. **Uma tarefa por sessão.** Não começas outra sem terminar ou bloquear a atual.
2. **Âmbito fechado.** Só alteras os ficheiros listados em "Criar/alterar". Se precisares de tocar noutro, justifica no resumo (no máximo 2 ficheiros extra e pequenos). Mudança maior → pára e pede (B5).
3. **Contratos congelados.** Não alteras as interfaces da C6 nem o esquema da C7 sem uma ADR aprovada pelo OLEK.
4. **Dependências.** Só adicionas as bibliotecas indicadas no cartão. Qualquer outra exige verificar a licença (C4) e registar no resumo.
5. **Código.** Python 3.12, síncrono, tipado (mypy strict em `rag_core`), ruff. TypeScript em modo strict. Nomes de código em inglês; textos para o utilizador em PT-PT.
6. **Segredos.** Nunca em código, testes, fixtures, logs ou mensagens de commit. Usa `.env.local` (ignorado pelo git); `.env.example` só tem nomes.
7. **Segurança não se desliga.** Nunca desativas CSP, RLS, validação de token, sandbox ou filtros para "fazer funcionar".
8. **Git.** Ramo `task/<ID>-<slug>`; commits pequenos com mensagem `<ID>: <resumo>`; PR com o template G4.
9. **Tarefa maior do que parece** (mais de ~10 ficheiros ou passos não previstos) → pára e propõe dividir.

## B3. Definição de Concluído (DoD) global — vale para todas as tarefas

- [ ] Todos os testes listados no cartão existem e passam; `make lint` e `make test` verdes.
- [ ] Cobertura do código novo ≥ 85% em Python (core e serviços) e ≥ 70% em TypeScript.
- [ ] Nenhum teste existente foi apagado, enfraquecido ou marcado `skip` sem um HR aprovado.
- [ ] Sem segredos (gitleaks), sem novos alertas de semgrep/audit, licenças dentro da allowlist.
- [ ] Cada invariante tocado (C5) tem pelo menos um teste com prefixo `test_invNN_`.
- [ ] Funções públicas com docstring; README do pacote atualizado se o uso mudou; ADR se houve desvio.
- [ ] `docs/plan/STATUS.md` atualizado e resumo final escrito (B7).

## B4. Regras de testes (anti-batota)

- Os testes descrevem **comportamento**, não implementação. Um comportamento por teste, com nome descritivo.
- **Proibido:** alterar um teste para coincidir com um bug; `assert True`; apanhar exceções para esconder falhas; fazer mock da própria unidade em teste; copiar valores esperados da saída do código sem os verificar à mão.
- Usa os **fakes da C10** em vez de mocks improvisados sempre que existam.
- Testes unitários: sem rede, sem Docker, menos de 1 s cada (excecionalmente 5 s).
- Se achares que um teste do cartão está errado, **não o mudes**: abre um HR com a explicação.
- Testes de segurança usam **canários** (C11) e verificam a sua **ausência** em logs, prompts, respostas e pedidos HTTP.
- Determinismo: nada de `sleep` para sincronizar (usa `FakeClock` ou eventos), nada de dependência da ordem dos testes, seeds fixas.

## B5. Pedir ajuda ao OLEK

**Quando:** (a) falta uma conta, chave, domínio ou acesso; (b) é precisa uma decisão de produto, negócio ou legal; (c) o cartão é ambíguo ou contraditório; (d) um teste do cartão parece errado; (e) é preciso hardware físico (Máquina 1/2) ou uma ação manual num painel; (f) há custos.

**Como:**
1. Cria ou atualiza a entrada em `docs/HUMAN_REQUESTS.md` com o formato G3. Os pedidos previstos na Parte E já têm ID (`HR-01`…); para pedidos novos usa o próximo número livre.
2. Pergunta no chat com o mesmo texto, curto e, se possível, com opções. Se tiveres uma ferramenta de perguntas ao utilizador, usa-a.
3. **Segredos nunca no chat.** Pede para os colocar em `.env.local` ou no gestor de segredos com o nome exato da variável, e para responder "feito".
4. **Enquanto esperas:** se o pedido for bloqueante, marca a tarefa ⛔ no `STATUS.md` com o ID do HR e passa a outra tarefa desbloqueada. Se não for bloqueante, continua com um fake/stub e deixa `TODO(HR-xxx)` no código.
5. Nunca inventes valores, nunca uses contas tuas, nunca contornes o pedido.

## B6. Quando algo não bate certo

- O cartão contradiz a Parte C → **a Parte C prevalece**; regista no resumo e abre um HR.
- Uma biblioteca não se comporta como o cartão diz → tenta o "Plano B" indicado nas Armadilhas; se não houver, pára e abre um HR.
- Queres mudar o desenho → escreve uma ADR em `docs/adr/NNNN-titulo.md` (template G2) com estado "proposta" e abre um HR para aprovação. Não implementes antes da aprovação.

## B7. STATUS.md e resumo final

`docs/plan/STATUS.md` tem uma linha por tarefa: `| ID | Título | Estado | Ramo/PR | Notas |`.
Estados: ⬜ por fazer · 🟨 em curso · ✅ concluída · ⛔ bloqueada (HR-xxx).

Resumo final (no chat e na descrição do PR):

```text
Tarefa: F3-T06 — concluída
Ficheiros: packages/core/rag_core/parsing/pdf_lite.py, packages/core/tests/parsing/test_pdf_lite.py
Testes: 11 novos, todos verdes (uv run pytest packages/core/tests/parsing -q)
Invariantes cobertos: INV-12
Desvios/decisões: nenhum
Pedidos humanos: nenhum
Próxima tarefa sugerida: F3-T07
```

---

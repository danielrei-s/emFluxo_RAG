<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# PARTE D — Roadmap: fases e cartões de tarefa

## D0. Mapa das fases

| Fase | Nome | Tarefas | Depende de | Marco |
|---|---|---|---|---|
| F0 | Fundações do repositório | 12 | — | |
| F1 | Contratos do core e fakes | 5 | F0 | |
| F2 | Corpus sintético e golden set | 2 | F1 | |
| F3 | Ingestão (core) | 13 | F2 | |
| F4 | Recuperação e geração (core) | 8 | F3 | |
| F5 | Store local, modelos reais, CLI e avaliação | 5 | F4 | **M1** |
| F6 | Inference Gateway | 8 | F4, F5 | **M2** |
| F7 | BD central, tenancy e identidade | 7 | F5, F6 | |
| F8 | Central API | 12 | F7 | |
| F9 | Back-office e extensibilidade (API) | 3 | F8 | **M3** |
| F10 | Aplicações web (Portal + UI do back-office) | 10 | F9 | **M4** |
| F11 | Motor local (Produto B) | 12 | F5 (T01–T07); F8, F10 (T08–T12) | |
| F12 | App desktop Tauri (Produto B) | 6 | F11 | **M5** |
| F13 | Endurecimento e prontidão para piloto | 8 | F10, F12 | **M6** |
| F14 | Piloto real | 4 | F13 | |
| F15 | Conectores cloud (ondas) | 6 | F14 | |
| F16 | Email: pesquisa (ondas) | 5 | F15 | |
| F17 | Email: rascunhos assistidos (ondas) | 4 | F16 | |
| F18 | Plataforma multi-negócio (ondas) | 8 | F13 | |

**Tamanhos:** S ≤ 3 h · M ½–1 dia · L 1–2 dias.
**Formato dos cartões:** Objetivo · Depende de · Ler antes · Criar/alterar · Passos · Testes · DoD específico · Humano · (Armadilhas · Não fazer). Template na Parte G1.
**Regra das fases:** nenhuma fase começa sem o gate da anterior verde (testes, invariantes da fase e, quando indicado, aprovação do OLEK).
**Paralelismo:** tarefas cujas dependências já estão ✅ podem ser feitas ao mesmo tempo por agentes diferentes, em ramos separados (ex.: F3-T04, F3-T05, F3-T06 e F3-T07 só dependem de F3-T03). Cada agente continua a fazer uma tarefa de cada vez.

**Primeira semana (sugestão):** F0-T01 → F0-T02/T03 → F0-T04/T05 → F0-T06/T07 → F0-T08…T12 → F1-T01…T05 → F2-T01. No fim há um repositório com CI de segurança, contratos de código, fakes e o corpus sintético — a base para tudo o resto ser feito com testes primeiro.

### F0 — Fundações do repositório

**Objetivo:** repositório, ferramentas, CI de segurança, configuração e logging sem conteúdo. Nenhuma funcionalidade de produto.
**Gate da fase:** `make lint test security` verde no CI; compose de desenvolvimento arranca; ADRs iniciais escritas.

- [F0-T01 · Criar o monorepo e a estrutura de pastas](tarefas/F0-T01.md)
- [F0-T02 · Ferramentas Python (workspace uv, ruff, mypy, pytest)](tarefas/F0-T02.md)
- [F0-T03 · Ferramentas JS/TS (pnpm, TypeScript strict, ESLint, Prettier, Vitest)](tarefas/F0-T03.md)
- [F0-T04 · Makefile com alvos padrão](tarefas/F0-T04.md)
- [F0-T05 · Primitivas comuns (ids, relógio, erros)](tarefas/F0-T05.md)
- [F0-T06 · Configuração tipada (`rag_core.config`)](tarefas/F0-T06.md)
- [F0-T07 · Logging sem conteúdo (`rag_core.logging`)](tarefas/F0-T07.md)
- [F0-T08 · Verificação de licenças por perfil](tarefas/F0-T08.md)
- [F0-T09 · Pre-commit e deteção de segredos local](tarefas/F0-T09.md)
- [F0-T10 · CI no GitHub Actions](tarefas/F0-T10.md)
- [F0-T11 · Docker Compose de desenvolvimento](tarefas/F0-T11.md)
- [F0-T12 · ADRs iniciais e documentos base](tarefas/F0-T12.md)

### F1 — Contratos do core e fakes

**Objetivo:** tipos, interfaces, política de acesso e fakes determinísticos, para que todo o desenvolvimento seguinte seja guiado por testes.
**Gate da fase:** suite de contrato de `VectorStore` verde contra `InMemoryVectorStore`; tabela de verdade da política verde.

- [F1-T01 · Modelos de domínio (`rag_core.types`)](tarefas/F1-T01.md)
- [F1-T02 · Interfaces (`rag_core.interfaces`)](tarefas/F1-T02.md)
- [F1-T03 · Política de acesso (`rag_core.policy`)](tarefas/F1-T03.md)
- [F1-T04 · Fakes determinísticos (`rag_core.fakes`)](tarefas/F1-T04.md)
- [F1-T05 · Suite de contrato de `VectorStore`](tarefas/F1-T05.md)

### F2 — Corpus sintético e golden set

**Objetivo:** dados de teste realistas e reprodutíveis (duas empresas fictícias) e o golden set que mede a qualidade.
**Gate da fase:** manifest consistente; golden set valida contra o manifest; OLEK reviu as perguntas (não bloqueante).

- [F2-T01 · Gerador do corpus sintético](tarefas/F2-T01.md)
- [F2-T02 · Golden set v0 e validador](tarefas/F2-T02.md)

### F3 — Ingestão (core)

**Objetivo:** transformar ficheiros em chunks seguros e bem estruturados, com os dois perfis de parsing, sandbox e ingestão incremental.
**Gate da fase:** todos os factos do manifest aparecem em algum chunk (exceto OCR com OCR desligado); canários ocultos nunca aparecem; ficheiros inválidos falham com o código certo; logs sem conteúdo.

- [F3-T01 · Deteção de tipo e validação de ficheiros](tarefas/F3-T01.md)
- [F3-T02 · Sanitização de texto e deteção de prompt injection](tarefas/F3-T02.md)
- [F3-T03 · Base dos parsers, registo e formatos de texto (TXT, MD, CSV, HTML)](tarefas/F3-T03.md)
- [F3-T04 · Parser DOCX (lite)](tarefas/F3-T04.md)
- [F3-T05 · Parsers XLSX e PPTX (lite)](tarefas/F3-T05.md)
- [F3-T06 · Parser PDF (lite)](tarefas/F3-T06.md)
- [F3-T07 · Parser de email (EML)](tarefas/F3-T07.md)
- [F3-T08 · OCR opcional (extra `ocr`)](tarefas/F3-T08.md)
- [F3-T09 · Adaptador Docling (perfil full, central)](tarefas/F3-T09.md)
- [F3-T10 · Sandbox de parsing (subprocesso com limites)](tarefas/F3-T10.md)
- [F3-T11 · Chunker estrutural](tarefas/F3-T11.md)
- [F3-T12 · Montagem de chunks (metadados, hashes, idioma, flags)](tarefas/F3-T12.md)
- [F3-T13 · Serviço de ingestão incremental](tarefas/F3-T13.md)

### F4 — Recuperação e geração (core)

**Objetivo:** pesquisa híbrida, seleção de contexto, prompt seguro, validação de citações, filtro de saída, redação de PII e o orquestrador de conversa.
**Gate da fase:** testes de INV-01, 02, 05, 06, 07, 08 e 17 verdes com fakes; o teste com LLM "obediente" (red team mínimo) passa.

- [F4-T01 · Pesquisa híbrida com fusão RRF](tarefas/F4-T01.md)
- [F4-T02 · Rerank, limiar de relevância e seleção final](tarefas/F4-T02.md)
- [F4-T03 · Construtor de prompt](tarefas/F4-T03.md)
- [F4-T04 · Validador de citações e política de resposta](tarefas/F4-T04.md)
- [F4-T05 · Filtro de saída (servidor)](tarefas/F4-T05.md)
- [F4-T06 · Tratamento da pergunta (limites, condensação, sinalização)](tarefas/F4-T06.md)
- [F4-T07 · Redação de PII portuguesa com reidratação](tarefas/F4-T07.md)
- [F4-T08 · Serviço de conversa (orquestrador, com e sem streaming)](tarefas/F4-T08.md)

### F5 — Store local, modelos reais, CLI e avaliação · Marco M1

**Objetivo:** store SQLite persistente, adaptadores de modelos reais, CLI `rag` e o harness de avaliação; escolher os modelos com dados.
**Gate da fase (M1):** com os modelos escolhidos, no golden set da Aurora: Recall@5 ≥ 0,80; `leak_rate` = 0; taxa de fallback por citação inválida ≤ 10%; respostas com o conteúdo esperado ≥ 75% nas perguntas respondíveis; TTFT medido e registado. ADR-0009 aprovada pelo OLEK.

- [F5-T01 · Store SQLite (CLI e base do motor local)](tarefas/F5-T01.md)
- [F5-T02 · Adaptadores de modelos reais e registo de modelos](tarefas/F5-T02.md)
- [F5-T03 · CLI `rag`](tarefas/F5-T03.md)
- [F5-T04 · Harness de avaliação](tarefas/F5-T04.md)
- [F5-T05 · Benchmark e escolha de modelos (com o OLEK)](tarefas/F5-T05.md)

### F6 — Inference Gateway · Marco M2

**Objetivo:** serviço entre as apps e os fornecedores de LLM: autenticação, quotas, rate limit, escolha de modelo, fallback, redação opcional e logging só de metadados.
**Gate da fase (M2):** testes de INV-03, 09, 14 e 24 verdes; gateway acessível em staging através do Cloudflare Tunnel (confirmação do OLEK).

- [F6-T01 · Esqueleto do serviço](tarefas/F6-T01.md)
- [F6-T02 · Autenticação por JWT (JWKS)](tarefas/F6-T02.md)
- [F6-T03 · Políticas por tenant, quotas e rate limit](tarefas/F6-T03.md)
- [F6-T04 · Escolha de modelo, timeouts e fallback](tarefas/F6-T04.md)
- [F6-T05 · Endpoint `/v1/chat/completions` (subconjunto compatível com OpenAI)](tarefas/F6-T05.md)
- [F6-T06 · Redação no gateway para fornecedores externos](tarefas/F6-T06.md)
- [F6-T07 · Deploy do gateway na Máquina 1 (staging)](tarefas/F6-T07.md)
- [F6-T08 · Fornecedor Hugging Face (opcional, fallback)](tarefas/F6-T08.md)

### F7 — BD central, tenancy e identidade

**Objetivo:** esquema Postgres com RLS forçado, camada de acesso com contexto de tenant, `PgVectorStore`, resolução do Principal, auditoria imutável e fila de jobs.
**Gate da fase:** suite de isolamento (INV-01) 100% verde, incluindo o teste de catálogo "todas as tabelas com RLS forçado"; filtro SQL = política Python (INV-02); auditoria append-only (INV-16).
**Notas comuns:** testes de integração com `testcontainers` e `pgvector/pgvector:pg17`; fixture de sessão que aplica as migrações e cria as roles `anon` e `authenticated` (para imitar o Supabase); cada teste corre numa transação revertida ou numa base limpa.

- [F7-T01 · Runner de migrações, schemas, extensões e roles](tarefas/F7-T01.md)
- [F7-T02 · Esquema de tenancy com RLS forçado](tarefas/F7-T02.md)
- [F7-T03 · Camada de acesso à BD com contexto de tenant](tarefas/F7-T03.md)
- [F7-T04 · Documentos, chunks e `PgVectorStore`](tarefas/F7-T04.md)
- [F7-T05 · Verificação de identidade e resolução do Principal](tarefas/F7-T05.md)
- [F7-T06 · Auditoria append-only com cadeia de hashes](tarefas/F7-T06.md)
- [F7-T07 · Fila de jobs em Postgres e worker](tarefas/F7-T07.md)

### F8 — Central API

**Objetivo:** API do repositório central (documentos, pesquisa federada, chat do Produto A, dispositivos, administração do tenant), worker de ingestão com parsing sem rede, encriptação por tenant e staging.
**Gate da fase:** isolamento entre tenants e ACL verdes em todos os endpoints (canários); todos os acessos auditados; eliminação propaga-se (INV-18); smoke em staging verde.

- [F8-T01 · Esqueleto da Central API, chaves de assinatura e JWKS](tarefas/F8-T01.md)
- [F8-T02 · API de documentos (upload, listagem, detalhe, ACL, conteúdo, eliminação)](tarefas/F8-T02.md)
- [F8-T03 · Worker de ingestão e contentor de parsing sem rede](tarefas/F8-T03.md)
- [F8-T04 · Cliente do gateway](tarefas/F8-T04.md)
- [F8-T05 · Pesquisa federada, chat do Produto A e conversas](tarefas/F8-T05.md)
- [F8-T06 · Endpoints internos para o gateway](tarefas/F8-T06.md)
- [F8-T07 · Registo de dispositivos, licença e kill switch (servidor)](tarefas/F8-T07.md)
- [F8-T08 · Encriptação envelope dos originais por tenant](tarefas/F8-T08.md)
- [F8-T09 · Retenção, exportação e eliminação de tenant](tarefas/F8-T09.md)
- [F8-T10 · Endpoints de administração do tenant](tarefas/F8-T10.md)
- [F8-T11 · Deploy da plataforma central em staging](tarefas/F8-T11.md)
- [F8-T12 · (Condicional) Fluxo próprio de autorização da app desktop](tarefas/F8-T12.md)

### F9 — Back-office e extensibilidade (API) · Marco M3

**Objetivo:** API do back-office (nossa equipa), registo de módulos com feature flags e branding por tenant.
**Gate da fase (M3):** INV-15, INV-20 e INV-23 verdes; staging com um tenant criado pelo back-office.

- [F9-T01 · API do back-office](tarefas/F9-T01.md)
- [F9-T02 · Registo de módulos e feature flags](tarefas/F9-T02.md)
- [F9-T03 · Branding por tenant](tarefas/F9-T03.md)

### F10 — Aplicações web (Portal do Produto A e UI do back-office) · Marco M4

**Objetivo:** portal Next.js (BFF) com chat em streaming, documentos e administração; UI do back-office; página de autorização da app desktop; deploy na Vercel (região UE).
**Gate da fase (M4):** e2e verdes em staging; CSP e cabeçalhos verificados no URL publicado; região UE confirmada; INV-08 verde na UI.

- [F10-T01 · Esqueleto Next.js, BFF, autenticação e cabeçalhos de segurança](tarefas/F10-T01.md)
- [F10-T02 · Cliente TypeScript gerado do OpenAPI](tarefas/F10-T02.md)
- [F10-T03 · Componentes de chat partilhados e renderização segura (`packages/ui`)](tarefas/F10-T03.md)
- [F10-T04 · Página de chat com streaming](tarefas/F10-T04.md)
- [F10-T05 · Gestão de documentos](tarefas/F10-T05.md)
- [F10-T06 · Administração do tenant](tarefas/F10-T06.md)
- [F10-T07 · Acessibilidade, estados de erro e responsivo](tarefas/F10-T07.md)
- [F10-T08 · Página de autorização da app desktop (OAuth 2.1)](tarefas/F10-T08.md)
- [F10-T09 · UI do back-office](tarefas/F10-T09.md)
- [F10-T10 · Deploy na Vercel (região UE)](tarefas/F10-T10.md)

### F11 — Motor local (Produto B)

**Objetivo:** serviço Python local com proteção de loopback, índice encriptado, consentimento por pasta e documento, FileGate, indexação incremental, modos híbrido e offline, login, licença e kill switch, empacotado para Windows, macOS e Linux.
**Gate da fase:** INV-04, 05, 10, 11, 13 e 18 verdes; revogação remove dados em < 1 min; binário empacotado passa o `--selftest` nos três sistemas.
**Nota:** T01–T07 só dependem do core (podem começar depois da F5); T08–T12 precisam da Central API (F8) e da página de consentimento (F10-T08).

- [F11-T01 · Esqueleto do motor com proteção de loopback](tarefas/F11-T01.md)
- [F11-T02 · Armazenamento local encriptado (SQLCipher + keychain do SO)](tarefas/F11-T02.md)
- [F11-T03 · Modelo de workspaces e consentimento](tarefas/F11-T03.md)
- [F11-T04 · FileGate — único ponto de leitura de ficheiros do utilizador](tarefas/F11-T04.md)
- [F11-T05 · API de workspaces: pré-visualização, aprovação e políticas](tarefas/F11-T05.md)
- [F11-T06 · Observação de pastas e indexação incremental](tarefas/F11-T06.md)
- [F11-T07 · Chat local e registo de transparência](tarefas/F11-T07.md)
- [F11-T08 · Login da app e registo do dispositivo (cliente)](tarefas/F11-T08.md)
- [F11-T09 · Modo híbrido: pesquisa federada, redação e gateway](tarefas/F11-T09.md)
- [F11-T10 · Modo offline (LLM local)](tarefas/F11-T10.md)
- [F11-T11 · Políticas, licença offline e kill switch (cliente)](tarefas/F11-T11.md)
- [F11-T12 · Empacotamento do motor (PyInstaller) e orçamento de tamanho](tarefas/F11-T12.md)

### F12 — App desktop (Tauri v2) · Marco M5

**Objetivo:** shell Tauri que arranca o motor, UI de login, consentimento, chat e transparência, atualizações assinadas e instaladores.
**Gate da fase (M5):** instaladores Windows e macOS gerados no CI; e2e de consentimento e chat verdes; verificações de segurança da app verdes.

- [F12-T01 · Esqueleto Tauri v2 com CSP e capacidades mínimas](tarefas/F12-T01.md)
- [F12-T02 · Ciclo de vida do motor (sidecar, em Rust)](tarefas/F12-T02.md)
- [F12-T03 · UI: login, onboarding e consentimento de pastas](tarefas/F12-T03.md)
- [F12-T04 · UI: chat, citações locais e painel de transparência](tarefas/F12-T04.md)
- [F12-T05 · Atualizações assinadas e pipeline de release](tarefas/F12-T05.md)
- [F12-T06 · Verificações de segurança da app (pentest interno automatizado)](tarefas/F12-T06.md)

### F13 — Endurecimento, observabilidade e prontidão para piloto · Marco M6

**Objetivo:** red team contínuo, cobertura de invariantes, observabilidade sem conteúdo, backups testados, testes de carga, gate de segurança, runbooks e pacote legal.
**Gate da fase (M6):** todos os gates verdes; `docs/plan/invariants_pending.txt` vazio; HR-19 e HR-20 resolvidos ou risco aceite por escrito pelo OLEK.

- [F13-T01 · Suite de red team no CI](tarefas/F13-T01.md)
- [F13-T02 · Cobertura de invariantes](tarefas/F13-T02.md)
- [F13-T03 · Observabilidade sem conteúdo](tarefas/F13-T03.md)
- [F13-T04 · Backups encriptados e teste de restauro](tarefas/F13-T04.md)
- [F13-T05 · Testes de carga e capacidade](tarefas/F13-T05.md)
- [F13-T06 · Gate de revisão de segurança](tarefas/F13-T06.md)
- [F13-T07 · Runbooks e documentação de produto](tarefas/F13-T07.md)
- [F13-T08 · Pacote legal (rascunhos para validação)](tarefas/F13-T08.md)

### F14 — Piloto real

**Objetivo:** validar valor e usabilidade com 1–2 clientes (idealmente um por produto).
**Gate da fase:** satisfação ≥ 4/5; respostas úteis ≥ 75%; zero incidentes de segurança.

- [F14-T01 · Preparar o ambiente do piloto](tarefas/F14-T01.md)
- [F14-T02 · Golden set com o cliente](tarefas/F14-T02.md)
- [F14-T03 · Ciclo de afinação guiado por avaliação](tarefas/F14-T03.md)
- [F14-T04 · Relatório semanal do piloto](tarefas/F14-T04.md)

### F15 — Conectores cloud (planeamento por ondas)

**Objetivo:** importar documentos e permissões de Google Drive, OneDrive/SharePoint e (opcionalmente) Dropbox, com sincronização incremental.
**Gate da fase:** permissões da origem refletidas em < 15 min; revogação na origem retira o acesso no chat.

- [F15-T00 · Refinar a fase em cartões detalhados](tarefas/F15-T00.md)
- [F15-T01 · Interface `Connector` e motor de sincronização](tarefas/F15-T01.md)
- [F15-T02 · Conector Google Drive](tarefas/F15-T02.md)
- [F15-T03 · Conector OneDrive/SharePoint (Microsoft Graph)](tarefas/F15-T03.md)
- [F15-T04 · Conector Dropbox (opcional)](tarefas/F15-T04.md)
- [F15-T05 · UI de fontes e estado de sincronização](tarefas/F15-T05.md)

### F16 — Email: pesquisa (planeamento por ondas)

**Objetivo:** indexar emails (Gmail, Microsoft 365, IMAP) e anexos, tratando emails externos como conteúdo hostil.
**Gate da fase:** suite de injection via email sem sucessos; scopes só de leitura.

- [F16-T00 · Refinar a fase em cartões detalhados](tarefas/F16-T00.md)
- [F16-T01 · Conector Gmail](tarefas/F16-T01.md)
- [F16-T02 · Conector Microsoft 365 Mail](tarefas/F16-T02.md)
- [F16-T03 · Conector IMAP genérico](tarefas/F16-T03.md)
- [F16-T04 · Emails externos como não confiáveis e suite de injection](tarefas/F16-T04.md)

### F17 — Email: rascunhos assistidos (planeamento por ondas)

**Objetivo:** o assistente propõe respostas que ficam como rascunho na caixa do utilizador; enviar exige sempre clique humano.
**Gate da fase:** impossível enviar sem aprovação (teste); auditoria por rascunho.

- [F17-T00 · Refinar a fase em cartões detalhados](tarefas/F17-T00.md)
- [F17-T01 · Geração de rascunhos](tarefas/F17-T01.md)
- [F17-T02 · Guardar o rascunho na caixa](tarefas/F17-T02.md)
- [F17-T03 · Garantias de não-envio](tarefas/F17-T03.md)

### F18 — Plataforma multi-negócio (planeamento por ondas)

**Objetivo:** perfis de setor, templates de documentos com branding, primeiros módulos verticais, faturação, domínios próprios, widget e ferramentas controladas.
**Gate da fase:** cada módulo com testes próprios, incluindo isolamento entre tenants; `check_core_agnostic.py` verde.

- [F18-T00 · Refinar a fase em cartões detalhados](tarefas/F18-T00.md)
- [F18-T01 · Perfis de setor](tarefas/F18-T01.md)
- [F18-T02 · Motor de templates de documentos](tarefas/F18-T02.md)
- [F18-T03 · Primeiros módulos verticais](tarefas/F18-T03.md)
- [F18-T04 · Faturação e limites por plano](tarefas/F18-T04.md)
- [F18-T05 · Domínio próprio e white-label](tarefas/F18-T05.md)
- [F18-T06 · Widget incorporável](tarefas/F18-T06.md)
- [F18-T07 · Ferramentas do assistente por tenant](tarefas/F18-T07.md)

### Backlog (sem cartões)

GraphRAG para perguntas relacionais · ferramentas de calendário e CRM com aprovação humana · afinação LoRA para PT-PT e jargão de setor · instalação on-prem com GPU · certificação ISO 27001 · sincronização central → local para o modo offline · prova de posse do dispositivo (DPoP / assinatura de pedidos) · suporte a .msg no desktop · certificate pinning quando o gateway deixar de estar atrás da Cloudflare.



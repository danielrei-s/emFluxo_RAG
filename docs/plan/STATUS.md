<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# STATUS

Legenda: ⬜ por fazer · 🟨 em curso · ✅ concluída · ⛔ bloqueada (HR-xxx)

## F0 — Fundações do repositório

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F0-T01 | Criar o monorepo e a estrutura de pastas | ✅ | task/F0-T01-monorepo | HR-01 pendente (titular na LICENSE) |
| F0-T02 | Ferramentas Python (workspace uv, ruff, mypy, pytest) | ✅ | main | |
| F0-T03 | Ferramentas JS/TS (pnpm, TypeScript strict, ESLint, Prettier, Vitest) | ✅ | main | |
| F0-T04 | Makefile com alvos padrão | ✅ | main | `make help` e `make lint test` validados |
| F0-T05 | Primitivas comuns (ids, relógio, erros) | ✅ | main | |
| F0-T06 | Configuração tipada (`rag_core.config`) | ✅ | main | |
| F0-T07 | Logging sem conteúdo (`rag_core.logging`) | ✅ | main | |
| F0-T08 | Verificação de licenças por perfil | ✅ | main | Deps novas (dev): pip-licenses (MIT), PyYAML (MIT) |
| F0-T09 | Pre-commit e deteção de segredos local | ✅ | main | Dep nova (dev): pre-commit (MIT) |
| F0-T10 | CI no GitHub Actions | ✅ | main | CI verde no GitHub depende de HR-01 (branch protection); vitest 4 e pnpm endurecido por audit/semgrep |
| F0-T11 | Docker Compose de desenvolvimento | ✅ | main | Smoke com Docker validado (postgres + pgvector); HR-02 não bloqueante |
| F0-T12 | ADRs iniciais e documentos base | ✅ | main | ADR-0002, 0003 e 0005 aguardam leitura do OLEK |

## F1 — Contratos do core e fakes

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F1-T01 | Modelos de domínio (`rag_core.types`) | ✅ | main | |
| F1-T02 | Interfaces (`rag_core.interfaces`) | ✅ | main | |
| F1-T03 | Política de acesso (`rag_core.policy`) | ✅ | main | |
| F1-T04 | Fakes determinísticos (`rag_core.fakes`) | ✅ | main | Dep nova: rank-bm25 (Apache-2.0); BM25Plus em vez de Okapi (idf negativo em corpora pequenos) |
| F1-T05 | Suite de contrato de `VectorStore` | ✅ | main | Suite validada com InMemory e com um store que recusa origem local (ramo do PgVectorStore) |

## F2 — Corpus sintético e golden set

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F2-T01 | Gerador do corpus sintético | ✅ | 2026-11-22 | 15 docs + 6 inválidos em fixtures/corpus; manifest com sha256; Pillow MIT-CMU permitida em dev |
| F2-T02 | Golden set v0 e validador | ✅ | 2026-11-22 | 62 itens (55 aurora + 7 boreal), todas as categorias da C11; testing.corpus; HR-03 pendente (não bloqueante) |

## F3 — Ingestão (core)

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F3-T01 | Deteção de tipo e validação de ficheiros | ✅ | 2026-11-22 | sniff/detect_type/validate_file; extra lite = olefile; OLE2 mínimo construído nos testes |
| F3-T02 | Sanitização de texto e deteção de prompt injection | ✅ | 2026-11-22 | clean_text (Cc/Cf/Co/tags, NFC) e 9 regras de injection PT/EN; sem dependências novas |
| F3-T03 | Base dos parsers, registo e formatos de texto (TXT, MD, CSV, HTML) | ✅ | 2026-11-22 | parsing/{base,registry,text,html}; beautifulsoup4 no extra lite; cobertura 100% |
| F3-T04 | Parser DOCX (lite) | ✅ | 2026-11-22 | parsing/docx_lite; python-docx no extra lite; HIDDEN_FLAG movido para parsing.base |
| F3-T05 | Parsers XLSX e PPTX (lite) | ✅ | 2026-11-22 | parsing/xlsx_lite e pptx_lite; openpyxl + python-pptx no extra lite; aviso formula_without_cached_value via 2.ª leitura sem data_only |
| F3-T06 | Parser PDF (lite) | ✅ | 2026-11-22 | parsing/pdf_lite + hidden_text_spans; pdfplumber + pypdfium2 no extra lite; exceção de licença pypdfium2 (ADR 0006) |
| F3-T07 | Parser de email (EML) | ✅ | 2026-11-22 | parsing/eml; MSG levanta UnsupportedType no lite (HR-04 pendente, não bloqueante); sem dependências novas |
| F3-T08 | OCR opcional (extra `ocr`) | ✅ | 2026-11-22 | OcrEngine + RapidOcrEngine (hash verificado antes de carregar), ImageParser, OCR 200 DPI no PdfParser; plano B: modelos do wheel em models.yaml; HR-27 aberto |
| F3-T09 | Adaptador Docling (perfil full, central) | ✅ | 2026-11-22 | DoclingParser + full_registry (EML fica no lite p/ anexos); pré-filtro de ocultos em DOCX/HTML e pós-filtro em PDF; docling==2.151.1 no extra; 13 testes docling OK num venv temporário com modelos locais; licenças alargadas (MIT-CMU, CNRI-Python, BSL-1.0, LLVM-exception) |
| F3-T10 | Sandbox de parsing (subprocesso com limites) | ✅ | 2026-11-22 | ingestion/sandbox{,_worker,_env}; psutil; audit hook + vigilância RSS; test_config com lista branca de leitura do ambiente; RLIMIT_* (POSIX) só validado no CI |
| F3-T11 | Chunker estrutural | ✅ | 2026-11-22 | ingestion/chunking: ChunkDraft, chunk_document, embedding_text; 100% de cobertura; parágrafos grandes entram frase a frase para a sobreposição caber |
| F3-T12 | Montagem de chunks (metadados, hashes, idioma, flags) | ✅ | 2026-11-22 | ingestion/metadata: build_chunks, detect_language (langdetect, seed 0); langdetect como dependência base |
| F3-T13 | Serviço de ingestão incremental | ✅ | 2026-11-22 | ingestion/pipeline: IngestionService (ingest_file, delete, sync_workspace), anexos até profundidade 2 rastreados em memória (limitação documentada, F7 traz parent_doc_id); gate da F3 cumprido; corpus ingerido via sandbox real |

## F4 — Recuperação e geração (core)

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F4-T01 | Pesquisa híbrida com fusão RRF | ⬜ | | |
| F4-T02 | Rerank, limiar de relevância e seleção final | ⬜ | | |
| F4-T03 | Construtor de prompt | ⬜ | | |
| F4-T04 | Validador de citações e política de resposta | ⬜ | | |
| F4-T05 | Filtro de saída (servidor) | ⬜ | | |
| F4-T06 | Tratamento da pergunta (limites, condensação, sinalização) | ⬜ | | |
| F4-T07 | Redação de PII portuguesa com reidratação | ⬜ | | |
| F4-T08 | Serviço de conversa (orquestrador, com e sem streaming) | ⬜ | | |

## F5 — Store local, modelos reais, CLI e avaliação · Marco M1

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F5-T01 | Store SQLite (CLI e base do motor local) | ⬜ | | |
| F5-T02 | Adaptadores de modelos reais e registo de modelos | ⬜ | | |
| F5-T03 | CLI `rag` | ⬜ | | |
| F5-T04 | Harness de avaliação | ⬜ | | |
| F5-T05 | Benchmark e escolha de modelos (com o OLEK) | ⬜ | | |

## F6 — Inference Gateway · Marco M2

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F6-T01 | Esqueleto do serviço | ⬜ | | |
| F6-T02 | Autenticação por JWT (JWKS) | ⬜ | | |
| F6-T03 | Políticas por tenant, quotas e rate limit | ⬜ | | |
| F6-T04 | Escolha de modelo, timeouts e fallback | ⬜ | | |
| F6-T05 | Endpoint `/v1/chat/completions` (subconjunto compatível com OpenAI) | ⬜ | | |
| F6-T06 | Redação no gateway para fornecedores externos | ⬜ | | |
| F6-T07 | Deploy do gateway na Máquina 1 (staging) | ⬜ | | |
| F6-T08 | Fornecedor Hugging Face (opcional, fallback) | ⬜ | | |

## F7 — BD central, tenancy e identidade

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F7-T01 | Runner de migrações, schemas, extensões e roles | ⬜ | | |
| F7-T02 | Esquema de tenancy com RLS forçado | ⬜ | | |
| F7-T03 | Camada de acesso à BD com contexto de tenant | ⬜ | | |
| F7-T04 | Documentos, chunks e `PgVectorStore` | ⬜ | | |
| F7-T05 | Verificação de identidade e resolução do Principal | ⬜ | | |
| F7-T06 | Auditoria append-only com cadeia de hashes | ⬜ | | |
| F7-T07 | Fila de jobs em Postgres e worker | ⬜ | | |

## F8 — Central API

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F8-T01 | Esqueleto da Central API, chaves de assinatura e JWKS | ⬜ | | |
| F8-T02 | API de documentos (upload, listagem, detalhe, ACL, conteúdo, eliminação) | ⬜ | | |
| F8-T03 | Worker de ingestão e contentor de parsing sem rede | ⬜ | | |
| F8-T04 | Cliente do gateway | ⬜ | | |
| F8-T05 | Pesquisa federada, chat do Produto A e conversas | ⬜ | | |
| F8-T06 | Endpoints internos para o gateway | ⬜ | | |
| F8-T07 | Registo de dispositivos, licença e kill switch (servidor) | ⬜ | | |
| F8-T08 | Encriptação envelope dos originais por tenant | ⬜ | | |
| F8-T09 | Retenção, exportação e eliminação de tenant | ⬜ | | |
| F8-T10 | Endpoints de administração do tenant | ⬜ | | |
| F8-T11 | Deploy da plataforma central em staging | ⬜ | | |
| F8-T12 | (Condicional) Fluxo próprio de autorização da app desktop | ⬜ | | |

## F9 — Back-office e extensibilidade (API) · Marco M3

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F9-T01 | API do back-office | ⬜ | | |
| F9-T02 | Registo de módulos e feature flags | ⬜ | | |
| F9-T03 | Branding por tenant | ⬜ | | |

## F10 — Aplicações web (Portal do Produto A e UI do back-office) · Marco M4

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F10-T01 | Esqueleto Next.js, BFF, autenticação e cabeçalhos de segurança | ⬜ | | |
| F10-T02 | Cliente TypeScript gerado do OpenAPI | ⬜ | | |
| F10-T03 | Componentes de chat partilhados e renderização segura (`packages/ui`) | ⬜ | | |
| F10-T04 | Página de chat com streaming | ⬜ | | |
| F10-T05 | Gestão de documentos | ⬜ | | |
| F10-T06 | Administração do tenant | ⬜ | | |
| F10-T07 | Acessibilidade, estados de erro e responsivo | ⬜ | | |
| F10-T08 | Página de autorização da app desktop (OAuth 2.1) | ⬜ | | |
| F10-T09 | UI do back-office | ⬜ | | |
| F10-T10 | Deploy na Vercel (região UE) | ⬜ | | |

## F11 — Motor local (Produto B)

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F11-T01 | Esqueleto do motor com proteção de loopback | ⬜ | | |
| F11-T02 | Armazenamento local encriptado (SQLCipher + keychain do SO) | ⬜ | | |
| F11-T03 | Modelo de workspaces e consentimento | ⬜ | | |
| F11-T04 | FileGate — único ponto de leitura de ficheiros do utilizador | ⬜ | | |
| F11-T05 | API de workspaces: pré-visualização, aprovação e políticas | ⬜ | | |
| F11-T06 | Observação de pastas e indexação incremental | ⬜ | | |
| F11-T07 | Chat local e registo de transparência | ⬜ | | |
| F11-T08 | Login da app e registo do dispositivo (cliente) | ⬜ | | |
| F11-T09 | Modo híbrido: pesquisa federada, redação e gateway | ⬜ | | |
| F11-T10 | Modo offline (LLM local) | ⬜ | | |
| F11-T11 | Políticas, licença offline e kill switch (cliente) | ⬜ | | |
| F11-T12 | Empacotamento do motor (PyInstaller) e orçamento de tamanho | ⬜ | | |

## F12 — App desktop (Tauri v2) · Marco M5

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F12-T01 | Esqueleto Tauri v2 com CSP e capacidades mínimas | ⬜ | | |
| F12-T02 | Ciclo de vida do motor (sidecar, em Rust) | ⬜ | | |
| F12-T03 | UI: login, onboarding e consentimento de pastas | ⬜ | | |
| F12-T04 | UI: chat, citações locais e painel de transparência | ⬜ | | |
| F12-T05 | Atualizações assinadas e pipeline de release | ⬜ | | |
| F12-T06 | Verificações de segurança da app (pentest interno automatizado) | ⬜ | | |

## F13 — Endurecimento, observabilidade e prontidão para piloto · Marco M6

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F13-T01 | Suite de red team no CI | ⬜ | | |
| F13-T02 | Cobertura de invariantes | ⬜ | | |
| F13-T03 | Observabilidade sem conteúdo | ⬜ | | |
| F13-T04 | Backups encriptados e teste de restauro | ⬜ | | |
| F13-T05 | Testes de carga e capacidade | ⬜ | | |
| F13-T06 | Gate de revisão de segurança | ⬜ | | |
| F13-T07 | Runbooks e documentação de produto | ⬜ | | |
| F13-T08 | Pacote legal (rascunhos para validação) | ⬜ | | |

## F14 — Piloto real

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F14-T01 | Preparar o ambiente do piloto | ⬜ | | |
| F14-T02 | Golden set com o cliente | ⬜ | | |
| F14-T03 | Ciclo de afinação guiado por avaliação | ⬜ | | |
| F14-T04 | Relatório semanal do piloto | ⬜ | | |

## F15 — Conectores cloud (planeamento por ondas)

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F15-T00 | Refinar a fase em cartões detalhados | ⬜ | | |
| F15-T01 | Interface `Connector` e motor de sincronização | ⬜ | | |
| F15-T02 | Conector Google Drive | ⬜ | | |
| F15-T03 | Conector OneDrive/SharePoint (Microsoft Graph) | ⬜ | | |
| F15-T04 | Conector Dropbox (opcional) | ⬜ | | |
| F15-T05 | UI de fontes e estado de sincronização | ⬜ | | |

## F16 — Email: pesquisa (planeamento por ondas)

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F16-T00 | Refinar a fase em cartões detalhados | ⬜ | | |
| F16-T01 | Conector Gmail | ⬜ | | |
| F16-T02 | Conector Microsoft 365 Mail | ⬜ | | |
| F16-T03 | Conector IMAP genérico | ⬜ | | |
| F16-T04 | Emails externos como não confiáveis e suite de injection | ⬜ | | |

## F17 — Email: rascunhos assistidos (planeamento por ondas)

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F17-T00 | Refinar a fase em cartões detalhados | ⬜ | | |
| F17-T01 | Geração de rascunhos | ⬜ | | |
| F17-T02 | Guardar o rascunho na caixa | ⬜ | | |
| F17-T03 | Garantias de não-envio | ⬜ | | |

## F18 — Plataforma multi-negócio (planeamento por ondas)

| ID | Título | Estado | Ramo/PR | Notas |
|---|---|---|---|---|
| F18-T00 | Refinar a fase em cartões detalhados | ⬜ | | |
| F18-T01 | Perfis de setor | ⬜ | | |
| F18-T02 | Motor de templates de documentos | ⬜ | | |
| F18-T03 | Primeiros módulos verticais | ⬜ | | |
| F18-T04 | Faturação e limites por plano | ⬜ | | |
| F18-T05 | Domínio próprio e white-label | ⬜ | | |
| F18-T06 | Widget incorporável | ⬜ | | |
| F18-T07 | Ferramentas do assistente por tenant | ⬜ | | |

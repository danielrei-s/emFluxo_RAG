# Plataforma RAG Multi-Negócio — Especificação Técnica e Roadmap

> **Nota (2026-11-21):** esta é a Especificação v0.1, mantida como referência de produto. O roadmap (secção 7), os primeiros passos (secção 8) e as questões em aberto (secção 9) foram substituídos pelo *Plano de Implementação para Agentes v1.0* (`docs/plan/`). As correções da Parte A desse plano aplicam-se a esta especificação; em caso de conflito, **prevalece o plano**. Os agentes **não** leem esta especificação por inteiro (ignorar a secção 0): leem só a secção que o cartão da tarefa indica.

Versão 0.1 · Documento de referência para agentes de desenvolvimento

## 0. Como usar este documento

Este documento é a fonte de verdade para construir a plataforma. Cada secção explica **o quê**, **como** e **porquê**. Os agentes devem: (1) ler as secções 1 a 4 antes de qualquer tarefa; (2) respeitar os requisitos de segurança da secção 5 como obrigatórios (MUST), não como sugestões; (3) implementar por fases (secção 7), sem saltar critérios de aceitação; (4) registar qualquer desvio numa ADR (Architecture Decision Record) em `docs/adr/`.

Convenções: **MUST** = obrigatório; **SHOULD** = recomendado, desvio exige ADR; **MAY** = opcional.

## 1. Visão do produto

Uma plataforma de assistente conversacional (LLM + RAG) reutilizável para vários negócios. Cada empresa cliente obtém um assistente que combina conhecimento geral do modelo com conhecimento específico da empresa (documentos, emails, base de conhecimento) e responde sempre com citação das fontes.

A mesma base de código serve **dois produtos**:

### Produto A — Portal Web (SaaS)

- O cliente entra num portal web, autentica-se e conversa com um chatbot que conhece a sua empresa.
- Os documentos da empresa são carregados ou sincronizados para o **repositório central** do tenant, alojado na nossa cloud (região UE).
- Indicado para clientes que aceitam alojamento gerido na cloud e querem zero instalação.

### Produto B — Aplicação Local (Desktop / On-premises)

- Software instalado na máquina ou servidor do cliente. Quando ligado, o chatbot fica ativo.
- Tem acesso a **duas fontes de conhecimento**:
  1. O **repositório central** da empresa (o mesmo conhecimento do Produto A, se o cliente o tiver).
  2. Uma ou mais **pastas de workspace locais** escolhidas pelo utilizador.
- A app pede permissão explícita ao utilizador antes de ler a pasta e, de forma granular, antes de usar cada documento.
- Ficheiros, parsing, embeddings, índice vetorial e pesquisa ficam **sempre no cliente**.
- Apenas a inferência do LLM pode sair, porque o cliente normalmente não tem GPU. Vai para um endpoint gerido por nós (ex.: Hugging Face Inference Endpoints, região UE), enviando só a pergunta e os excertos estritamente necessários.
- Variante **100% offline** (MAY, para clientes de alta sensibilidade): o LLM corre também localmente (Ollama / llama.cpp / vLLM), sem qualquer tráfego externo.

### Princípios orientadores

1. **Os dados ficam o mais perto possível do cliente.** O que pode correr localmente corre localmente.
2. **Minimização de dados.** Para fora sai o mínimo indispensável, e isso é visível e auditável.
3. **Uma base, várias implantações.** Os componentes são os mesmos; muda a configuração (`deployment_mode: cloud | hybrid | offline`).
4. **Respostas com fontes ou nenhuma resposta.** Se não houver suporte nos documentos, o assistente diz que não sabe.
5. **Segurança por omissão** (secure by default), com isolamento total entre tenants.

## 2. Glossário

- **Tenant:** uma empresa cliente. Todo o dado pertence a exatamente um tenant.
- **Workspace:** um conjunto de fontes (pastas, conectores) dentro de um tenant, com as suas permissões.
- **Repositório central:** a base de conhecimento do tenant alojada na cloud (documentos, chunks, embeddings, metadados).
- **Chunk:** um fragmento de documento indexado, com metadados (origem, página, ACL, hash).
- **ACL:** a lista de utilizadores ou grupos com direito a ver um documento ou chunk.
- **Gateway de inferência:** um serviço nosso que recebe pedidos de geração, aplica políticas e os encaminha para o fornecedor de LLM.
- **Agente local:** o processo do Produto B que vigia pastas, indexa e pesquisa no dispositivo do cliente.

## 3. Arquitetura de alto nível

### 3.1 Componentes

| Componente | Responsabilidade | Produto A | Produto B |
| --- | --- | --- | --- |
| Ingestion Service | Ler ficheiros e emails, converter (Docling), fazer chunking e extrair metadados | Cloud | Local |
| Embedding Service | Gerar vetores (modelo multilingue que corre em CPU) | Cloud | Local |
| Vector + Keyword Store | Pesquisa híbrida (vetorial + BM25) | Cloud (Postgres+pgvector ou Qdrant) | Local (Qdrant embebido / LanceDB / SQLite-vec) |
| Retrieval & Rerank | Pesquisa, filtro por ACL, reranking | Cloud | Local |
| Orchestrator (RAG) | Montar o prompt, aplicar guardrails, gerir a conversa | Cloud | Local |
| Inference Gateway | Encaminhar para o LLM, aplicar quotas, redação e logging | Cloud | Cloud (ou local no modo offline) |
| Central Repository API | Servir conhecimento do tenant, com ACL | Cloud | Consumido pelo B via API |
| Identity (IdP) | Autenticação OIDC, SSO e MFA | Cloud | Cloud + cache local |
| Admin Portal | Gerir tenants, utilizadores, fontes e políticas | Cloud | Cloud |
| Audit Log | Registo imutável de acessos e ações | Cloud | Local + envio de metadados (sem conteúdo) |

### 3.2 Fluxo de uma pergunta — Produto A

1. O utilizador autentica-se (OIDC) e recebe um token com `tenant_id`, `user_id` e `groups`.
2. O Orchestrator recebe a pergunta e chama o Retrieval com o filtro obrigatório `tenant_id` + ACL do utilizador.
3. A pesquisa híbrida devolve os top-k candidatos, que são reordenados (rerank) para ficar com os top-n.
4. O prompt é montado com instruções de sistema e com os excertos delimitados e marcados como **dados não confiáveis**.
5. O Inference Gateway chama o LLM e a resposta passa por um validador de citações e um filtro de saída.
6. A resposta é devolvida com as fontes, e o evento é registado no Audit Log.

### 3.3 Fluxo de uma pergunta — Produto B (híbrido)

1. O utilizador abre a app local (sessão OIDC com PKCE e refresh token guardado no keychain do sistema operativo).
2. O agente local pesquisa **em paralelo**: (a) o índice local das pastas autorizadas e (b) o repositório central, via API autenticada que aplica a ACL no servidor.
3. Os resultados são fundidos (Reciprocal Rank Fusion) e reordenados localmente.
4. O Orchestrator local monta o prompt e aplica **redação de PII** configurável (ex.: NIF, IBAN, emails, telefones) antes do envio.
5. Só o prompt mínimo (pergunta + excertos selecionados) segue por TLS 1.3 para o Inference Gateway, que **não guarda o conteúdo** (zero-retention por omissão).
6. A resposta volta, as citações são validadas localmente e as entidades redigidas são re-hidratadas localmente, quando aplicável.
7. O utilizador vê, em qualquer momento, **o que foi enviado para fora** (painel de transparência).

### 3.4 Modo offline (Produto B, variante)

Igual ao 3.3, mas o passo 5 chama um LLM local (Ollama / llama.cpp) através da mesma interface `LLMProvider`. Sem tráfego externo, exceto atualizações assinadas, que também podem ser opcionais (instalação air-gapped).

### 3.5 Separação entre produtos (MUST)

Os dois produtos são **produtos distintos**, com licenças, builds e políticas separadas, que partilham recursos comuns.

**Partilhado por ambos:**

- A **base documental da empresa** (repositório central do tenant): documentos, chunks, embeddings, ACL. É a mesma fonte de verdade para web e local.
- O core (`core/`): ingestão, retrieval, orquestração, guardrails.
- A identidade (IdP), o Inference Gateway, a auditoria e o portal de administração.

**Exclusivo do Produto B (local):**

- Os **documentos próprios de trabalho** do utilizador, vindos das pastas a que deu acesso. Ficam só no dispositivo e **nunca** são carregados para o repositório central.
- O índice local, o file watcher, o fluxo de consentimento e o modo offline.

**Produto A (web):** acede **apenas** à base documental da empresa. Não tem, nem pode ter, acesso a pastas locais de qualquer utilizador.

| Fonte de conhecimento | Produto A (Web) | Produto B (Local) |
| --- | --- | --- |
| Conhecimento geral do LLM | ✔ | ✔ |
| Base documental da empresa (central) | ✔ | ✔ |
| Documentos próprios da pasta autorizada | ✖ | ✔ |

Regras de implementação:

1. A separação é feita por **entitlements** no token (`products: ["web"]`, `["local"]` ou ambos), validados no servidor.
2. O código exclusivo do B vive em `desktop-app/` e `local-engine/`, e o do A em `web-portal/`. O core não conhece nenhum dos produtos: recebe as fontes por configuração.
3. Os chunks locais levam `origin: local` e nunca são enviados para a Central API (há um teste automático que o garante).
4. Cada produto tem a sua própria documentação (`docs/product-web/` e `docs/product-local/`), e ambas repetem esta tabela.

## 4. Sistemas em detalhe

### 4.1 Pipeline de ingestão (comum aos dois produtos)

**Porquê:** a qualidade do RAG depende mais da ingestão do que do modelo. Um mau parsing ou chunking gera respostas erradas, por melhor que seja o LLM.

Etapas (MUST, por esta ordem):

1. **Descoberta:** listar os ficheiros da fonte (pasta, conector ou upload).
2. **Validação:** confirmar a extensão **e** o tipo real (magic bytes), rejeitar ficheiros acima do limite configurado e rejeitar ficheiros encriptados ou corrompidos com um erro claro.
3. **Sandbox:** o parsing corre num processo isolado, sem rede, com limites de CPU, memória e tempo. Porquê: os parsers de PDF/Office são uma superfície de ataque clássica.
4. **Conversão:** Docling para PDF, DOCX, PPTX, XLSX, HTML, imagens (com OCR) e emails EML/MSG, gerando um documento estruturado (títulos, tabelas, páginas).
5. **Limpeza e segurança do conteúdo:** remover texto invisível (letra branca, tamanho zero, caracteres Unicode de controlo/tag) e marcar padrões suspeitos de prompt injection (ver 5.6).
6. **Chunking estrutural:** cortar por secções e títulos (alvo de 300 a 800 tokens, sobreposição de 10 a 15%), preservar tabelas inteiras quando possível e incluir o caminho de títulos no chunk.
7. **Metadados obrigatórios por chunk:** `tenant_id`, `workspace_id`, `source_uri`, `doc_id`, `page`, `content_hash` (SHA-256), `acl` (users/groups), `classification` (public/internal/confidential/restricted), `language`, `ingested_at`, `parser_version`.
8. **Embeddings:** modelo multilingue que corre em CPU e suporta PT-PT (candidatos: `BAAI/bge-m3`, `intfloat/multilingual-e5-base`). A versão do modelo fica guardada com o vetor.
9. **Indexação:** índice vetorial + índice lexical (BM25/FTS).
10. **Incremental:** reindexar só o que mudou (por hash/mtime) e propagar eliminações (um ficheiro apagado ou com permissão revogada sai do índice em menos de 5 minutos).

### 4.2 Agente local — pastas de workspace (Produto B)

**Objetivo:** a app local observa uma ou mais pastas escolhidas pelo utilizador, entende cada documento conforme o seu tipo, avalia a relevância e usa-o nas respostas, **sempre com consentimento explícito**.

#### 4.2.1 Modelo de consentimento (MUST)

Três níveis, todos revogáveis a qualquer momento:

1. **Consentimento de pasta:** o utilizador escolhe a pasta através do seletor nativo do sistema operativo. A app nunca varre o disco por iniciativa própria. No macOS usa security-scoped bookmarks; no Windows, apenas os caminhos escolhidos.
2. **Pré-visualização e seleção:** antes de indexar, a app mostra a lista de ficheiros encontrados (nome, tipo, tamanho, classificação sugerida) e o utilizador marca o que autoriza. Por omissão, ficam excluídos padrões sensíveis: `.env`, chaves (`*.pem`, `*.key`, `id_rsa`), carteiras, bases de dados de passwords, `.git/` e pastas de sistema.
3. **Política de novos ficheiros:** o utilizador escolhe entre "perguntar sempre", "autorizar automaticamente os tipos X" ou "nunca". O padrão é **perguntar sempre**.

Estado por documento: `pending` → `approved` → `indexed` | `rejected` | `revoked`. Revogar remove os chunks e os embeddings do índice local e regista o evento.

O utilizador pode ainda marcar um documento como **"só local"**: nunca pode ser enviado como excerto para o LLM na cloud, nem sequer redigido. Nesse caso, perguntas que dependam dele só são respondidas no modo offline, ou então a app avisa o utilizador.

#### 4.2.2 Funcionamento

- **File watcher** (`watchdog` em Python ou `notify` em Rust) com debounce e fila persistente.
- **Classificador de relevância** na ingestão: gera um resumo curto e etiquetas por documento (localmente, com um modelo pequeno ou heurísticas) para permitir pesquisa em dois níveis: primeiro o documento, depois o chunk.
- **Na pergunta:** pesquisa híbrida no índice local, filtro por estado `approved`/`indexed`, rerank (cross-encoder pequeno em CPU, ex.: `bge-reranker-v2-m3`) e limiar mínimo de relevância. Abaixo do limiar, o documento não entra no contexto.
- **Painel de transparência:** para cada resposta, mostra quais documentos foram usados e **quais excertos saíram do dispositivo**.

#### 4.2.3 Stack recomendada para a app local

- **Shell:** Tauri (Rust + WebView), mais leve e com menor superfície de ataque do que o Electron. Alternativa: Electron, com `contextIsolation` e `sandbox` ativos.
- **Motor local:** serviço Python (FastAPI) empacotado (PyInstaller/Nuitka), a escutar **apenas** em `127.0.0.1` ou num named pipe / Unix socket, com token de sessão aleatório por arranque. Porquê: impede que outras apps ou páginas web no browser falem com o motor (DNS rebinding, CSRF local).
- **Armazenamento local:** índice vetorial embebido (LanceDB ou Qdrant local) + SQLite para metadados, **encriptados em repouso** (SQLCipher; chave no Keychain do macOS, DPAPI/Credential Manager no Windows, libsecret no Linux).
- **Atualizações:** assinadas (code signing + verificação de assinatura do updater), canal estável e canal beta.

### 4.3 Repositório central (Produtos A e B)

- **API:** REST/JSON (FastAPI) com OpenAPI, autenticação por OIDC e autorização por política (ver 5.3).
- **Armazenamento:** PostgreSQL com `pgvector` + FTS; ficheiros originais em object storage (S3-compatível, região UE) com encriptação por tenant.
- **Isolamento:** Row-Level Security no Postgres por `tenant_id` **e** filtro aplicado no código (defesa em profundidade). Clientes premium podem ter schema ou base de dados dedicados.
- **Endpoints principais:** `POST /search` (devolve chunks já filtrados por ACL), `POST /documents`, `DELETE /documents/{id}`, `GET /sources`, `POST /chat` (só Produto A).
- **Regra:** o Produto B **nunca** recebe chunks a que o utilizador não tem direito. O filtro de ACL é sempre aplicado no servidor e nunca confiado ao cliente.

### 4.4 Conectores (fase posterior)

Interface comum `Connector` com os métodos `list()`, `fetch(id)`, `permissions(id)`, `changes(since)`, `delete_events()`. Ordem sugerida: pasta local → upload web → Google Drive → OneDrive/SharePoint (Microsoft Graph) → Gmail → Microsoft 365 Mail → IMAP genérico. Cada conector **importa também as permissões** da origem e usa OAuth com os scopes mínimos (apenas leitura).

### 4.5 Integração com email (fase posterior)

Níveis, por ordem de risco crescente:

1. **Pesquisa:** os emails são indexados como documentos, com anexos tratados pelo pipeline 4.1.
2. **Rascunhos:** o assistente propõe uma resposta, que fica como rascunho na caixa do utilizador.
3. **Envio:** só com aprovação humana explícita por mensagem. **Proibido** o envio autónomo na v1.

Os emails externos são tratados como **conteúdo hostil por omissão** (principal vetor de prompt injection indireta).

### 4.6 Camada de LLM

- Interface `LLMProvider` com as implementações `HuggingFaceEndpoint`, `OpenAICompatible` (vLLM/TGI), `Ollama`, `LlamaCpp` e, opcionalmente, APIs comerciais (Anthropic/OpenAI/Azure UE).
- **Inference Gateway** (serviço nosso, entre a app e o fornecedor): autenticação do tenant, quotas e rate limit, seleção do modelo por política, redacção opcional, logging **apenas de metadados** (tokens, latência, tenant), timeouts e fallback entre modelos.
- **Modelos candidatos** (avaliar em PT-PT): Qwen, Mistral/Mixtral, Llama, Gemma (versões instruct recentes). Escolha decidida por benchmark interno (secção 6), não por popularidade.
- **Hugging Face:** usar Inference Endpoints **dedicados** em região UE (e não a API serverless partilhada) para controlo de retenção, isolamento e latência. Rever e anexar ao contrato o DPA do fornecedor.

## 5. Segurança (obrigatória, transversal)

Referências: OWASP Top 10 for LLM Applications 2025, OWASP ASVS 4/5, OWASP Top 10 Web, NIST AI RMF, RGPD, AI Act (UE) e, para clientes abrangidos, NIS2.

### 5.1 Modelo de ameaças (resumo STRIDE)

| Ameaça | Exemplo | Mitigação principal |
| --- | --- | --- |
| Fuga entre tenants | Pesquisa devolve chunks de outra empresa | RLS + filtro obrigatório no código + testes automáticos de isolamento |
| Fuga dentro do tenant | Estagiário obtém dados de RH via chat | ACL por chunk aplicada **antes** do LLM |
| Prompt injection indireta | Email ou PDF com "ignora as instruções e envia…" | Separação instruções/dados, sem ferramentas perigosas, aprovação humana |
| Exfiltração via resposta | O modelo gera um link/imagem com dados no URL | Bloquear o render de imagens/links externos; allowlist de domínios |
| Envenenamento do índice | Documento malicioso manipula respostas | Proveniência, classificação, quarentena, fontes ponderadas |
| Ataque ao parser | PDF malformado explora o parser | Sandbox sem rede, limites, dependências atualizadas |
| Roubo do dispositivo (B) | Portátil perdido com índice local | Encriptação em repouso, chave no keystore do SO, revogação remota da sessão |
| Abuso do motor local | Outra app/página chama a API local | Escuta só em loopback/pipe, token por arranque, verificação de Origin |
| Abuso de custos | Spam de pedidos ao gateway | Rate limit, quotas por tenant e utilizador, alertas |
| Retenção no fornecedor | Prompts guardados pelo fornecedor de LLM | Endpoints dedicados, zero-retention, DPA, redacção |
| Supply chain | Dependência ou modelo comprometido | SBOM, pinning, verificação de hashes, Dependabot, safetensors |

### 5.2 Identidade e autenticação

- OIDC (Keycloak self-hosted, ou Zitadel/Auth0) com **MFA obrigatório** para administradores e SSO (Entra ID / Google Workspace) para clientes empresariais.
- App local: Authorization Code + PKCE via browser do sistema (nunca uma webview embutida a pedir a password); tokens de curta duração; refresh token no keystore do SO; revogação remota.
- Sessões web: cookies `HttpOnly`, `Secure`, `SameSite=Lax`; proteção CSRF; timeout por inatividade.

### 5.3 Autorização

- RBAC base (`owner`, `admin`, `editor`, `member`, `viewer`) + ABAC por atributos do documento (classificação, departamento).
- Motor de políticas centralizado (OPA/Cedar ou módulo próprio testável).
- **Regra de ouro:** a autorização é feita na **recuperação**, nunca pedida ao LLM. O modelo só vê o que o utilizador já podia ver.

### 5.4 Proteção de dados

- **Em trânsito:** TLS 1.3; HSTS; certificate pinning na app local para o gateway e para o repositório (SHOULD).
- **Em repouso:** AES-256; chaves geridas em KMS (Vault, ou o KMS do fornecedor cloud), com uma chave por tenant (envelope encryption) para permitir crypto-shredding na saída do cliente.
- **Minimização:** só os top-n excertos vão para o LLM; limite de tokens de contexto; redacção de PII configurável por tenant (Microsoft Presidio + reconhecedores PT: NIF, NISS, CC, IBAN PT, telefones +351).
- **Retenção:** histórico de conversas configurável (0, 30, 90 dias); eliminação real, incluindo backups dentro da janela definida; exportação de dados do tenant.
- **Logs:** nunca registar conteúdo de prompts ou documentos em logs aplicacionais; apenas IDs, hashes e métricas.

### 5.5 Segurança da app local (Produto B)

- Princípio de menor privilégio: acesso apenas às pastas consentidas; sem privilégios de administrador após a instalação.
- Motor local em loopback ou named pipe, com token de sessão e validação de `Origin`/`Host`; CSP restrita na WebView.
- Binários assinados (Authenticode no Windows, notarização Apple no macOS); updater com verificação de assinatura; rollback seguro.
- Kill switch remoto: o admin do tenant pode revogar dispositivos, o que apaga as credenciais locais e bloqueia a sincronização.
- Opção de política empresarial (MDM): forçar modo offline, bloquear o envio de documentos "confidenciais" e fixar as pastas permitidas.

### 5.6 Defesas específicas de LLM

1. **Hierarquia de instruções:** o prompt de sistema define que o conteúdo recuperado é **dado, não instrução**; os excertos vão delimitados (ex.: `<document id=…>`), com escape de delimitadores dentro do conteúdo.
2. **Detecção de injection** na ingestão e na consulta (classificador leve + regras), com chunks suspeitos em quarentena ou com peso reduzido. Não é uma garantia, é uma camada.
3. **Sem ferramentas perigosas na v1:** o assistente não executa código, não envia emails nem chama URLs arbitrários. Ferramentas futuras: allowlist, parâmetros validados, confirmação humana para efeitos externos.
4. **Saída segura:** render de Markdown sanitizado; imagens e links externos bloqueados ou com confirmação; nunca interpretar a saída como HTML/JS.
5. **Grounding obrigatório:** cada afirmação factual da empresa deve citar um chunk existente; um validador confirma que as citações correspondem a chunks fornecidos e, se não houver fontes, responde "não encontrei nos documentos".
6. **Proteção do prompt de sistema:** não colocar segredos no prompt; assumir que pode vazar.
7. **Limites:** tamanho máximo da pergunta, do contexto e da resposta; rate limit; detecção de abuso.
8. **Red teaming contínuo:** suíte de ataques (injection, exfiltração, cross-tenant, jailbreak) a correr no CI.

### 5.7 Segurança de infraestrutura e desenvolvimento

- IaC (Terraform/OpenTofu), ambientes separados (dev/staging/prod), segredos num gestor de segredos (nunca no repositório).
- CI com SAST (Semgrep), análise de dependências (Dependabot/Renovate, `pip-audit`, `npm audit`), detecção de segredos (gitleaks), scan de imagens (Trivy), SBOM (Syft/CycloneDX).
- Contentores não-root, imagens mínimas, rede segmentada, WAF à frente do portal.
- Modelos apenas em formato `safetensors`, de fontes verificadas, com hash fixado.
- Backups encriptados, testados mensalmente; RPO de 24 h e RTO de 4 h na v1.
- Plano de resposta a incidentes com notificação RGPD em 72 h.

### 5.8 Conformidade

- **RGPD:** nós somos subcontratante (processor) e o cliente é o responsável pelo tratamento; DPA com cada cliente; lista pública de sub-subcontratantes (cloud, Hugging Face); dados na UE; DPIA modelo para os clientes; suporte aos direitos dos titulares (acesso, eliminação).
- **AI Act:** transparência (o utilizador sabe que fala com uma IA); documentação do sistema; o uso previsto não é de alto risco, mas cada novo setor de cliente deve ser reavaliado (ex.: saúde, RH).
- **Preparação para ISO 27001 / SOC 2** a partir da fase 4 (políticas, registos, controlo de acessos).

## 6. Qualidade e avaliação

**Porquê:** sem medição não dá para escolher modelos, chunking ou rerankers. Cada alteração deve ser comparada contra uma baseline.

- **Golden set** por tenant piloto: 50 a 200 perguntas reais com a resposta esperada e os documentos de suporte.
- **Métricas de recuperação:** Recall@k, MRR, nDCG.
- **Métricas de resposta:** fidelidade (faithfulness), relevância, precisão das citações e taxa de "não sei" correto (ferramentas: Ragas, DeepEval, promptfoo).
- **Métricas de segurança:** taxa de sucesso da suíte de ataques (alvo: 0 fugas entre tenants; 0 ações não autorizadas).
- **Operação:** latência p50/p95 (alvo p95 < 6 s no modo híbrido), custo por pergunta, feedback 👍/👎.
- Avaliação automática no CI: um PR que piore uma métrica acima do limiar não é integrado.

## 7. Roadmap por fases

Cada fase tem objetivo, entregáveis, critérios de aceitação (DoD) e a justificação da ordem. Nenhuma fase começa sem a anterior cumprir o DoD de segurança.

### Fase 0 — Fundações (1 a 2 semanas)

**Porquê primeiro:** decisões estruturais são caras de mudar depois.

- Monorepo: `core/` (ingestão, retrieval, orquestração), `gateway/`, `central-api/`, `web-portal/`, `desktop-app/`, `evals/`, `infra/`, `docs/adr/`.
- Python 3.12 + FastAPI + uv; frontend Next.js (portal) e Tauri (desktop).
- Docker Compose para desenvolvimento local: Postgres+pgvector, Qdrant, Ollama, Keycloak.
- CI com lint, testes, SAST, gitleaks e análise de dependências **desde o primeiro commit**.
- ADRs iniciais: escolha de vector store, modelo de embeddings, IdP e formato de metadados.
- **DoD:** `docker compose up` arranca tudo; o pipeline de CI está verde; a ameaça de modelo (5.1) foi revista.

### Fase 1 — Core RAG local (2 a 3 semanas)

**Porquê:** é o coração comum aos dois produtos; valida a qualidade antes de investir em produto.

- Pipeline 4.1 completo para PDF, DOCX, XLSX, PPTX, TXT/MD e EML/MSG (Docling), com sandbox.
- Embeddings multilingues em CPU; pesquisa híbrida; rerank; citações.
- Interface `LLMProvider` com Ollama (local) e endpoint compatível com OpenAI.
- CLI de teste: `ingest <pasta>` e `ask "pergunta"`.
- Golden set inicial (documentos fictícios ou de um piloto, com autorização) e primeiros evals.
- **DoD:** Recall@5 ≥ 0,8 no golden set; 100% das respostas com citações válidas ou "não sei"; parser isolado sem rede.

### Fase 2 — Inference Gateway + Hugging Face (1 a 2 semanas)

**Porquê:** desbloqueia o modo híbrido (cliente sem GPU) e centraliza custos e políticas.

- Gateway com autenticação por tenant, quotas, rate limit, logging só de metadados e fallback.
- Endpoint dedicado na Hugging Face (região UE); benchmark de 2 ou 3 modelos em PT-PT usando os evals.
- Redacção de PII (Presidio + reconhecedores PT) configurável.
- **DoD:** p95 < 6 s; zero conteúdo em logs (verificado por teste); quotas a funcionar; DPA do fornecedor revisto.

### Fase 3 — Produto B MVP: app local (3 a 4 semanas)

**Porquê antes do portal:** é o produto mais diferenciador e o que mais exige da arquitetura (consentimento, encriptação local, modo híbrido).

- App Tauri com motor Python empacotado; login OIDC + PKCE.
- Fluxo de consentimento 4.2.1 completo (pasta → pré-visualização → seleção → política de novos ficheiros → revogação), exclusões por omissão e flag "só local".
- File watcher incremental; índice local encriptado (SQLCipher + keystore do SO).
- Chat com citações clicáveis (abre o ficheiro na página certa) e painel de transparência.
- Modos `hybrid` e `offline` selecionáveis por política.
- Instaladores assinados para Windows e macOS.
- **DoD:** nenhum ficheiro fora das pastas consentidas é lido (teste); revogação remove os dados em menos de 1 min; o motor local rejeita pedidos sem token ou com outra origem; pentest interno à app.

### Fase 4 — Repositório central + Produto A MVP: portal web (3 a 4 semanas)

**Porquê:** reaproveita o core e acrescenta multi-tenancy cloud, a peça com mais risco de fuga entre clientes.

- Central API com RLS, ACL por chunk, upload web, encriptação por tenant (envelope).
- Portal Next.js: login/SSO, chat, gestão de documentos, admin do tenant (utilizadores, grupos, classificação, retenção).
- Integração do Produto B com o repositório central (pesquisa federada + fusão RRF).
- Widget de chat incorporável no site do cliente (MAY), com chave pública restrita e apenas conhecimento público.
- **DoD:** suíte de testes de isolamento entre tenants 100% verde; ACL respeitada nos evals de segurança; auditoria a registar todos os acessos.

### Fase 5 — Piloto real (4 semanas)

**Porquê:** valida valor e usabilidade antes de escalar.

- 1 ou 2 clientes piloto (um por produto), com DPA e DPIA assinados.
- Golden set construído com o cliente; afinação de chunking, prompts e modelo.
- Métricas de uso, feedback e custo por pergunta.
- **DoD:** satisfação ≥ 4/5; taxa de respostas úteis ≥ 75%; zero incidentes de segurança.

### Fase 6 — Conectores cloud (3 a 5 semanas)

- Google Drive, OneDrive/SharePoint, Dropbox, com importação de permissões e sincronização incremental.
- **DoD:** permissões da origem refletidas em menos de 15 min; revogação na origem retira o acesso no chat.

### Fase 7 — Email: pesquisa (2 a 3 semanas)

- Gmail/Google Workspace, Microsoft 365 (Graph) e IMAP; indexação de threads e anexos; emails externos marcados como não confiáveis.
- **DoD:** suíte de injection via email sem sucesso; scopes OAuth só de leitura.

### Fase 8 — Email: rascunhos assistidos (2 a 3 semanas)

- Geração de rascunhos com base no histórico e nos documentos; o envio exige sempre clique humano.
- **DoD:** impossível enviar sem aprovação (teste); registo de auditoria por rascunho.

### Fase 9 — Plataforma multi-negócio (contínuo)

- Templates por setor (prompts, classificações, golden sets base).
- Personalização de marca (white-label) por tenant.
- Faturação por uso (Stripe), planos e limites.
- Painel de observabilidade (OpenTelemetry, Grafana).

### Fase 10 — Evoluções avançadas (backlog)

- GraphRAG / knowledge graph para perguntas relacionais.
- Ferramentas controladas (calendário, CRM) com aprovação humana.
- Fine-tuning leve (LoRA) de um modelo próprio para PT-PT e jargão do setor.
- Instalação on-prem em servidor com GPU para clientes grandes.
- Certificação ISO 27001.

## 8. Primeiros passos concretos (esta semana)

1. Criar o monorepo com a estrutura da Fase 0 e o CI de segurança.
2. Subir o Docker Compose com Postgres+pgvector, Qdrant e Ollama (modelo instruct pequeno).
3. Correr o Docling sobre 10 a 20 documentos reais variados (PDF digitalizado, Excel, email com anexo) e inspecionar o resultado.
4. Implementar `ingest` + `ask` com citações, e escrever 30 perguntas de golden set.
5. Escrever as primeiras ADRs.

## 9. Questões em aberto (decidir com ADR)

- Vector store: pgvector único em todo o lado ou Qdrant? (Recomendação inicial: pgvector na cloud, LanceDB na app local.)
- IdP: Keycloak self-hosted ou serviço gerido?
- Modelo LLM principal e de fallback (decidir pelos evals da Fase 2).
- Preço e modelo de licenciamento do Produto B (por posto, por dispositivo, por tenant).
- Usar Onyx (MIT) como base de código ou apenas como referência? (Recomendação: referência; o core próprio dá controlo sobre multi-tenancy, app local e licença.)

## 10. Infraestrutura: MVP vs produto final

**Princípio:** o MVP tem **as mesmas fases, sistemas e controlos de segurança** do produto final. Só muda a infraestrutura, que no MVP é a mais gratuita possível. Para isso, todo o código usa interfaces (`LLMProvider`, `VectorStore`, `BlobStore`, `AuthProvider`), e passar do MVP para a produção é configuração, não reescrita.

### 10.1 Hardware local disponível

- **Máquina 1:** Intel i5 de 13.ª geração + NVIDIA GTX 1660 OC (6 GB de VRAM, sem tensor cores). Papel: **servidor de modelos do MVP**.
  - Embeddings (`bge-m3` / `multilingual-e5`) e reranker: sem problemas, em GPU ou CPU.
  - LLM: modelos de 7 a 8B quantizados em Q4 (Qwen, Llama, Mistral, Gemma) via Ollama ou llama.cpp, com contexto moderado (4 a 8k). Velocidade aceitável para demo e piloto pequeno; não serve muitos utilizadores em simultâneo.
  - Docling com OCR: funciona; documentos grandes são processados em fila.
- **Máquina 2:** desenvolvimento, testes da app local (Produto B) e simulação de um "cliente".

### 10.2 Tabela comparativa

| Componente | MVP (grátis / quase grátis) | Produto final |
| --- | --- | --- |
| Portal web (Produto A) | Vercel (Next.js) | Vercel Pro ou contentores em cloud UE (ex.: Hetzner, OVH, Scaleway, AWS eu-west/eu-south) |
| API central + gateway | Fly.io / Render free, ou a Máquina 1 exposta via Cloudflare Tunnel | Kubernetes ou contentores geridos na UE, com autoscaling |
| Base de dados + vetores | Supabase (Postgres + pgvector + RLS) | Supabase Pro/Team em região UE, ou Postgres gerido com réplicas |
| Armazenamento de ficheiros | Supabase Storage | Object storage S3 na UE com encriptação por tenant |
| Autenticação | Supabase Auth (OIDC, MFA) | Keycloak/Zitadel ou Supabase Auth pago, com SSO empresarial |
| LLM | Ollama na Máquina 1 (prioridade); Hugging Face (créditos gratuitos) como fallback | Hugging Face Inference Endpoints dedicados (UE), com GPU sob procura, ou servidor GPU próprio |
| Embeddings/rerank (central) | Máquina 1 | Serviço GPU/CPU dedicado ou endpoint HF |
| Rate limit / filas | Upstash Redis (free) | Redis gerido |
| Segredos | Variáveis encriptadas da Vercel/Supabase + Doppler/Infisical free | Vault / KMS da cloud |
| Observabilidade | Sentry free + Grafana Cloud free + Langfuse self-hosted | Stack completa OpenTelemetry com alertas e on-call |
| CI/CD | GitHub Actions (free) | GitHub Actions + ambientes protegidos |
| Exposição da Máquina 1 | Cloudflare Tunnel (sem abrir portas) + Cloudflare Access | Deixa de ser necessário |
| App local (Produto B) | Igual à final, só com builds assinados por certificado de teste | Instaladores com certificados de code signing comerciais |

### 10.3 Notas e limites do MVP (a verificar antes de começar)

- **Vercel Hobby:** pelo que se sabe, o plano gratuito destina-se a uso **não comercial**. Serve para desenvolvimento e demos; um piloto com cliente pagante deve passar para o Pro. Confirmar os termos atuais.
- **Supabase free:** limites de base de dados e de armazenamento reduzidos, e os projetos inativos são pausados. Chega para dev e demo; para o piloto, ponderar o plano Pro. Escolher região UE desde o início.
- **Máquina 1 como servidor:** é um ponto único de falha. Aceitável no MVP, não na produção. Manter o firewall fechado e expor só via Cloudflare Tunnel com autenticação; o disco tem de estar encriptado.
- **Dados reais no MVP:** só com DPA assinado e consentimento do cliente piloto, porque os mesmos controlos de segurança aplicam-se no MVP.
- **Hugging Face grátis:** os créditos de inferência são limitados e a API partilhada não oferece as mesmas garantias de retenção. Usar apenas com dados de teste; com dados de clientes, usar a Máquina 1 ou endpoints dedicados.

### 10.4 Caminho de migração MVP → produto final

1. Trocar a configuração do `LLMProvider` (Ollama local → HF dedicado) e correr os evals para garantir que não há regressão.
2. Migrar o Supabase para um plano pago ou para Postgres gerido (dump/restore; o schema e a RLS são idênticos).
3. Mover a API e o gateway da Máquina 1 para a cloud UE (as mesmas imagens Docker).
4. Ativar KMS com chave por tenant, backups geridos e monitorização com alertas.
5. Repetir o pentest e a suíte de segurança na nova infraestrutura antes de abrir a clientes.

### 10.5 Stacks recomendadas por fase comercial

#### A) Piloto grátis / o mais barato possível (custo alvo: 0 a 30 €/mês)

| Camada | Escolha recomendada | Porquê |
| --- | --- | --- |
| Portal web + back-office | **Vercel Hobby** (dev/demo) | Deploy automático do Next.js a partir do GitHub, preview por PR |
| Base de dados, vetores, auth, storage | **Supabase Free** (região UE) | Postgres + pgvector + RLS + Auth + Storage num só serviço; o modelo de dados é o mesmo da produção |
| API central + Inference Gateway (FastAPI) | **Máquina 1 em Docker**, exposta via **Cloudflare Tunnel + Cloudflare Access** | Grátis, sem abrir portas; alternativa: Fly.io / Render (free) para a API sem GPU |
| LLM | **Ollama na Máquina 1** (7 a 8B em Q4) | Dados não saem da nossa infraestrutura; custo zero |
| LLM fallback (só dados de teste) | Hugging Face (créditos gratuitos) | Para comparar modelos maiores nos evals |
| Embeddings + rerank | Máquina 1 (GPU/CPU) | Grátis, privado |
| Filas / rate limit | Upstash Redis Free | Serverless, encaixa bem com a Vercel |
| Observabilidade | Sentry Free + Langfuse (self-hosted na Máquina 1) + Grafana Cloud Free | Erros, traces de LLM e métricas |
| Email transacional | Resend Free ou Brevo Free | Convites, reset de password |
| Segredos | Infisical / Doppler (free) | Nunca segredos no repositório |
| CI/CD | GitHub Actions | Inclui todos os scans de segurança |
| DNS + WAF básico | Cloudflare Free | DNS, TLS, proteção DDoS |
| App local | Builds Tauri via GitHub Actions; assinatura de teste | Os certificados comerciais ficam para a fase paga |

#### B) Versão comercial / Pro (vender a clientes)

| Camada | Escolha recomendada | Porquê |
| --- | --- | --- |
| Portal web + back-office | **Vercel Pro** (ou contentores em Scaleway/OVH/Hetzner se for preciso controlo total na UE) | Uso comercial permitido, SLA, equipa |
| Base de dados, vetores, auth, storage | **Supabase Pro / Team** (UE), com PITR e backups; Enterprise quando houver exigências de compliance | Mesmo schema do piloto, sem migração de código |
| API central + gateway | Contentores geridos na UE: **Scaleway Serverless Containers / Kapsule**, **OVHcloud**, **Hetzner** (custo) ou **AWS eu-south-2 / eu-west** (escala) | Dados na UE, autoscaling, sem ponto único de falha |
| LLM | **Hugging Face Inference Endpoints dedicados** em região UE com scale-to-zero; alternativa: GPU própria em Scaleway/OVH com vLLM | Isolamento, retenção controlada, DPA |
| Embeddings + rerank | Endpoint HF dedicado ou serviço CPU em contentor | Escalável e separado do LLM |
| Filas / cache | Upstash Pro ou Redis gerido | Volume e fiabilidade |
| Segredos e chaves | KMS da cloud ou HashiCorp Vault; chave por tenant | Crypto-shredding, auditoria |
| Observabilidade | Sentry Team + Langfuse Cloud (UE) ou self-hosted + Grafana com alertas | On-call e SLA |
| Email transacional | Resend / Postmark pagos | Entregabilidade |
| Segurança perimetral | Cloudflare Pro (WAF, bot management) | Proteção do portal |
| App local | Certificados de code signing (Windows EV/OV + Apple Developer) e updater assinado | Confiança e instalação sem avisos |
| Faturação | Stripe Billing (com faturação certificada PT via integração, ex.: InvoiceXpress/Moloni) | Subscrições e conformidade fiscal |

Nota: os planos e limites dos fornecedores mudam. Confirmar preços e termos atuais antes de cada transição e registar a decisão numa ADR.

## 11. Plataforma genérica e extensível por negócio (MUST no desenho, implementação futura)

**Princípio:** o núcleo da plataforma é **agnóstico ao tipo de negócio e ao modelo de negócio**. Nenhum conceito de um setor específico (contabilidade, saúde, imobiliário…) entra no core. As adaptações por negócio fazem-se por **configuração e módulos**, nunca com `if tenant == X` no código.

**Importante:** esta secção define a arquitetura que tem de ficar **preparada desde a Fase 0**. As funcionalidades específicas (templates, orçamentos, etc.) não são implementadas no MVP; apenas os pontos de extensão.

### 11.1 Back-office (super-admin, nosso)

Aplicação separada (`backoffice/`), acessível só pela nossa equipa, com MFA obrigatório e, idealmente, restrição por IP ou Cloudflare Access. Permite:

- Criar, suspender e eliminar **tenants** (empresas clientes) e gerir os seus planos.
- Gerir os **logins**: administradores de cada empresa, convites, reset de MFA.
- Atribuir **produtos** (Web, Local ou ambos) e **módulos/features** por tenant.
- Configurar o **perfil de setor** (prompts base, classificações, templates) a partir de um catálogo.
- Ver métricas de uso e custo por tenant, **sem acesso ao conteúdo** dos documentos. O acesso ao conteúdo para suporte só é possível com autorização temporária do cliente ("break-glass"), que fica registada na auditoria.

### 11.2 Isolamento por empresa

- Cada empresa, ao fazer login, vê **apenas a sua conta e os seus dados** (RLS + `tenant_id` no token + testes de isolamento, conforme a secção 5).
- O front-end é o mesmo para todos, mas **compõe-se em runtime** conforme as features ativas do tenant.

### 11.3 Pontos de extensão a preparar

1. **Feature flags / entitlements por tenant:** tabela `tenant_features` (feature, ativo, configuração JSON validada por schema). O front-end e a API consultam-na; uma feature inativa não aparece nem responde.
2. **Registo de módulos:** cada módulo (ex.: `templates-planilhas`, `orcamentos`) declara um manifesto com nome, versão, rotas de UI, endpoints, permissões necessárias e schema de configuração. O core carrega apenas os módulos ativos para o tenant.
3. **Branding por tenant:** logotipo, cores, nome do assistente, domínio ou subdomínio próprio, guardados em `tenant_branding` e aplicados no portal, na app local e em documentos gerados.
4. **Templates de documentos por tenant:** armazenamento de templates (DOCX, XLSX, HTML) com placeholders; motor de geração (ex.: docxtemplater / python-docx / openpyxl / HTML→PDF) que preenche os dados e aplica o branding. Exemplos futuros:
   - **Contabilidade:** modelos de planilhas próprios da empresa, disponíveis só para esse tenant.
   - **Orçamentos:** o cliente carrega o seu modelo; o utilizador preenche (ou o assistente preenche a partir da conversa) e o resultado sai com o logótipo e as imagens da empresa.
5. **Perfis de setor:** pacotes reutilizáveis (prompt de sistema, glossário, classificações, golden set base, módulos recomendados) aplicáveis a vários tenants do mesmo setor e personalizáveis por tenant.
6. **Ferramentas do assistente por tenant:** o assistente só vê as ferramentas dos módulos ativos (ex.: "gerar orçamento"), sempre com as regras da secção 5.6 (allowlist, validação, confirmação humana).
7. **Webhooks / API pública por tenant** (futuro), para integrações com o ERP ou CRM do cliente.

### 11.4 Regras para manter o core genérico

- Nenhum nome de cliente ou setor no código do core; tudo vem de configuração ou de módulos.
- Os módulos dependem do core e nunca o contrário.
- Cada módulo tem os seus testes, incluindo testes de isolamento entre tenants.
- Os templates carregados pelos clientes são validados (tipo real, tamanho, sem macros nem conteúdo ativo) e processados em sandbox, como qualquer ficheiro (secção 4.1).
- Qualquer customização pedida por um cliente começa com a pergunta: "isto pode ser um módulo ou uma configuração reutilizável?"

### 11.5 Impacto no roadmap

- **Fase 0:** criar as tabelas `tenants`, `tenant_features`, `tenant_branding`, o registo de módulos (mesmo que vazio) e o esqueleto do back-office.
- **Fase 4:** back-office funcional (tenants, logins, produtos, features) e branding básico.
- **Fase 9:** primeiros módulos verticais (templates de planilhas, orçamentos com branding) e perfis de setor.

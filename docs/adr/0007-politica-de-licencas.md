# ADR-0007 · Política de licenças verificada no CI

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

Várias dependências habituais em RAG têm licenças que tornariam o produto não vendável:
PyMuPDF (AGPL), extract-msg (GPL-3.0), html2text (GPL-3.0), rerankers com CC-BY-NC (jina-reranker
v2), MinIO (AGPL). Parte do código vai para o computador do cliente (app desktop), onde as
obrigações de licença são mais exigentes do que num serviço alojado por nós.

## Decisão

Uma allowlist de licenças **por perfil**, verificada automaticamente por `scripts/check_licenses.py`
(`make licenses`, job `security` do CI) com a política em `scripts/license_policy.yaml`:

- `shipped` (vai para o cliente: `rag_local`, `rag_core`, `apps/desktop`, `packages/ui`): MIT,
  BSD-2/3, Apache-2.0, ISC, Zlib, PSF, MPL-2.0 (ficheiros não modificados), Unicode, CC0, 0BSD,
  HPND. Proibidas: GPL, AGPL, LGPL (salvo ADR), SSPL, BUSL, CC-BY-NC, Commons Clause e licenças
  desconhecidas.
- `server` (gateway, central-api, worker, parser-sandbox): o mesmo mais LGPL (por exemplo
  psycopg). Proibidas: AGPL, SSPL, BUSL, CC-BY-NC e desconhecidas.
- `dev`: qualquer licença OSI.
- Exceções só por pacote e versão, com motivo e ADR.
- **Modelos:** Apache-2.0, MIT ou BSD; Llama e Gemma só com ADR; proibido CC-BY-NC e "research
  only". O PyInstaller (GPL com exceção de bootloader) pode ser usado para empacotar.

## Alternativas consideradas

- **Revisão manual de licenças** — falha em silêncio quando uma dependência transitiva muda.
- **Aceitar GPL/AGPL no servidor** — obrigaria a abrir o código ou a pagar licenças comerciais.
- **Uma só allowlist para tudo** — ou demasiado restritiva para o servidor, ou demasiado permissiva
  para o que se distribui.

## Consequências

- O CI falha quando entra uma dependência fora da política (INV-21).
- Algumas bibliotecas populares estão excluídas e há alternativas a escolher caso a caso.
- A política é uma fonte de verdade versionada; mudar uma licença permitida exige ADR.

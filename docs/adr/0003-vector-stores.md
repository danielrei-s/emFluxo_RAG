# ADR-0003 · Vector stores: pgvector na central e SQLite/SQLCipher no local

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

A especificação v0.1 misturava Qdrant, pgvector e LanceDB. O índice local (Produto B) tem de ser
encriptado em repouso com a chave no keystore do SO, e o LanceDB e o Qdrant não se encriptam com
SQLCipher. Cada serviço extra aumenta a operação e a superfície de ataque.

## Decisão

- **Central:** pgvector no Postgres 17, atrás da interface `VectorStore` (`PgVectorStore`).
  Chunks, ACL e embeddings na mesma base, sujeitos ao mesmo RLS.
- **Local:** um único ficheiro SQLCipher 4 com metadados, FTS5 e vetores em BLOB. A pesquisa
  vetorial faz-se em memória com numpy até cerca de 200 mil chunks. Se o FTS5 não estiver
  disponível, há fallback BM25 em memória.
- Qdrant sai do compose; LanceDB não é usado.
- A dimensão `D` dos vetores fixa-se na ADR-0009 (F5-T05) antes de F7-T04. Mudar de modelo de
  embeddings implica nova migração e um job de reindexação.
- Uma suite de contrato partilhada corre contra todas as implementações de `VectorStore`.

## Alternativas consideradas

- **Qdrant na central** — um serviço a mais para operar, sem RLS nativo; as ACL teriam de ser
  replicadas.
- **LanceDB no local** — não encripta com SQLCipher; obrigaria a encriptação de disco por fora.
- **sqlite-vec / FAISS no local** — mais uma dependência nativa por SO; a pesquisa em memória é
  suficiente para o volume previsto.

## Consequências

- Uma só tecnologia por ambiente e um único modelo de segurança (RLS na central, SQLCipher no
  local).
- Acima de ~200 mil chunks locais é preciso uma ADR de migração (índice aproximado).
- O desempenho do pgvector depende do índice escolhido (HNSW/IVFFlat), a decidir na F7-T04.

# ADR-0009 · Modelos v1 (embeddings, reranker, LLM e perfil desktop)

- **Estado:** proposta (aguarda o benchmark da Máquina 1: HR-05)
- **Data:** 2026-11-22 · **Tarefa:** F5-T05

## Contexto

A qualidade, a latência e o custo dependem de quatro escolhas: modelo de embeddings (e a sua
dimensão `D`, que fixa o esquema do pgvector), reranker, LLM por omissão e de *fallback*, e os
modelos do perfil desktop (CPU, offline). O gate M1 pede, no golden set: Recall@5 ≥ 0,80,
`leak_rate` = 0, fallback por citação inválida ≤ 10% e respostas com o conteúdo esperado ≥ 75%.
Licenças: só Apache-2.0, MIT ou BSD; Llama/Gemma exigem esta ADR (INV-21). Revisões e hashes
fixados (INV-22).

## Decisão

**Ainda por tomar.** O que está pronto para decidir com dados (`make bench`, relatório em
`evals/bench/results-<data>.md`):

| Escolha | Candidatos | Critério |
|---|---|---|
| Embeddings (Ollama) | `bge-m3` (D = 1024) | Recall@5, emb/s, VRAM |
| Embeddings (ONNX) | `multilingual-e5-base`, `multilingual-e5-small` (prefixos `query: ` e `passage: `) | Recall@5, RSS em CPU |
| Reranker | `bge-reranker-v2-m3` vs nenhum | ganho de Recall@5/MRR vs latência |
| LLM por omissão | versões *instruct* recentes de Qwen e Mistral (Q4_K_M, Apache-2.0) | `contém`, fallback, TTFT p50 |
| LLM desktop (CPU) | dois modelos de 3–4B (Apache-2.0/MIT) | `contém` e tempo total p95 em CPU |

A preencher depois do benchmark:

- **Dimensão `D`** dos vetores (pré-requisito de F7-T04) e o modelo de embeddings escolhido.
- **`min_relevance`** calibrado (por omissão 0,35) e se o reranker fica ligado.
- **Chunking** alinhado ao modelo: `max_tokens` abaixo do comprimento máximo do modelo (ex.:
  multilingual-e5 aceita 512 tokens, logo `max_tokens` ≈ 450) e `HfTokenCounter` como contador
  em produção (hoje o contador é a estimativa `len/4`).
- **Perfil desktop**: modelos e quantização.
- Licença, `revision` e `sha256` de cada modelo no `models.yaml` (`rag models check`).

## Alternativas consideradas

- **Fixar já o `bge-m3`** — plausível, mas sem números do hardware real (GTX 1660, 6 GB) seria
  uma suposição; a decisão custa um dia de benchmark e evita retrabalho do esquema vetorial.
- **Modelos Llama/Gemma** — só entram com justificação específica nesta ADR (licença restrita).

## Consequências

- Até esta ADR ser aceite, a dimensão `D` fica em aberto e F7-T04 (pgvector) não deve começar.
- O benchmark é reprodutível (`evals/bench/README.md`) e o relatório não leva segredos.
- Mudar de modelo de embeddings obriga a reindexar tudo (o hash do corpus na cache da avaliação
  inclui o `model_id`).

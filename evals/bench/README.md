# Benchmark de modelos (F5-T05)

Mede, para cada combinação **embeddings × reranker × LLM**, a qualidade no golden set e a
latência e memória do servidor de modelos. Os resultados alimentam a ADR-0009.

## Como correr (Máquina 1, com Ollama e GPU)

1. Preparar o `models.yaml` a partir de `models.example.yaml` com os candidatos (licença
   Apache-2.0/MIT/BSD; Llama/Gemma só com `adr`). Ver `docs/plan/tarefas/F5-T05.md`.
2. Ter os modelos descarregados no Ollama (LLM em Q4_K_M, embeddings `bge-m3`) e, para os ONNX,
   as revisões e hashes preenchidos no `models.yaml` (`uv run rag models check --cache-dir …`).
3. Definir `RAG_OLLAMA_URL` (inclui `/v1`) e correr:

```powershell
uv run python evals/bench/run_bench.py --models models.yaml `
    --embeddings rag-embed rag-embed-e5-base --rerankers none rag-rerank `
    --llms rag-qwen rag-mistral --out evals/bench/results-AAAA-MM-DD.md
```

`make bench` corre o mesmo com os valores por omissão (`rag-embed`, sem reranker, `rag-default`).

## O que o relatório traz

`recall@5`, `mrr`, `contém` (respostas com o conteúdo esperado), `não-encontrei`, `fugas`,
`fallback`, embeddings por segundo, TTFT p50, tempo total p50/p95, RSS do processo e VRAM
(via `nvidia-smi`, se existir). Gate M1: Recall@5 ≥ 0,80, `fugas` = 0, `fallback` ≤ 10%,
`contém` ≥ 75%.

## Ensaio sem modelos

`uv run python evals/bench/run_bench.py --dry-run` usa os fakes e só valida o formato do
relatório (é o que `test_bench_script_dry_run` faz). O relatório **não leva segredos**: partilha-o
tal como sai.

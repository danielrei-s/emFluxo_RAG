# ADR-0004 · LLM e embeddings por API compatível com OpenAI, com Ollama

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

Os modelos correm na Máquina 1 (i5 de 13.ª geração, GTX 1660 com 6 GB de VRAM) no MVP, e terão de
poder mudar para Hugging Face Endpoints, vLLM ou um fornecedor cloud sem reescrever código. O
Ollama não tem autenticação. A meta de latência p95 < 6 s é impossível na GTX 1660 com modelos de
7–8B parâmetros: o prefill de ~3 mil tokens mais ~300 gerados fica na ordem dos 10–20 s (estimativa
a medir na F5).

## Decisão

- Uma única implementação `OpenAICompatible` para LLM e embeddings, que cobre Ollama, llama.cpp,
  vLLM, TGI e Hugging Face Endpoints. Os modelos são aliases em `models.yaml` (backend, URL,
  modelo, revisão fixada, licença).
- O Inference Gateway centraliza autenticação, quotas, rate limit, escolha de modelo, fallback e
  redação de PII antes de fornecedores externos.
- O Ollama **nunca** é exposto: só na rede Docker interna ou em loopback (INV-24), com teste à
  configuração do compose. Em modo offline o URL do LLM tem de ser loopback (INV-05).
- Modelos só de revisões fixadas, em formatos seguros (safetensors, ONNX, GGUF), com hash
  verificado (INV-22), e com licença comercial (Apache-2.0, MIT ou BSD).
- No MVP mede-se o tempo até ao primeiro token (TTFT) com streaming; o p95 < 6 s fica para a
  infraestrutura de produção.

## Alternativas consideradas

- **SDK de um só fornecedor** — prende o produto a esse fornecedor e dificulta o modo offline.
- **LiteLLM ou camada equivalente** — mais uma dependência grande no caminho crítico; o subconjunto
  de que precisamos é pequeno.
- **Expor o Ollama diretamente** — sem autenticação; inaceitável fora da rede interna.

## Consequências

- Trocar de modelo ou fornecedor é configuração; a qualidade é validada pelo golden set.
- O gateway é ponto único de falha no MVP (Máquina 1); há runbook e testes de capacidade (F13).
- Licenças com restrições (Llama, Gemma) só com ADR própria; CC-BY-NC e "research only" são
  proibidas.

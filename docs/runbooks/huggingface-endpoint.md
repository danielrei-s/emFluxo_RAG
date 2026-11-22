# Fornecedor Hugging Face (fallback opcional, HR-08)

O gateway pode usar um **Inference Endpoint dedicado** do Hugging Face como fallback quando o
Ollama da Máquina 1 falha. É opcional: sem este passo o gateway só usa os modelos locais.

## Regras

- **Só dados de teste** até existir DPA com o fornecedor (especificação 10.3).
- O alias `rag-fallback-hf` está marcado `external: true`: o gateway **redige a PII** antes de
  enviar (NIF, NISS, CC, IBAN, telefone, email) e repõe-na na resposta (F6-T06), conforme
  `redact_pii_for_external` da política do tenant.
- Conteúdo `restricted` ou `local_only` nunca chega a um fornecedor externo (INV-05).
- O alias só é usado por tenants que o tenham em `allowed_models` no `policies.yaml`.

## Criar o endpoint

1. Hugging Face → **Inference Endpoints → New endpoint**.
2. Escolher um modelo com licença Apache-2.0/MIT (ver `models.example.yaml` e a ADR-0009).
3. **Região na UE**, tipo **Dedicated**, **Protected** (exige token) e _scale to zero_ ligado
   (menos custo; o primeiro pedido depois de inatividade demora a arrancar).
4. Motor **TGI** ou vLLM com a API compatível com OpenAI (`/v1/chat/completions`).
5. Definir o limite de custo mensal e um alerta no painel de faturação.
6. Rever a retenção de pedidos/logs do endpoint (desligar o registo de pedidos).

## Configurar o gateway

Em `/etc/rag/gateway.env` (modo 0600; os valores **nunca** vão para o chat nem para o Git):

```
RAG_HF_ENDPOINT_URL=https://<endpoint>.endpoints.huggingface.cloud/v1
RAG_HF_API_KEY=<token com permissão só de inferência>
```

No `models.yaml` da Máquina 1, copiar a entrada `rag-fallback-hf` de `models.example.yaml` e, no
`policies.yaml`, acrescentá-la depois do modelo principal:

```yaml
tenants:
  aurora:
    allowed_models: [rag-default, rag-fallback-hf]
```

## Verificar

```powershell
$env:RAG_LIVE_HF_URL = "https://<endpoint>.endpoints.huggingface.cloud/v1"
$env:RAG_LIVE_HF_KEY = "<token>"
uv run pytest services/gateway/tests/test_hf_live.py -m live
```

O teste só envia uma frase sem dados pessoais e não imprime a resposta nem o token.

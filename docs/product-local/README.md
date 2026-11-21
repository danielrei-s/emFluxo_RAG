# Produto B — App local (desktop)

App instalada no computador do cliente. Usa a base documental da empresa (via Central API, com ACL
aplicada no servidor) e as pastas locais que o utilizador autoriza, com consentimento por pasta e
por documento. Ficheiros, parsing, embeddings e índice local ficam **sempre** no dispositivo.

Modos: **híbrido** (só a pergunta e os excertos mínimos, já redigidos, vão para o nosso Inference
Gateway) e **offline** (o LLM também corre localmente com Ollama, só em loopback).

## Fontes de conhecimento

| Fonte de conhecimento | Produto A (Web) | Produto B (Local) |
| --- | --- | --- |
| Conhecimento geral do LLM | ✔ | ✔ |
| Base documental da empresa (central) | ✔ | ✔ |
| Documentos próprios da pasta autorizada | ✖ | ✔ |

## O que não faz

- **Não carrega documentos locais** para o repositório central: chunks com `origin: local` nunca
  são enviados à Central API (INV-04).
- Documentos marcados "só local" **nunca saem do dispositivo**, nem redigidos (INV-05).
- Não lê nada fora das pastas consentidas: todo o acesso a ficheiros passa pelo FileGate (INV-10).
- Não expõe o motor local à rede: escuta só em loopback, com token por arranque e verificação de
  Origin.
- Não guarda tokens ou credenciais em disco em claro; ficam no keychain do SO (INV-13).
- Não funciona depois de revogado: o kill switch apaga credenciais e índice local.

## Onde fica o código

`apps/desktop` (shell Tauri e UI), `apps/local-engine` (motor `rag_local`) e `packages/core`.
O código exclusivo do Produto B nunca vive em `packages/core`.

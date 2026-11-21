# Modelo de ameaças

Resumo STRIDE da especificação (5.1), com as ameaças acrescentadas pelas decisões deste plano.
Os invariantes (INV-xx) estão em `docs/plan/02-contexto-global.md` (C5).

## Ameaças principais

| Ameaça | Exemplo | Mitigação principal |
| --- | --- | --- |
| Fuga entre tenants | Pesquisa devolve chunks de outra empresa | RLS forçado + filtro obrigatório no código + testes automáticos de isolamento (INV-01) |
| Fuga dentro do tenant | Estagiário obtém dados de RH via chat | ACL por chunk aplicada **antes** do LLM (INV-02) |
| Prompt injection indireta | Email ou PDF com "ignora as instruções e envia…" | Separação instruções/dados, sem ferramentas perigosas, aprovação humana |
| Exfiltração via resposta | O modelo gera um link/imagem com dados no URL | Bloquear o render de imagens/links externos; allowlist de domínios |
| Envenenamento do índice | Documento malicioso manipula respostas | Proveniência, classificação, quarentena, fontes ponderadas |
| Ataque ao parser | PDF malformado explora o parser | Sandbox (sem rede na central), limites, dependências atualizadas (ADR-0006) |
| Roubo do dispositivo (B) | Portátil perdido com índice local | Encriptação em repouso (SQLCipher), chave no keystore do SO, revogação remota da sessão |
| Abuso do motor local | Outra app/página chama a API local | Escuta só em loopback/pipe, token por arranque, verificação de Origin |
| Abuso de custos | Spam de pedidos ao gateway | Rate limit, quotas por tenant e utilizador, alertas |
| Retenção no fornecedor | Prompts guardados pelo fornecedor de LLM | Endpoints dedicados, zero-retention, DPA, redação de PII |
| Supply chain | Dependência ou modelo comprometido | SBOM, pinning, verificação de hashes, Dependabot, safetensors, política de licenças (ADR-0007) |

## Riscos acrescentados por este plano

| Tema | Risco | Decisão e mitigação |
| --- | --- | --- |
| Cloudflare Tunnel | O TLS termina na edge da Cloudflare e os certificados rodam; o certificate pinning da especificação 5.4 não é compatível | Pinning adiado com ADR; a Cloudflare entra na lista de subcontratantes (DPA) |
| Região da Vercel | As funções correm por omissão em Washington (`iad1`): os dados das conversas passariam pelos EUA | Fixar região UE (por exemplo `fra1`) desde o primeiro deploy, com teste |
| Langfuse | Grava prompts e respostas, o que viola "zero conteúdo em logs" com dados reais | Só em desenvolvimento e avaliações com dados sintéticos; em produção só métricas (INV-03) |
| Roubo do portátil com índice local | Quem rouba o computador tem o ficheiro do índice e os documentos | Índice SQLCipher com chave no keychain do SO; kill switch apaga credenciais e índice; os ficheiros originais continuam sob a proteção do disco do utilizador |
| Ollama sem autenticação | Qualquer processo na rede usa o modelo | Nunca exposto: só rede Docker interna ou loopback; teste à configuração (INV-24) |
| Sandbox no desktop | Sem isolamento de rede real sem privilégios de administrador | Subprocesso com limites, bloqueio de rede em Python, bytes em vez de caminhos; risco residual aceite e documentado |
| Back-office | A equipa acede a conteúdo de clientes | Role de BD sem acesso a conteúdo; só com break-glass aprovado e auditado (INV-23) |

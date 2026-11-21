# Produto A — Portal web

Chatbot alojado por nós (SaaS), na UE, que responde com citações sobre a base documental da
empresa do utilizador. O utilizador entra no portal, escolhe uma conversa e pergunta; a Central API
aplica a ACL e a classificação **antes** de o LLM ver qualquer excerto.

## Fontes de conhecimento

| Fonte de conhecimento | Produto A (Web) | Produto B (Local) |
| --- | --- | --- |
| Conhecimento geral do LLM | ✔ | ✔ |
| Base documental da empresa (central) | ✔ | ✔ |
| Documentos próprios da pasta autorizada | ✖ | ✔ |

O conhecimento geral é **rotulado** como tal nas respostas por omissão; cada tenant pode proibi-lo.

## O que não faz

- **Não acede a pastas locais** de nenhum utilizador, nem pode: esse conhecimento é exclusivo do
  Produto B.
- Não mostra chunks ou documentos a quem não tem permissão; um recurso de outro tenant devolve
  404.
- Não executa ferramentas nem ações em nome do utilizador (sem envio de email, sem escrita em
  sistemas externos).
- Não renderiza imagens nem links fora da allowlist de domínios do tenant.
- Não guarda conteúdo em logs, métricas ou traces (INV-03).

## Onde fica o código

`apps/web` (portal), `packages/ui` (componentes de chat partilhados), `services/central-api`
(API e worker de ingestão) e `packages/core` (o core, que não conhece os produtos). O acesso é
controlado por entitlements (`products: ["web"]`) validados no servidor em cada pedido.

# ADR-0005 · Autenticação: Supabase Auth atrás de `AuthProvider`

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

A especificação v0.1 era contraditória: Keycloak (secção 5.2 e compose) contra Supabase Auth
(secção 10). Além disso, o token com `tenant_id` e `groups` impede a revogação imediata e cria
dados obsoletos. A app desktop (Produto B) precisa de OIDC com PKCE, mas o Supabase Auth não tem
ecrã de login alojado.

## Decisão

- **Supabase Auth** como IdP do MVP, atrás da interface `AuthProvider`. Keycloak sai do compose.
- **O token só prova identidade.** Tenant, papel, grupos e produtos (entitlements) são resolvidos
  no servidor em cada pedido, com cache de no máximo 60 s. Revogar um utilizador ou um
  entitlement tem efeito em ≤ 60 s.
- **Produto B:** usar o OAuth 2.1 Server do Supabase (beta pública desde novembro de 2025;
  confirmar o estado num spike) com página de consentimento no portal. Plano B documentado: fluxo
  próprio segundo o RFC 8252 na Central API. A escolha final fica na ADR-0010 (F10-T08).
- Registo de dispositivos, licença offline e kill switch são independentes do emissor do token;
  os tokens de serviço e de licença usam chaves Ed25519 da própria central com JWKS.
- Os tokens ficam só no keychain do SO (INV-13); nunca em disco em claro.

## Alternativas consideradas

- **Keycloak** — serviço pesado para operar no MVP; duplicaria a identidade já oferecida pelo
  Supabase.
- **Tenant e grupos dentro do JWT** — revogação lenta e informação obsoleta até o token expirar.
- **Autenticação própria desde o início** — mais código de segurança escrito por agentes; só se
  justifica como plano B para o Produto B.

## Consequências

- Menos código de autenticação para manter e auditar.
- Dependência de um recurso em beta (OAuth 2.1 Server) para o login do Produto B: risco mitigado
  com spike, ADR-0010 e o plano B pronto (F8-T12).
- Cada pedido faz uma resolução de Principal no servidor, com custo de uma consulta em cache.

# Projeto Supabase (HR-09)

Supabase serve só de **identidade** (Auth) e, em staging, de Postgres gerido. A Central API valida os
tokens no servidor e decide tenant, role e produtos pela BD (`app.memberships`); nunca confia no que
o cliente envia.

## Checklist do projeto

1. **Região UE** (por exemplo Frankfurt ou Paris). Plano e custos: confirmar com o OLEK.
2. **Chaves JWT assimétricas** (Authentication → JWT Keys): usar ES256 ou RS256 e não o segredo
   partilhado HS256. O JWKS fica em `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`.
3. **MFA TOTP** ativo (Authentication → Multi-Factor). As ações de administração exigem `aal2`
   (INV-15); sem MFA os administradores não conseguem geri-los.
4. **SMTP próprio** para os emails de convite e recuperação (nada de enviar pelo serviço partilhado).
5. **Redirect URLs** só dos domínios da aplicação (`https://<tenant>.<domínio>/*`) e do `localhost`
   em desenvolvimento.
6. **OAuth 2.1 Server** (Authentication → OAuth Server) se for preciso para a aplicação local.
7. Desligar o registo livre (_Allow new users to sign up_): os utilizadores entram por convite.

## Configuração da Central API

Em `/etc/rag/central.env` (modo 0600; os valores nunca vão para o chat nem para o Git):

```
RAG_SUPABASE_JWT_ISSUER=https://<ref>.supabase.co/auth/v1
RAG_SUPABASE_JWKS_URL=https://<ref>.supabase.co/auth/v1/.well-known/jwks.json
RAG_SUPABASE_JWT_AUDIENCE=authenticated
```

## Verificar

- Um token válido de um utilizador **com** pertença dá 200; sem pertença dá 403; sem token 401.
- Um utilizador com várias pertenças tem de enviar `X-Tenant-Id`; sem ele a resposta é 400.
- Desativar a pertença deixa de valer ao fim de 60 s (TTL da cache do resolver).

Os testes automáticos usam um emissor de tokens de teste (`rag_core.testing.jwt`) e não precisam do
Supabase real.

# ADR-0002 · Supabase no MVP, atrás de interfaces

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

O MVP usa infraestrutura gratuita. O Supabase oferece Postgres 17 com pgvector, Auth e Storage,
mas traz riscos concretos: expõe o schema `public` pela Data API com a chave anónima; a role
`service_role` tem BYPASSRLS (o RLS não se aplica se a API ligar com ela); o plano gratuito pausa
projetos inativos e não tem backups descarregáveis. Queremos poder passar para infraestrutura
própria ou para um plano pago sem reescrever código.

## Decisão

Usar o Supabase **apenas como Postgres gerido, Auth e Storage**, sempre atrás das interfaces do
core (`VectorStore`, `BlobStore`, `AuthProvider`). Regras:

- As tabelas vivem no schema `app`, sem grants para `anon` nem `authenticated`; todo o acesso a
  dados passa pela Central API.
- A API liga ao Postgres com roles da aplicação **sem BYPASSRLS**, com `FORCE ROW LEVEL SECURITY`
  e `set_config('app.tenant_id', …)` por transação. Um teste falha se alguma tabela não tiver RLS.
- A `service_role` só é usada para convites e administração (back-office), nunca no caminho dos
  pedidos dos utilizadores.
- Backups: `pg_dump` encriptado diário e teste de restauro mensal.
- Migrações SQL próprias, uma só fonte para testes, desenvolvimento e Supabase.

## Alternativas consideradas

- **Postgres próprio desde o início** — mais operação (backups, atualizações, TLS) numa fase em
  que o custo e o tempo são o fator limitante.
- **Usar a Data API do Supabase diretamente a partir do browser** — o RLS passaria a ser a única
  barreira e a lógica de ACL e auditoria ficaria fora da Central API.
- **Outro BaaS (Firebase, etc.)** — sem Postgres/pgvector nem RLS, incompatível com o modelo de
  tenancy escolhido.

## Consequências

- Trocar de fornecedor de Postgres é configuração (`RAG_DATABASE_*`), não reescrita.
- Antes de clientes pagantes é preciso passar para um plano pago (HR-13) e registar em ADR.
- O isolamento entre tenants (INV-01) assenta em RLS forçado **e** em filtro no código.

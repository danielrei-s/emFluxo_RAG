-- F7-T06: auditoria append-only com cadeia de hashes por escopo (tenant ou plataforma). INV-16.
create table app.audit_log (
  id bigint generated always as identity primary key,
  tenant_id uuid, -- null = evento de plataforma
  actor_type text not null check (actor_type in ('user', 'staff', 'device', 'system')),
  actor_id text,
  action text not null check (action ~ '^[a-z0-9_.]+$'),
  resource_type text,
  resource_id text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null,
  prev_hash text not null,
  hash text not null
);
create index audit_log_tenant_idx on app.audit_log (tenant_id, id);

create table app.audit_heads (
  scope text primary key, -- id do tenant ou 'platform'
  last_hash text not null
);

create function app.audit_immutable() returns trigger
  language plpgsql
  as $$ begin
    raise exception 'audit_log é append-only' using errcode = '42501';
  end $$;

create trigger audit_no_update before update or delete on app.audit_log
  for each row execute function app.audit_immutable();
create trigger audit_no_truncate before truncate on app.audit_log
  for each statement execute function app.audit_immutable();

alter table app.audit_log enable row level security;
alter table app.audit_log force row level security;
alter table app.audit_heads enable row level security;
alter table app.audit_heads force row level security;

create policy audit_log_select on app.audit_log for select to app_user_role
  using (tenant_id = app.current_tenant());
create policy audit_log_insert on app.audit_log for insert to app_user_role
  with check (tenant_id = app.current_tenant());
create policy audit_heads_tenant on app.audit_heads to app_user_role
  using (scope = app.current_tenant()::text) with check (scope = app.current_tenant()::text);

-- back-office: lê tudo (sem conteúdo) e escreve só eventos de plataforma
create policy audit_log_backoffice_select on app.audit_log for select to app_backoffice_role
  using (true);
create policy audit_log_backoffice_insert on app.audit_log for insert to app_backoffice_role
  with check (tenant_id is null);
create policy audit_heads_backoffice on app.audit_heads to app_backoffice_role
  using (scope = 'platform') with check (scope = 'platform');

revoke all on app.audit_log, app.audit_heads from public;
grant select, insert on app.audit_log to app_user_role, app_backoffice_role;
grant select, insert, update on app.audit_heads to app_user_role, app_backoffice_role;

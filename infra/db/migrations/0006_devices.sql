-- F8-T06/F8-T07: instalações do Produto B (a tabela serve já o estado interno para o gateway).
create table app.devices (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  user_id uuid not null references app.users (id) on delete cascade,
  name text not null,
  os text,
  app_version text,
  public_key text,
  status text not null default 'active' check (status in ('active', 'revoked')),
  created_at timestamptz not null default now(),
  last_seen_at timestamptz,
  revoked_at timestamptz,
  revoked_by uuid
);
create index devices_user_idx on app.devices (tenant_id, user_id);

alter table app.devices enable row level security;
alter table app.devices force row level security;
create policy devices_tenant on app.devices to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());
create policy devices_backoffice on app.devices for select to app_backoffice_role using (true);

revoke all on app.devices from public;
grant select, insert, update on app.devices to app_user_role;
grant select on app.devices to app_backoffice_role;

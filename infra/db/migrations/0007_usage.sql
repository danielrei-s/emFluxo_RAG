-- F8-T06: consumo do gateway. Só metadados: nenhuma coluna de conteúdo (INV-03).
create table app.usage_events (
  id bigint generated always as identity primary key,
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  user_id text,
  device_id text,
  model text not null,
  tokens_in int not null check (tokens_in >= 0),
  tokens_out int not null check (tokens_out >= 0),
  latency_ms int not null check (latency_ms >= 0),
  ttft_ms int,
  status text not null check (status in ('ok', 'error', 'rejected')),
  error_code text check (error_code is null or error_code ~ '^[a-z0-9_]{1,64}$'),
  at timestamptz not null
);
create index usage_events_tenant_month_idx on app.usage_events (tenant_id, at);

alter table app.usage_events enable row level security;
alter table app.usage_events force row level security;
create policy usage_events_tenant on app.usage_events to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());
create policy usage_events_backoffice on app.usage_events for select to app_backoffice_role
  using (true);

revoke all on app.usage_events from public;
grant select, insert on app.usage_events to app_user_role;
grant select on app.usage_events to app_backoffice_role;

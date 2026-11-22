-- F7-T07: fila de jobs em Postgres (SKIP LOCKED). O payload só leva IDs e metadados (INV-03).
create table app.jobs (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  kind text not null check (kind ~ '^[a-z0-9_.]+$'),
  payload jsonb not null default '{}',
  status text not null default 'queued'
    check (status in ('queued', 'running', 'done', 'failed', 'dead')),
  attempts int not null default 0,
  max_attempts int not null default 5,
  run_after timestamptz not null default now(),
  locked_by text,
  locked_at timestamptz,
  last_error_code text,
  dedupe_key text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (kind, dedupe_key)
);
create index jobs_ready on app.jobs (run_after) where status = 'queued';
create index jobs_tenant_idx on app.jobs (tenant_id, status);

alter table app.jobs enable row level security;
alter table app.jobs force row level security;

-- a API vê e cria os jobs do seu tenant; o worker (que herda estas políticas) vê todos
create policy jobs_tenant_select on app.jobs for select to app_user_role
  using (tenant_id = app.current_tenant());
create policy jobs_tenant_insert on app.jobs for insert to app_user_role
  with check (tenant_id = app.current_tenant());
create policy jobs_worker on app.jobs to app_worker_role using (true) with check (true);

revoke all on app.jobs from public;
grant select, insert on app.jobs to app_user_role;
grant update, delete on app.jobs to app_worker_role;

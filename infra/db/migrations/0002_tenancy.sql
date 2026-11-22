-- F7-T02: tenancy (tenants, utilizadores, membros, grupos, workspaces, features, branding) com
-- RLS forçado e privilégios mínimos. Ver C7 e C8 do plano. INV-01, INV-23.

-- ---------------------------------------------------------------------------- funções
create function app.current_tenant() returns uuid
  language sql stable
  as $$ select nullif(current_setting('app.tenant_id', true), '')::uuid $$;

create function app.current_user_id() returns uuid
  language sql stable
  as $$ select nullif(current_setting('app.user_id', true), '')::uuid $$;

create function app.role_rank(role text) returns int
  language sql immutable
  as $$ select case role
    when 'owner' then 5 when 'admin' then 4 when 'editor' then 3
    when 'member' then 2 when 'viewer' then 1 else 0 end $$;

create function app.classification_rank(classification text) returns int
  language sql immutable
  as $$ select case classification
    when 'public' then 0 when 'internal' then 1 when 'confidential' then 2
    when 'restricted' then 3 else 99 end $$;

grant execute on all functions in schema app to app_user_role, app_backoffice_role;

-- ---------------------------------------------------------------------------- tabelas
create table app.tenants (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique check (slug ~ '^[a-z0-9-]{3,40}$'),
  name text not null,
  status text not null default 'active' check (status in ('active', 'suspended', 'deleting')),
  plan text not null default 'pilot',
  products text[] not null default '{}' check (products <@ array['web', 'local']::text[]),
  settings jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create table app.users (
  id uuid primary key,
  email text not null,
  display_name text,
  created_at timestamptz not null default now()
);

create table app.memberships (
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  user_id uuid not null references app.users (id) on delete cascade,
  role text not null check (role in ('owner', 'admin', 'editor', 'member', 'viewer')),
  products text[] not null default '{}',
  status text not null default 'active' check (status in ('active', 'invited', 'disabled')),
  created_at timestamptz not null default now(),
  primary key (tenant_id, user_id)
);
create index memberships_user_idx on app.memberships (user_id);

create table app.groups (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  name text not null,
  unique (tenant_id, name),
  unique (tenant_id, id)
);

create table app.group_members (
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  group_id uuid not null,
  user_id uuid not null references app.users (id) on delete cascade,
  primary key (group_id, user_id),
  foreign key (tenant_id, group_id) references app.groups (tenant_id, id) on delete cascade
);

create table app.workspaces (
  id uuid primary key default gen_random_uuid(),
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  name text not null,
  kind text not null default 'upload' check (kind in ('upload', 'connector')),
  unique (tenant_id, id)
);

create table app.tenant_features (
  tenant_id uuid not null references app.tenants (id) on delete cascade,
  feature text not null,
  enabled boolean not null default false,
  config jsonb not null default '{}',
  updated_at timestamptz not null default now(),
  primary key (tenant_id, feature)
);

create table app.tenant_branding (
  tenant_id uuid primary key references app.tenants (id) on delete cascade,
  assistant_name text,
  primary_color text check (primary_color is null or primary_color ~ '^#[0-9a-fA-F]{6}$'),
  logo_blob_key text,
  custom_domain text unique
);

-- Equipa da plataforma: fora do RLS e sem grants para a aplicação (só o back-office lê).
create table app.platform_staff (
  user_id uuid primary key,
  role text not null check (role in ('support', 'admin'))
);

-- ---------------------------------------------------------------------------- RLS forçado
alter table app.tenants enable row level security;
alter table app.tenants force row level security;
alter table app.users enable row level security;
alter table app.users force row level security;
alter table app.memberships enable row level security;
alter table app.memberships force row level security;
alter table app.groups enable row level security;
alter table app.groups force row level security;
alter table app.group_members enable row level security;
alter table app.group_members force row level security;
alter table app.workspaces enable row level security;
alter table app.workspaces force row level security;
alter table app.tenant_features enable row level security;
alter table app.tenant_features force row level security;
alter table app.tenant_branding enable row level security;
alter table app.tenant_branding force row level security;

-- tenants
create policy tenants_tenant on app.tenants to app_user_role
  using (id = app.current_tenant()) with check (id = app.current_tenant());

-- users: o próprio, ou quem partilha o tenant atual; só se insere o próprio
create policy users_select on app.users for select to app_user_role
  using (
    id = app.current_user_id()
    or exists (
      select 1 from app.memberships m
      where m.user_id = users.id and m.tenant_id = app.current_tenant()
    )
  );
create policy users_insert on app.users for insert to app_user_role
  with check (id = app.current_user_id());
create policy users_update on app.users for update to app_user_role
  using (id = app.current_user_id()) with check (id = app.current_user_id());

-- memberships: leitura também pelo próprio utilizador (para escolher o tenant)
create policy memberships_select on app.memberships for select to app_user_role
  using (tenant_id = app.current_tenant() or user_id = app.current_user_id());
create policy memberships_insert on app.memberships for insert to app_user_role
  with check (tenant_id = app.current_tenant());
create policy memberships_update on app.memberships for update to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());
create policy memberships_delete on app.memberships for delete to app_user_role
  using (tenant_id = app.current_tenant());

-- política genérica das restantes tabelas com tenant_id
create policy groups_tenant on app.groups to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());
create policy group_members_tenant on app.group_members to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());
create policy workspaces_tenant on app.workspaces to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());
create policy tenant_features_tenant on app.tenant_features to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());
create policy tenant_branding_tenant on app.tenant_branding to app_user_role
  using (tenant_id = app.current_tenant()) with check (tenant_id = app.current_tenant());

-- back-office: só metadados, todos os tenants, só leitura (INV-23)
create policy tenants_backoffice on app.tenants for select to app_backoffice_role using (true);
create policy users_backoffice on app.users for select to app_backoffice_role using (true);
create policy memberships_backoffice on app.memberships for select to app_backoffice_role
  using (true);
create policy groups_backoffice on app.groups for select to app_backoffice_role using (true);
create policy group_members_backoffice on app.group_members for select to app_backoffice_role
  using (true);
create policy workspaces_backoffice on app.workspaces for select to app_backoffice_role
  using (true);
create policy tenant_features_backoffice on app.tenant_features for select to app_backoffice_role
  using (true);
create policy tenant_branding_backoffice on app.tenant_branding for select to app_backoffice_role
  using (true);

-- ---------------------------------------------------------------------------- privilégios
revoke all on all tables in schema app from public;

-- a aplicação nunca altera products, plan nem status do tenant (só o back-office/provisionamento)
grant select on app.tenants to app_user_role;
grant update (settings) on app.tenants to app_user_role;
grant select, insert on app.users to app_user_role;
grant update (display_name) on app.users to app_user_role;
grant select, insert, delete on app.memberships to app_user_role;
grant update (role, status) on app.memberships to app_user_role;
grant select, insert, update, delete on app.groups, app.group_members, app.workspaces
  to app_user_role;
grant select on app.tenant_features to app_user_role;
grant select, insert, update on app.tenant_branding to app_user_role;

grant select on app.tenants, app.users, app.memberships, app.groups, app.group_members,
  app.workspaces, app.tenant_features, app.tenant_branding, app.platform_staff
  to app_backoffice_role;

-- tabelas futuras: nada por omissão (cada migração faz os seus grants)
alter default privileges in schema app revoke all on tables from public;

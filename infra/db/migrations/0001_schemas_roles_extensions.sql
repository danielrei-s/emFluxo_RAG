-- F7-T01: schemas, extensões e roles. Idêntico em testes, staging (Supabase) e produção.
create schema if not exists extensions;
create extension if not exists vector with schema extensions;
create extension if not exists unaccent with schema extensions;
create schema if not exists app;
create schema if not exists app_meta;

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'app_user_role') then
    create role app_user_role nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'app_worker_role') then
    create role app_worker_role nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'app_backoffice_role') then
    create role app_backoffice_role nologin;
  end if;
end $$;

grant app_user_role to app_worker_role;
revoke all on schema app from public;
grant usage on schema app, extensions to app_user_role, app_backoffice_role;

-- No Supabase, anon e authenticated existem e nunca podem tocar no schema app.
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on schema app from anon';
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    execute 'revoke all on schema app from authenticated';
  end if;
end $$;

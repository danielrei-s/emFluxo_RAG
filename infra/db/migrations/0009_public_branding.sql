-- F9-T03: leitura pública (sem sessão) só do que o ecrã de login precisa. Função SECURITY DEFINER
-- que devolve apenas campos de marca de tenants ativos; o dono tem de poder ignorar o RLS
-- (no Supabase o papel postgres tem BYPASSRLS; nos testes é superutilizador).
create function app.public_branding(p_slug text)
  returns table (assistant_name text, primary_color text, logo_blob_key text)
  language sql stable security definer
  set search_path = app, pg_temp
  as $$
    select b.assistant_name, b.primary_color, b.logo_blob_key
    from app.tenants t join app.tenant_branding b on b.tenant_id = t.id
    where t.slug = p_slug and t.status = 'active'
  $$;
revoke all on function app.public_branding(text) from public;
grant execute on function app.public_branding(text) to app_user_role;

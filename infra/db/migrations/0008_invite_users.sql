-- F8-T10: um owner/admin do tenant atual pode criar a linha de um utilizador convidado.
-- A verificação do papel é feita na BD (defesa em profundidade), não só na API.
create policy users_insert_by_tenant_admin on app.users for insert to app_user_role
  with check (
    app.current_tenant() is not null
    and exists (
      select 1 from app.memberships m
      where m.tenant_id = app.current_tenant()
        and m.user_id = app.current_user_id()
        and m.role in ('owner', 'admin')
        and m.status = 'active'
    )
  );

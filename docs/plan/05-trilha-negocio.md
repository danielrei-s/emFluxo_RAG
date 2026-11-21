<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# PARTE F — Trilha não técnica (negócio, legal, contas)

Coisas que não são código mas condicionam o calendário. Nenhuma é tarefa de agente; os agentes podem preparar rascunhos quando pedido.

1. **Setor e cliente piloto** — escolher o primeiro setor e 1–2 clientes (idealmente um para cada produto). Condiciona F14 e o perfil de setor da F18.
2. **Modelo de preços e licenciamento** — Produto A por utilizador ou por tenant; Produto B por posto, por dispositivo ou por tenant (questão em aberto da especificação, secção 9). Condiciona F18-T04 e o desenho da licença offline (F11-T11).
3. **Contratos** — DPA (somos subcontratante), termos de serviço, política de privacidade, DPIA modelo, lista pública de subcontratantes (F13-T08, HR-20).
4. **Marca e domínio** — nome comercial, domínio, email transacional (HR-06, HR-26).
5. **Contas e custos** — preços indicativos, **a confirmar antes de cada transição** e registar em ADR (a especificação já o exige):

| Item | MVP | Comercial |
|---|---|---|
| Vercel | Hobby (só uso não comercial) | Pro (por utilizador/mês) |
| Supabase | Free (UE; projetos inativos pausam; sem backups descarregáveis) | Pro, com backups e PITR opcional |
| Máquina 1 | eletricidade + internet | substituída por cloud UE |
| Cloudflare | Free (DNS, tunnel, Access até ao limite gratuito) | Pro (WAF) |
| Hugging Face | créditos gratuitos (só dados de teste) | endpoints dedicados com scale-to-zero (pago por hora) |
| Code signing | certificado de teste | Apple Developer Program (anual) + certificado Windows OV/EV ou serviço de assinatura |
| Verificação Google (scopes restritos) | — | avaliação de segurança anual paga (só se usar Drive/Gmail com scopes restritos) |

6. **Seguro e responsabilidade** — avaliar seguro de responsabilidade civil profissional/ciber antes de clientes pagantes.
7. **Suporte** — canal, horário e SLA do piloto.

---


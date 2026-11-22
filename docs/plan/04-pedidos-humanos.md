<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# PARTE E — Pedidos humanos previstos

Estes são os momentos em que um agente vai precisar do OLEK. Cada um já tem ID; o agente regista-o em `docs/HUMAN_REQUESTS.md` (formato G3) quando chegar a altura. **Segredos nunca vão para o chat**: vão para `.env.local` ou para o gestor de segredos, com o nome de variável indicado.

| ID | Pedido | Tarefas | Bloqueia? | Como entregar |
|---|---|---|---|---|
| HR-01 | Repositório GitHub privado, nome do projeto e titular legal (para a `LICENSE`); branch protection e Dependabot | F0-T01, F0-T10 | Não (trabalha-se num repo local) | Convidar o agente/conta de CI; responder com o nome do titular |
| HR-02 | SO, Docker e GPU nas Máquinas 1 e 2 (drivers NVIDIA + container toolkit ou WSL2) | F0-T11 | Não | Responder com SO e versões; confirmar `docker run --gpus all` |
| HR-03 | Rever as perguntas do golden set (PT-PT natural) | F2-T02 | Não | Comentários no PR |
| HR-04 | Decisão sobre `.msg` no desktop (biblioteca com licença compatível ou "não suportado") | F3-T07 | Não | Escolher uma opção |
| HR-05 | Máquina 1 pronta (Ollama com GPU, modelos descarregados) e execução de benchmarks e testes de carga | F5-T05, F6-T07, F13-T05 | **Sim** (M1 e dimensão do vetor) | Correr `make bench` ou dar acesso SSH; partilhar o relatório |
| HR-06 | Cloudflare: conta, domínio, tunnel, DNS e rotas | F6-T07, F8-T11, F10-T10 | Sim (deploy) | Token do tunnel em `/etc/rag/cloudflared.env` na Máquina 1 |
| HR-07 | Máquina 1 como servidor: disco encriptado, firewall fechado, arranque automático | F6-T07 | Sim (deploy) | Confirmar "feito" seguindo `runbooks/machine1-setup.md` |
| HR-08 | Hugging Face (opcional): conta, token, endpoint dedicado na UE, custos | F6-T08 | Não | `RAG_LLM_API_KEY_RAG_FALLBACK_HF` no gestor de segredos |
| HR-09 | Supabase: projeto na UE, chaves JWT assimétricas, MFA TOTP, SMTP próprio, redirect URLs; correr o bootstrap de roles | F7-T05, F8-T11 | Sim (staging) | URLs em `.env.local`; service role key e passwords no gestor de segredos |
| HR-10 | Gestor de segredos (Infisical ou Doppler) e segredos de staging | F8-T11 | Sim (staging) | Convite para o projeto de segredos |
| HR-11 | Back-office: Cloudflare Access (só o teu email) e utilizador staff | F10-T09 | Sim (back-office em staging) | Confirmar "feito"; email do utilizador staff |
| HR-12 | Ativar o OAuth 2.1 Server do Supabase e registar o cliente "desktop" (redirect loopback); aprovar a ADR-0010 | F10-T08, F11-T08, F8-T12 | Sim (login do Produto B) | `client_id` em `.env.local` |
| HR-13 | Vercel: contas e projetos, região UE; passar a Pro antes de um cliente pagante | F10-T10, F14-T01 | Sim (deploy web) | Convite para a equipa Vercel |
| HR-14 | Gerar a chave de assinatura de atualizações do Tauri e escolher o alojamento público das atualizações | F12-T05 | Sim (release desktop) | Chave privada como segredo do GitHub `TAURI_SIGNING_PRIVATE_KEY`; pública no PR |
| HR-15 | Certificados comerciais de code signing (Apple Developer ID; Windows OV/EV ou serviço de assinatura) | F12-T05, F14-T01 | Antes do piloto do Produto B | Certificados como segredos do GitHub |
| HR-16 | Revisão manual da checklist de pentest da app | F12-T06 | Não | Comentários no PR |
| HR-17 | Contas Grafana Cloud e Sentry (free) | F13-T03 | Não | DSN/endpoint no gestor de segredos |
| HR-18 | Armazenamento externo para backups + par de chaves `age` (privada offline) | F13-T04 | Sim (M6) | Credenciais do bucket no gestor de segredos; chave pública no PR |
| HR-19 | Aprovar o gate de segurança e aceitar os riscos residuais | F13-T06 | Sim (M6) | Aprovação escrita no PR |
| HR-20 | Validação jurídica dos documentos legais | F13-T08 | Sim (antes de vender) | Versões validadas em `docs/legal/` |
| HR-21 | Cliente(s) piloto, DPA e DPIA assinados | F14-T01 | Sim (F14) | Confirmação; documentos guardados fora do repo |
| HR-22 | Recolher 50–200 perguntas e respostas reais com o cliente | F14-T02 | Sim (F14-T02) | Ficheiro no armazenamento encriptado do piloto |
| HR-23 | Google: decisão sobre scopes restritos (verificação de segurança anual) | F15, F16 | Sim (conectores Google) | Decisão + projeto Google Cloud |
| HR-24 | Microsoft: registo de app Entra ID e consentimento de administrador | F15, F16 | Sim (conectores Microsoft) | IDs da app em `.env.local`; segredo no gestor |
| HR-25 | Stripe e faturação certificada PT | F18-T04 | Sim (F18-T04) | Chaves no gestor de segredos |
| HR-26 | Domínio de envio de email (Resend: SPF/DKIM) para convites | F8-T10, F9-T01 | Não (fake nos testes) | Confirmar DNS; chave da API no gestor de segredos |
| HR-27 | Modelo de OCR latino (acentos portugueses) para o RapidOCR | F3-T08 | Não | Decisão por escrito; o agente fixa revisão e sha256 em `models.yaml` |

---


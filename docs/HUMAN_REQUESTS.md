<!-- Gerado por split_plan.py a partir do plano em ficheiro único. Não editar à mão. -->

# Pedidos humanos (HR)

Registo dos pedidos ao OLEK. Formato: Parte G3 do plano. Segredos nunca no chat.

### HR-01 · Repositório GitHub privado, nome do projeto e titular legal (para a `LICENSE`); branch protection e Dependabot
- **Tarefa:** F0-T01, F0-T10 · **Bloqueante:** Não (trabalha-se num repo local)
- **Preciso de:** Repositório GitHub privado, nome do projeto e titular legal (para a `LICENSE`); branch protection e Dependabot
- **Como entregar:** Convidar o agente/conta de CI; responder com o nome do titular
- **Estado:** previsto

### HR-02 · SO, Docker e GPU nas Máquinas 1 e 2 (drivers NVIDIA + container toolkit ou WSL2)
- **Tarefa:** F0-T11 · **Bloqueante:** Não
- **Preciso de:** SO, Docker e GPU nas Máquinas 1 e 2 (drivers NVIDIA + container toolkit ou WSL2)
- **Como entregar:** Responder com SO e versões; confirmar `docker run --gpus all`
- **Estado:** previsto

### HR-03 · Rever as perguntas do golden set (PT-PT natural)
- **Tarefa:** F2-T02 · **Bloqueante:** Não
- **Preciso de:** Rever as perguntas do golden set (PT-PT natural)
- **Como entregar:** Comentários no PR
- **Estado:** previsto

### HR-04 · Decisão sobre `.msg` no desktop (biblioteca com licença compatível ou "não suportado")
- **Tarefa:** F3-T07 · **Bloqueante:** Não
- **Preciso de:** Decisão sobre `.msg` no desktop (biblioteca com licença compatível ou "não suportado")
- **Como entregar:** Escolher uma opção
- **Estado:** previsto

### HR-05 · Máquina 1 pronta (Ollama com GPU, modelos descarregados) e execução de benchmarks e testes de carga
- **Tarefa:** F5-T05, F6-T07, F13-T05 · **Bloqueante:** **Sim** (M1 e dimensão do vetor)
- **Preciso de:** Máquina 1 pronta (Ollama com GPU, modelos descarregados) e execução de benchmarks e testes de carga
- **Como entregar:** Correr `make bench` ou dar acesso SSH; partilhar o relatório
- **Estado:** previsto

### HR-06 · Cloudflare: conta, domínio, tunnel, DNS e rotas
- **Tarefa:** F6-T07, F8-T11, F10-T10 · **Bloqueante:** Sim (deploy)
- **Preciso de:** Cloudflare: conta, domínio, tunnel, DNS e rotas
- **Como entregar:** Token do tunnel em `/etc/rag/cloudflared.env` na Máquina 1
- **Estado:** previsto

### HR-07 · Máquina 1 como servidor: disco encriptado, firewall fechado, arranque automático
- **Tarefa:** F6-T07 · **Bloqueante:** Sim (deploy)
- **Preciso de:** Máquina 1 como servidor: disco encriptado, firewall fechado, arranque automático
- **Como entregar:** Confirmar "feito" seguindo `runbooks/machine1-setup.md`
- **Estado:** previsto

### HR-08 · Hugging Face (opcional): conta, token, endpoint dedicado na UE, custos
- **Tarefa:** F6-T08 · **Bloqueante:** Não
- **Preciso de:** Hugging Face (opcional): conta, token, endpoint dedicado na UE, custos
- **Como entregar:** `RAG_LLM_API_KEY_RAG_FALLBACK_HF` no gestor de segredos
- **Estado:** previsto

### HR-09 · Supabase: projeto na UE, chaves JWT assimétricas, MFA TOTP, SMTP próprio, redirect URLs; correr o bootstrap de roles
- **Tarefa:** F7-T05, F8-T11 · **Bloqueante:** Sim (staging)
- **Preciso de:** Supabase: projeto na UE, chaves JWT assimétricas, MFA TOTP, SMTP próprio, redirect URLs; correr o bootstrap de roles
- **Como entregar:** URLs em `.env.local`; service role key e passwords no gestor de segredos
- **Estado:** previsto

### HR-10 · Gestor de segredos (Infisical ou Doppler) e segredos de staging
- **Tarefa:** F8-T11 · **Bloqueante:** Sim (staging)
- **Preciso de:** Gestor de segredos (Infisical ou Doppler) e segredos de staging
- **Como entregar:** Convite para o projeto de segredos
- **Estado:** previsto

### HR-11 · Back-office: Cloudflare Access (só o teu email) e utilizador staff
- **Tarefa:** F10-T09 · **Bloqueante:** Sim (back-office em staging)
- **Preciso de:** Back-office: Cloudflare Access (só o teu email) e utilizador staff
- **Como entregar:** Confirmar "feito"; email do utilizador staff
- **Estado:** previsto

### HR-12 · Ativar o OAuth 2.1 Server do Supabase e registar o cliente "desktop" (redirect loopback); aprovar a ADR-0010
- **Tarefa:** F10-T08, F11-T08, F8-T12 · **Bloqueante:** Sim (login do Produto B)
- **Preciso de:** Ativar o OAuth 2.1 Server do Supabase e registar o cliente "desktop" (redirect loopback); aprovar a ADR-0010
- **Como entregar:** `client_id` em `.env.local`
- **Estado:** previsto

### HR-13 · Vercel: contas e projetos, região UE; passar a Pro antes de um cliente pagante
- **Tarefa:** F10-T10, F14-T01 · **Bloqueante:** Sim (deploy web)
- **Preciso de:** Vercel: contas e projetos, região UE; passar a Pro antes de um cliente pagante
- **Como entregar:** Convite para a equipa Vercel
- **Estado:** previsto

### HR-14 · Gerar a chave de assinatura de atualizações do Tauri e escolher o alojamento público das atualizações
- **Tarefa:** F12-T05 · **Bloqueante:** Sim (release desktop)
- **Preciso de:** Gerar a chave de assinatura de atualizações do Tauri e escolher o alojamento público das atualizações
- **Como entregar:** Chave privada como segredo do GitHub `TAURI_SIGNING_PRIVATE_KEY`; pública no PR
- **Estado:** previsto

### HR-15 · Certificados comerciais de code signing (Apple Developer ID; Windows OV/EV ou serviço de assinatura)
- **Tarefa:** F12-T05, F14-T01 · **Bloqueante:** Antes do piloto do Produto B
- **Preciso de:** Certificados comerciais de code signing (Apple Developer ID; Windows OV/EV ou serviço de assinatura)
- **Como entregar:** Certificados como segredos do GitHub
- **Estado:** previsto

### HR-16 · Revisão manual da checklist de pentest da app
- **Tarefa:** F12-T06 · **Bloqueante:** Não
- **Preciso de:** Revisão manual da checklist de pentest da app
- **Como entregar:** Comentários no PR
- **Estado:** previsto

### HR-17 · Contas Grafana Cloud e Sentry (free)
- **Tarefa:** F13-T03 · **Bloqueante:** Não
- **Preciso de:** Contas Grafana Cloud e Sentry (free)
- **Como entregar:** DSN/endpoint no gestor de segredos
- **Estado:** previsto

### HR-18 · Armazenamento externo para backups + par de chaves `age` (privada offline)
- **Tarefa:** F13-T04 · **Bloqueante:** Sim (M6)
- **Preciso de:** Armazenamento externo para backups + par de chaves `age` (privada offline)
- **Como entregar:** Credenciais do bucket no gestor de segredos; chave pública no PR
- **Estado:** previsto

### HR-19 · Aprovar o gate de segurança e aceitar os riscos residuais
- **Tarefa:** F13-T06 · **Bloqueante:** Sim (M6)
- **Preciso de:** Aprovar o gate de segurança e aceitar os riscos residuais
- **Como entregar:** Aprovação escrita no PR
- **Estado:** previsto

### HR-20 · Validação jurídica dos documentos legais
- **Tarefa:** F13-T08 · **Bloqueante:** Sim (antes de vender)
- **Preciso de:** Validação jurídica dos documentos legais
- **Como entregar:** Versões validadas em `docs/legal/`
- **Estado:** previsto

### HR-21 · Cliente(s) piloto, DPA e DPIA assinados
- **Tarefa:** F14-T01 · **Bloqueante:** Sim (F14)
- **Preciso de:** Cliente(s) piloto, DPA e DPIA assinados
- **Como entregar:** Confirmação; documentos guardados fora do repo
- **Estado:** previsto

### HR-22 · Recolher 50–200 perguntas e respostas reais com o cliente
- **Tarefa:** F14-T02 · **Bloqueante:** Sim (F14-T02)
- **Preciso de:** Recolher 50–200 perguntas e respostas reais com o cliente
- **Como entregar:** Ficheiro no armazenamento encriptado do piloto
- **Estado:** previsto

### HR-23 · Google: decisão sobre scopes restritos (verificação de segurança anual)
- **Tarefa:** F15, F16 · **Bloqueante:** Sim (conectores Google)
- **Preciso de:** Google: decisão sobre scopes restritos (verificação de segurança anual)
- **Como entregar:** Decisão + projeto Google Cloud
- **Estado:** previsto

### HR-24 · Microsoft: registo de app Entra ID e consentimento de administrador
- **Tarefa:** F15, F16 · **Bloqueante:** Sim (conectores Microsoft)
- **Preciso de:** Microsoft: registo de app Entra ID e consentimento de administrador
- **Como entregar:** IDs da app em `.env.local`; segredo no gestor
- **Estado:** previsto

### HR-25 · Stripe e faturação certificada PT
- **Tarefa:** F18-T04 · **Bloqueante:** Sim (F18-T04)
- **Preciso de:** Stripe e faturação certificada PT
- **Como entregar:** Chaves no gestor de segredos
- **Estado:** previsto

### HR-26 · Domínio de envio de email (Resend: SPF/DKIM) para convites
- **Tarefa:** F8-T10, F9-T01 · **Bloqueante:** Não (fake nos testes)
- **Preciso de:** Domínio de envio de email (Resend: SPF/DKIM) para convites
- **Como entregar:** Confirmar DNS; chave da API no gestor de segredos
- **Estado:** previsto

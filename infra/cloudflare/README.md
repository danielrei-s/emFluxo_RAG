# Cloudflare Tunnel para o gateway (HR-06)

O gateway **não tem portas abertas** na Máquina 1: o `cloudflared` liga para fora e o Cloudflare
encaminha `https://gw.<domínio>` para `gateway:8080` pela rede `edge` do compose de produção
(`infra/compose/docker-compose.prod.yml`). O OLEK faz estes passos; nada daqui fica no repositório.

## 1. Criar o tunnel

1. Cloudflare → **Zero Trust → Networks → Tunnels → Create a tunnel** (tipo _Cloudflared_), nome
   `rag-gateway-staging`.
2. Copiar o **token** do tunnel e guardá-lo na Máquina 1 em `/etc/rag/cloudflared.env`:

   ```
   TUNNEL_TOKEN=<token>
   ```

   Permissões: `chmod 600`, dono `root`. O token nunca vai para o chat, para o Git nem para o
   histórico do shell.

## 2. Hostname público

No separador **Public Hostname** do tunnel:

| Campo     | Valor                |
| --------- | -------------------- |
| Subdomain | `gw`                 |
| Domain    | o domínio do projeto |
| Type      | `HTTP`               |
| URL       | `gateway:8080`       |

O DNS (`CNAME` proxied) é criado pelo Cloudflare. Não publicar `ollama`, a Central API nem outro
serviço por este tunnel.

## 3. Regras básicas (WAF e rate limit)

Em **Security → WAF → Custom rules** e **Rate limiting rules** do domínio:

- bloquear pedidos a `gw.<domínio>` cujo caminho não comece por `/v1/`, `/healthz` ou `/readyz`;
- limitar `POST /v1/chat/completions` por IP (por exemplo 60 pedidos/minuto), com resposta 429;
- ativar **Bot Fight Mode** e **TLS mínimo 1.2**, **Always Use HTTPS**;
- o limite fino por utilizador e por tenant é do próprio gateway (F6-T03); o do Cloudflare é só a
  primeira barreira.

## 4. Verificar

```powershell
python scripts/smoke_gateway.py --url https://gw.<domínio> --token-file token.txt
```

Sem `--token-file` o script só verifica `/healthz`, `/readyz` e que um pedido sem token dá 401.
O token de staging (serviço) vem de quem opera a Central API ou de um JWKS de desenvolvimento
(`RAG_CENTRAL_JWKS_URL`); esse caminho desaparece na F8-T11.

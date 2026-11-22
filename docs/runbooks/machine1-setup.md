# Máquina 1: preparação como servidor (HR-05, HR-07)

Máquina 1 = a que tem GPU e corre o gateway e o Ollama (MVP). Objetivo: estar pronta a correr
`infra/compose/docker-compose.prod.yml` sem que nada fique exposto à rede.

## 1. Disco encriptado

- **Windows 11 Pro:** BitLocker no disco do sistema e no que guarda os volumes Docker
  (Painel de controlo → BitLocker; guardar a chave de recuperação fora da máquina).
- **Linux:** LUKS na instalação, ou `cryptsetup` para a partição de dados.

Confirmar: `manage-bde -status` (Windows) ou `lsblk -f` (Linux) mostra o volume encriptado.

## 2. Drivers NVIDIA e Docker com GPU

1. Driver NVIDIA atualizado; `nvidia-smi` lista a GPU.
2. Docker Desktop (WSL2) ou Docker Engine + **NVIDIA Container Toolkit**.
3. Teste: `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.

## 3. Firewall fechado

- Bloquear **todas as entradas** (nenhuma porta aberta: o acesso externo é só pelo tunnel).
- Permitir saídas HTTPS (443) e DNS. SSH só pela rede local ou por VPN, nunca pela Internet.
- Confirmar de outra máquina da internet que `nmap <ip-público>` não mostra portas abertas.

## 4. Ficheiros de configuração (fora do repositório)

Em `/etc/rag/` (no Windows, a pasta montada no WSL2 ou o caminho equivalente definido no compose),
dono `root`, modo `0600`:

| Ficheiro          | Conteúdo                                                                 |
| ----------------- | ------------------------------------------------------------------------ |
| `gateway.env`     | `RAG_ENV=staging`, `RAG_CENTRAL_ISSUER`, `RAG_CENTRAL_JWKS_URL`          |
| `cloudflared.env` | token do tunnel (ver `infra/cloudflare/README.md`)                       |
| `models.yaml`     | registo de modelos (a partir de `models.example.yaml`, após a ADR-0009)  |
| `policies.yaml`   | `tenants:` com a política de cada tenant (`allowed_models`, quotas, ...) |

Nunca colocar segredos no `docker-compose.prod.yml`: há um teste (`test_inv13_no_inline_secrets`).

## 5. Arranque automático

- Docker a arrancar com o sistema (Docker Desktop: _Start when you sign in_ + início de sessão
  automático, ou serviço do Docker Engine em Linux).
- Os serviços têm `restart: unless-stopped`, por isso voltam sozinhos depois de um reinício.
- Ligar a máquina à energia com UPS se possível, e configurar "ligar após falha de energia" na BIOS.

## 6. Primeiro arranque

```powershell
docker compose -f infra/compose/docker-compose.prod.yml up -d --build
docker compose -f infra/compose/docker-compose.prod.yml exec ollama ollama pull <modelo da ADR-0009>
docker compose -f infra/compose/docker-compose.prod.yml ps
python scripts/smoke_gateway.py --url https://gw.<domínio> --token-file token.txt
```

Todos os serviços têm de ficar `healthy` e o smoke tem de terminar com `smoke OK`.

## 7. Confirmar ao agente

Responder "feito" com: resultado do `smoke_gateway.py`, `docker compose ps` e confirmação de que o
firewall não tem portas abertas. Os valores dos segredos **não** vão no chat.

"""Chaves de assinatura da Central (Ed25519) e emissão de tokens (F8-T01; INV-13).

``RAG_CENTRAL_SIGNING_KEYS`` é um JSON ``[{"kid": "...", "pem": "-----BEGIN PRIVATE KEY..."}]``:
a primeira chave assina, todas ficam no JWKS (assim a rotação não invalida tokens em circulação).
O JWKS publicado só tem material público.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from pydantic import SecretStr
from rag_core.errors import ValidationFailed
from rag_core.interfaces import Clock

SERVICE_AUDIENCE = "rag-gateway"
ENTITLEMENT_AUDIENCE = "rag-local"
SERVICE_TTL_S = 60
ENTITLEMENT_TTL = timedelta(days=7)


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private: ed25519.Ed25519PrivateKey


def generate_keys_json(*kids: str) -> str:
    """Gera chaves novas no formato de ``RAG_CENTRAL_SIGNING_KEYS`` (para o provisionamento)."""
    entries = []
    for kid in kids:
        pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        entries.append({"kid": kid, "pem": pem.decode("ascii")})
    return json.dumps(entries)


def load_keys(secret: SecretStr | None) -> list[SigningKey]:
    if secret is None:
        raise ValidationFailed(subcode="signing_keys_missing")
    try:
        entries = json.loads(secret.get_secret_value())
        keys = [
            SigningKey(str(e["kid"]), _ed25519(serialization.load_pem_private_key(
                str(e["pem"]).encode("ascii"), password=None
            )))
            for e in entries
        ]  # fmt: skip
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationFailed(subcode="signing_keys_invalid") from exc  # sem eco do segredo
    if not keys or len({k.kid for k in keys}) != len(keys):
        raise ValidationFailed(subcode="signing_keys_invalid")
    return keys


def _ed25519(key: Any) -> ed25519.Ed25519PrivateKey:
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise ValueError("not_ed25519")
    return key


class Signer:
    def __init__(self, keys: list[SigningKey], issuer: str, clock: Clock) -> None:
        self._keys = list(keys)
        self._issuer = issuer
        self._clock = clock

    def jwks(self) -> dict[str, Any]:
        """Só chaves públicas (nunca o parâmetro ``d``)."""
        algorithm = pyjwt.algorithms.OKPAlgorithm()
        public = []
        for key in self._keys:
            jwk: dict[str, Any] = json.loads(algorithm.to_jwk(key.private.public_key()))
            public.append({**jwk, "kid": key.kid, "use": "sig", "alg": "EdDSA"})
        return {"keys": public}

    def _sign(self, claims: dict[str, Any]) -> str:
        key = self._keys[0]
        # Os claims só levam identificadores, produtos e prazos (testado: sem conteúdo).
        # nosemgrep: python.jwt.security.audit.jwt-exposed-data.jwt-python-exposed-data
        return pyjwt.encode(claims, key.private, algorithm="EdDSA", headers={"kid": key.kid})

    def _base(self, audience: str, subject: str, ttl: timedelta) -> dict[str, Any]:
        now = self._clock.now()
        return {
            "iss": self._issuer,
            "aud": audience,
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
            "jti": uuid.uuid4().hex,  # um identificador por token
        }

    def mint_service_token(
        self, tenant_id: str, user_id: str, purpose: str, ttl_s: int = SERVICE_TTL_S
    ) -> str:
        """Token curto (≤ 60 s) para a Central API falar com o gateway em nome de um utilizador."""
        claims = self._base(SERVICE_AUDIENCE, "svc-central", timedelta(seconds=ttl_s))
        claims |= {"typ": "service", "tenant_id": tenant_id, "user_id": user_id, "purpose": purpose}
        return self._sign(claims)

    def mint_entitlement_token(
        self,
        user_id: str,
        tenant_id: str,
        device_id: str,
        products: list[str],
        ttl: timedelta = ENTITLEMENT_TTL,
    ) -> str:
        """Licença do dispositivo (F8-T07): só identificadores e produtos, nenhum conteúdo."""
        claims = self._base(ENTITLEMENT_AUDIENCE, user_id, ttl)
        claims |= {
            "typ": "entitlement",
            "tenant_id": tenant_id,
            "device_id": device_id,
            "products": sorted(products),
        }
        return self._sign(claims)

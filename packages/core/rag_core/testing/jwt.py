"""Gerador de tokens e JWKS de teste (F6-T02): chaves Ed25519/RSA e tokens válidos e inválidos."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

ISSUER = "https://central.test"
AUDIENCE = "rag-gateway"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class JwtFactory:
    """Duas chaves (Ed25519 ``ed-1`` e RSA ``rsa-1``), o seu JWKS e a emissão de tokens."""

    def __init__(self, issuer: str = ISSUER, audience: str = AUDIENCE) -> None:
        self.issuer, self.audience = issuer, audience
        self._ed = ed25519.Ed25519PrivateKey.generate()
        self._rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._extra: dict[str, Any] = {}  # chaves publicadas depois (rotação)

    # ------------------------------------------------------------------ JWKS

    def _public_jwk(self, key: Any, kid: str, alg: str) -> dict[str, Any]:
        jwk: dict[str, Any] = json.loads(pyjwt.algorithms.get_default_algorithms()[alg].to_jwk(key))
        return {**jwk, "kid": kid, "use": "sig", "alg": alg}

    def jwks(self) -> dict[str, Any]:
        keys = [
            self._public_jwk(self._ed.public_key(), "ed-1", "EdDSA"),
            self._public_jwk(self._rsa.public_key(), "rsa-1", "RS256"),
        ]
        keys += [self._public_jwk(k.public_key(), kid, "EdDSA") for kid, k in self._extra.items()]
        return {"keys": keys}

    def rotate(self, kid: str = "ed-2") -> str:
        """Publica uma chave nova no JWKS (para o teste de ``kid`` desconhecido → atualização)."""
        self._extra[kid] = ed25519.Ed25519PrivateKey.generate()
        return kid

    def public_pem(self) -> bytes:
        return self._ed.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    # ---------------------------------------------------------------- tokens

    def claims(self, **overrides: Any) -> dict[str, Any]:
        now = int(time.time())
        base: dict[str, Any] = {
            "iss": self.issuer, "aud": self.audience, "sub": "svc-central",
            "iat": now, "exp": now + 30,
        }  # fmt: skip
        return {**base, **overrides}

    def service_claims(self, **overrides: Any) -> dict[str, Any]:
        return self.claims(
            **{"typ": "service", "tenant_id": "t1", "user_id": "u1", "purpose": "chat", **overrides}
        )

    def issue(self, claims: dict[str, Any] | None = None, *, kid: str = "ed-1") -> str:
        """Token assinado com a chave publicada sob ``kid`` (``ed-*`` Ed25519, ``rsa-1`` RSA)."""
        payload = claims if claims is not None else self.service_claims()
        if kid == "rsa-1":
            return pyjwt.encode(payload, self._rsa, algorithm="RS256", headers={"kid": kid})
        key = self._ed if kid == "ed-1" else self._extra[kid]
        return pyjwt.encode(payload, key, algorithm="EdDSA", headers={"kid": kid})

    def expired(self) -> str:
        now = int(time.time())
        return self.issue(self.service_claims(iat=now - 400, exp=now - 300))

    def wrong_audience(self) -> str:
        return self.issue(self.service_claims(aud="outro-servico"))

    def alg_none(self, claims: dict[str, Any] | None = None) -> str:
        header = _b64(json.dumps({"alg": "none", "typ": "JWT", "kid": "ed-1"}).encode())
        payload = _b64(json.dumps(claims or self.service_claims()).encode())
        return f"{header}.{payload}."

    def hs256_with_public_key(self, claims: dict[str, Any] | None = None) -> str:
        """Ataque de confusão de chaves: HS256 assinado com a chave pública como segredo."""
        header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "ed-1"}).encode())
        payload = _b64(json.dumps(claims or self.service_claims()).encode())
        signing_input = f"{header}.{payload}".encode("ascii")
        signature = hmac.new(self.public_pem(), signing_input, hashlib.sha256).digest()
        return f"{header}.{payload}.{_b64(signature)}"

    def unknown_kid(self) -> str:
        token = self.issue()
        _, payload, signature = token.split(".")
        forged = _b64(json.dumps({"alg": "EdDSA", "typ": "JWT", "kid": "nao-existe"}).encode())
        return f"{forged}.{payload}.{signature}"

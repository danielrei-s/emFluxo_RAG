"""Verificação de JWT por JWKS (F6-T02): robusta contra ``alg=none`` e confusão de chaves."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

import httpx
import jwt
from jwt import PyJWK

from rag_core.auth.claims import REQUIRED_CLAIMS
from rag_core.clock import SystemClock
from rag_core.config import Env, is_loopback_url
from rag_core.errors import Unauthenticated, UpstreamError
from rag_core.interfaces import Clock

DEFAULT_ALGORITHMS = ("EdDSA", "RS256", "ES256")
CLOCK_SKEW_S = 30
MIN_REFRESH_INTERVAL_S = 10.0  # um kid desconhecido não pode provocar um fetch por pedido
_FORBIDDEN_PREFIXES = ("HS", "none")

_REASONS: tuple[tuple[type[Exception], str], ...] = (
    (jwt.ExpiredSignatureError, "expired"),
    (jwt.InvalidAudienceError, "audience"),
    (jwt.InvalidIssuerError, "issuer"),
    (jwt.MissingRequiredClaimError, "missing_claim"),
    (jwt.InvalidAlgorithmError, "algorithm"),
    (jwt.InvalidSignatureError, "signature"),
    (jwt.ImmatureSignatureError, "not_yet_valid"),
    (jwt.InvalidIssuedAtError, "issued_at"),
)


def _reason(error: Exception) -> str:
    for cls, reason in _REASONS:
        if isinstance(error, cls):
            return reason
    return "invalid_token"


def _check_jwks_url(url: str, env: Env) -> None:
    scheme = urlsplit(url).scheme.lower()
    if scheme == "file":
        if env == Env.PROD:  # chaves lidas de disco só antes da F8 (staging)
            raise ValueError("jwks_url com file:// não é permitido em produção")
    elif scheme == "http":
        if env == Env.PROD and not is_loopback_url(url):
            raise ValueError("jwks_url tem de ser https em produção")
    elif scheme != "https":
        raise ValueError("jwks_url: esquema não suportado")


class JwksVerifier:
    """Verifica a assinatura e as claims de um JWT com as chaves de um endpoint JWKS."""

    def __init__(
        self,
        jwks_url: str,
        issuer: str,
        audience: str,
        algorithms: tuple[str, ...] = DEFAULT_ALGORITHMS,
        cache_ttl_s: float = 300.0,
        http: httpx.Client | None = None,
        *,
        clock: Clock | None = None,
        env: Env = Env.DEV,
        leeway_s: int = CLOCK_SKEW_S,
    ) -> None:
        if any(alg.upper().startswith(_FORBIDDEN_PREFIXES) or alg == "none" for alg in algorithms):
            raise ValueError("algoritmos simétricos ou 'none' nunca são aceites")
        _check_jwks_url(jwks_url, env)
        self.issuer = issuer
        self._url = jwks_url
        self._audience = audience
        self._algorithms = algorithms
        self._ttl = cache_ttl_s
        self._http = http or httpx.Client(timeout=5.0)
        self._clock = clock or SystemClock()
        self._leeway = leeway_s
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self.fetch_count = 0

    # ------------------------------------------------------------------ chaves

    def _now(self) -> float:
        return self._clock.now().timestamp()

    def _load_document(self) -> Mapping[str, Any]:
        parts = urlsplit(self._url)
        try:
            if parts.scheme == "file":
                return dict(json.loads(Path(url2pathname(parts.path)).read_text("utf-8")))
            response = self._http.get(self._url)
            response.raise_for_status()
            return dict(response.json())
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise UpstreamError("jwks_unavailable") from exc

    def _refresh(self) -> None:
        document = self._load_document()
        keys: dict[str, PyJWK] = {}
        for entry in document.get("keys", []):
            try:
                key = PyJWK(entry)
            except (jwt.PyJWTError, ValueError):  # chave de um tipo não suportado: ignora-a
                continue
            if key.key_id:
                keys[key.key_id] = key
        self._keys = keys
        self._fetched_at = self._now()
        self.fetch_count += 1

    def _stale(self) -> bool:
        return self._fetched_at is None or self._now() - self._fetched_at > self._ttl

    def _may_refresh(self) -> bool:
        return self._fetched_at is None or self._now() - self._fetched_at >= MIN_REFRESH_INTERVAL_S

    def _key_for(self, kid: str) -> PyJWK:
        if self._stale():
            self._refresh()
        # chave nova? uma atualização (no máximo uma por intervalo)
        if kid not in self._keys and self._may_refresh():
            self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise Unauthenticated("unknown_kid")
        return key

    # ---------------------------------------------------------------- verificação

    def verify(self, token: str) -> dict[str, Any]:
        """Devolve as claims de um token válido ou levanta ``Unauthenticated``."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise Unauthenticated("malformed") from exc
        algorithm = str(header.get("alg", ""))
        if algorithm not in self._algorithms:  # recusa "none", HS* e o que não estiver na lista
            raise Unauthenticated("algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise Unauthenticated("missing_kid")
        key = self._key_for(kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self.issuer,
                leeway=self._leeway,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except jwt.PyJWTError as exc:
            raise Unauthenticated(_reason(exc)) from exc
        return claims


class CompositeVerifier:
    """Encaminha o token para o verificador do seu ``iss`` (lido sem verificar, só para isso)."""

    def __init__(self, verifiers: Mapping[str, JwksVerifier]) -> None:
        self._verifiers = dict(verifiers)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise Unauthenticated("malformed") from exc
        issuer = unverified.get("iss")
        verifier = self._verifiers.get(issuer) if isinstance(issuer, str) else None
        if verifier is None:
            raise Unauthenticated("unknown_issuer")
        return verifier.verify(token)

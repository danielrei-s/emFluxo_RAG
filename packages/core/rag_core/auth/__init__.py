"""Autenticação por JWT/JWKS partilhada pelos serviços (F6-T02)."""

from rag_core.auth.claims import ServiceClaims, parse_service_claims
from rag_core.auth.jwks import CompositeVerifier, JwksVerifier

__all__ = ["CompositeVerifier", "JwksVerifier", "ServiceClaims", "parse_service_claims"]

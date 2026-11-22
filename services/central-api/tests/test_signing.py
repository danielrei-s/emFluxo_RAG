"""Testes de F8-T01: chaves de assinatura, JWKS e tokens de serviço/licença (INV-13)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr
from rag_central.signing import Signer, generate_keys_json, load_keys
from rag_core.auth import JwksVerifier, parse_service_claims
from rag_core.clock import SystemClock
from rag_core.errors import Unauthenticated, ValidationFailed

ISSUER = "https://central.test"
URL = "https://central.test/.well-known/jwks.json"


def _signer(*kids: str) -> Signer:
    return Signer(load_keys(SecretStr(generate_keys_json(*kids))), ISSUER, SystemClock())


def _verifier(signer: Signer, audience: str) -> JwksVerifier:
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=signer.jwks()))
    )
    return JwksVerifier(URL, ISSUER, audience, http=http)


def test_inv13_jwks_has_no_private_material() -> None:
    jwks = _signer("k1", "k2").jwks()
    assert [k["kid"] for k in jwks["keys"]] == ["k1", "k2"]
    for key in jwks["keys"]:
        assert "d" not in key and key["kty"] == "OKP" and key["crv"] == "Ed25519"
        assert key["alg"] == "EdDSA" and key["use"] == "sig"
    assert "PRIVATE" not in json.dumps(jwks)


def test_service_token_verifies_with_jwks() -> None:
    signer = _signer("k1")
    token = signer.mint_service_token("t1", "u1", "chat")
    claims = _verifier(signer, "rag-gateway").verify(token)
    service = parse_service_claims(claims)  # as mesmas regras que o gateway aplica
    assert (service.tenant_id, service.user_id, service.purpose) == ("t1", "u1", "chat")
    assert service.exp - service.iat == 60
    with pytest.raises(Unauthenticated):  # audiência errada
        _verifier(signer, "rag-local").verify(token)


def test_first_key_signs_and_all_keys_verify_after_rotation() -> None:
    old_signer = Signer(load_keys(SecretStr(generate_keys_json("antiga"))), ISSUER, SystemClock())
    old_token = old_signer.mint_service_token("t1", "u1", "chat")
    old_entries = json.loads(json.dumps(old_signer_entries(old_signer)))
    assert old_entries == ["antiga"]
    rotated = _rotate(old_signer)
    new_token = rotated.mint_service_token("t1", "u1", "chat")
    assert pyjwt.get_unverified_header(new_token)["kid"] == "nova"
    verifier = _verifier(rotated, "rag-gateway")
    assert verifier.verify(new_token)["tenant_id"] == "t1"
    assert verifier.verify(old_token)["tenant_id"] == "t1"  # tokens em circulação continuam válidos


def old_signer_entries(signer: Signer) -> list[str]:
    return [k["kid"] for k in signer.jwks()["keys"]]


def _rotate(old: Signer) -> Signer:
    """Nova chave à frente (assina) e a antiga mantida (só verifica)."""
    fresh = load_keys(SecretStr(generate_keys_json("nova")))
    return Signer([*fresh, *old._keys], ISSUER, SystemClock())


def test_entitlement_token_is_contentless_and_lasts_seven_days() -> None:
    signer = _signer("k1")
    token = signer.mint_entitlement_token("u1", "t1", "dev1", ["web", "local"])
    claims = _verifier(signer, "rag-local").verify(token)
    assert claims["typ"] == "entitlement" and claims["products"] == ["local", "web"]
    assert claims["device_id"] == "dev1" and claims["sub"] == "u1"
    assert claims["exp"] - claims["iat"] == int(timedelta(days=7).total_seconds())
    assert datetime.fromtimestamp(claims["exp"], UTC) > datetime.now(UTC)
    assert set(claims) == {
        "iss", "aud", "sub", "iat", "exp", "jti", "typ", "tenant_id", "device_id", "products",
    }  # fmt: skip


def test_invalid_key_configuration_is_rejected_without_echoing_it() -> None:
    bad = (
        None,
        SecretStr("não é json SEGREDO"),
        SecretStr("[]"),
        SecretStr(json.dumps([{"kid": "a"}])),
        SecretStr(json.dumps([{"kid": "a", "pem": "SEGREDO"}])),
    )
    for secret in bad:
        with pytest.raises(ValidationFailed) as exc:
            load_keys(secret)
        assert "SEGREDO" not in str(exc.value)
    duplicated = json.loads(generate_keys_json("a")) * 2
    with pytest.raises(ValidationFailed):
        load_keys(SecretStr(json.dumps(duplicated)))
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    with pytest.raises(ValidationFailed):  # só Ed25519
        load_keys(SecretStr(json.dumps([{"kid": "r", "pem": pem.decode()}])))

"""Testes de F6-T02: verificação de JWT por JWKS (INV-14)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from rag_core.auth import CompositeVerifier, JwksVerifier, parse_service_claims
from rag_core.clock import FakeClock
from rag_core.config import Env
from rag_core.errors import Unauthenticated, UpstreamError
from rag_core.testing.jwt import AUDIENCE, ISSUER, JwtFactory

JWKS_URL = "https://central.test/.well-known/jwks.json"


@pytest.fixture
def factory() -> JwtFactory:
    return JwtFactory()


@pytest.fixture
def jwks_route(factory: JwtFactory) -> Iterator[respx.Route]:
    with respx.mock(assert_all_called=False) as router:
        yield router.get(JWKS_URL).mock(
            side_effect=lambda request: httpx.Response(200, json=factory.jwks())
        )


def _verifier(clock: FakeClock | None = None, **kwargs: object) -> JwksVerifier:
    return JwksVerifier(JWKS_URL, ISSUER, AUDIENCE, clock=clock, **kwargs)  # type: ignore[arg-type]


def _reason(verifier: JwksVerifier, token: str) -> str | None:
    with pytest.raises(Unauthenticated) as exc:
        verifier.verify(token)
    return exc.value.detail_id


def test_valid_service_token(factory: JwtFactory, jwks_route: respx.Route) -> None:
    verifier = _verifier()
    claims = verifier.verify(factory.issue())
    service = parse_service_claims(claims)
    assert (service.tenant_id, service.user_id, service.purpose) == ("t1", "u1", "chat")
    assert service.iss == ISSUER
    assert verifier.verify(factory.issue(kid="rsa-1"))["sub"] == "svc-central"  # RS256 também
    assert jwks_route.call_count == 1  # as chaves ficam em cache


def test_expired_rejected(factory: JwtFactory, jwks_route: respx.Route) -> None:
    assert _reason(_verifier(), factory.expired()) == "expired"
    # a tolerância de relógio é de 30 s: 20 s depois de expirar ainda passa, 40 s não
    now = int(time.time())
    assert _verifier().verify(factory.issue(factory.service_claims(iat=now - 50, exp=now - 20)))
    assert (
        _reason(_verifier(), factory.issue(factory.service_claims(iat=now - 70, exp=now - 40)))
        == "expired"
    )


def test_wrong_audience_and_issuer_rejected(factory: JwtFactory, jwks_route: respx.Route) -> None:
    assert _reason(_verifier(), factory.wrong_audience()) == "audience"
    wrong_issuer = factory.issue(factory.service_claims(iss="https://outro.test"))
    assert _reason(_verifier(), wrong_issuer) == "issuer"


def test_required_claims_are_enforced(factory: JwtFactory, jwks_route: respx.Route) -> None:
    for missing in ("exp", "iat", "sub", "iss", "aud"):
        claims = factory.service_claims()
        del claims[missing]
        assert _reason(_verifier(), factory.issue(claims)) in {
            "missing_claim",
            "issuer",
            "audience",
        }, missing
    future = factory.issue(factory.service_claims(iat=int(time.time()) + 3600))
    assert _reason(_verifier(), future) in {"issued_at", "not_yet_valid", "invalid_token"}


def test_inv14_alg_none_rejected(factory: JwtFactory, jwks_route: respx.Route) -> None:
    assert _reason(_verifier(), factory.alg_none()) == "algorithm"
    assert jwks_route.call_count == 0  # recusado antes de ir buscar chaves


def test_inv14_hs256_key_confusion_rejected(factory: JwtFactory, jwks_route: respx.Route) -> None:
    assert _reason(_verifier(), factory.hs256_with_public_key()) == "algorithm"
    with pytest.raises(ValueError):  # nem sequer se pode configurar um algoritmo simétrico
        JwksVerifier(JWKS_URL, ISSUER, AUDIENCE, algorithms=("EdDSA", "HS256"))
    with pytest.raises(ValueError):
        JwksVerifier(JWKS_URL, ISSUER, AUDIENCE, algorithms=("none",))


def test_malformed_and_tampered_tokens(factory: JwtFactory, jwks_route: respx.Route) -> None:
    verifier = _verifier()
    assert _reason(verifier, "isto-nao-e-um-jwt") == "malformed"
    header, _, signature = factory.issue().split(".")
    other_payload = factory.issue(factory.service_claims(tenant_id="outro")).split(".")[1]
    assert _reason(verifier, f"{header}.{other_payload}.{signature}") == "signature"
    no_kid = factory.issue()
    import jwt as pyjwt

    bare = pyjwt.encode(factory.service_claims(), factory._ed, algorithm="EdDSA")
    assert _reason(verifier, bare) == "missing_kid"
    assert no_kid


def test_unknown_kid_refreshes_once(factory: JwtFactory, jwks_route: respx.Route) -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    verifier = _verifier(clock)
    assert verifier.verify(factory.issue())
    assert jwks_route.call_count == 1

    new_kid = factory.rotate()  # o emissor rodou as chaves
    clock.advance(seconds=11)
    assert verifier.verify(factory.issue(kid=new_kid))
    assert jwks_route.call_count == 2  # uma atualização e passou

    clock.advance(seconds=11)
    assert _reason(verifier, factory.unknown_kid()) == "unknown_kid"
    assert jwks_route.call_count == 3  # uma atualização e depois falha
    for _ in range(5):  # kids falsos em série não provocam um fetch por pedido
        assert _reason(verifier, factory.unknown_kid()) == "unknown_kid"
    assert jwks_route.call_count == 3
    clock.advance(seconds=11)
    _reason(verifier, factory.unknown_kid())
    assert jwks_route.call_count == 4


def test_jwks_cache_expires_after_ttl(factory: JwtFactory, jwks_route: respx.Route) -> None:
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    verifier = _verifier(clock, cache_ttl_s=300)
    verifier.verify(factory.issue())
    clock.advance(seconds=200)
    verifier.verify(factory.issue())
    assert jwks_route.call_count == 1
    clock.advance(seconds=200)
    verifier.verify(factory.issue())
    assert jwks_route.call_count == 2 and verifier.fetch_count == 2


def test_jwks_unavailable_is_an_upstream_error(factory: JwtFactory) -> None:
    with respx.mock() as router:
        router.get(JWKS_URL).respond(500, text="CANARIO-corpo")
        with pytest.raises(UpstreamError) as exc:
            _verifier().verify(factory.issue())
    assert exc.value.detail_id == "jwks_unavailable" and "CANARIO" not in str(exc.value)
    with respx.mock() as router:
        router.get(JWKS_URL).mock(side_effect=httpx.ConnectError("sem rede"))
        with pytest.raises(UpstreamError):
            _verifier().verify(factory.issue())
    with respx.mock() as router:  # só chaves de tipos não suportados: kid desconhecido
        router.get(JWKS_URL).respond(200, json={"keys": [{}, {"kty": "desconhecido"}]})
        assert _reason(_verifier(), factory.issue()) == "unknown_kid"


def test_file_jwks_is_only_allowed_outside_prod(factory: JwtFactory, tmp_path: Path) -> None:
    path = tmp_path / "jwks.json"
    path.write_text(json.dumps(factory.jwks()), encoding="utf-8")
    url = path.as_uri()
    assert JwksVerifier(url, ISSUER, AUDIENCE, env=Env.STAGING).verify(factory.issue())
    with pytest.raises(ValueError, match="produção"):
        JwksVerifier(url, ISSUER, AUDIENCE, env=Env.PROD)
    missing = JwksVerifier((tmp_path / "nao-existe.json").as_uri(), ISSUER, AUDIENCE)
    with pytest.raises(UpstreamError):
        missing.verify(factory.issue())


def test_jwks_url_schemes(factory: JwtFactory) -> None:
    JwksVerifier("http://127.0.0.1:9000/jwks", ISSUER, AUDIENCE, env=Env.PROD)  # loopback
    with pytest.raises(ValueError, match="https"):
        JwksVerifier("http://exemplo.test/jwks", ISSUER, AUDIENCE, env=Env.PROD)
    JwksVerifier("http://exemplo.test/jwks", ISSUER, AUDIENCE, env=Env.DEV)
    with pytest.raises(ValueError, match="esquema"):
        JwksVerifier("ftp://exemplo.test/jwks", ISSUER, AUDIENCE)


def test_composite_verifier_routes_by_issuer(factory: JwtFactory) -> None:
    supabase = JwtFactory(issuer="https://supabase.test", audience="authenticated")
    with respx.mock(assert_all_called=False) as router:
        router.get(JWKS_URL).mock(side_effect=lambda r: httpx.Response(200, json=factory.jwks()))
        router.get("https://supabase.test/jwks").mock(
            side_effect=lambda r: httpx.Response(200, json=supabase.jwks())
        )
        composite = CompositeVerifier(
            {
                ISSUER: JwksVerifier(JWKS_URL, ISSUER, AUDIENCE),
                "https://supabase.test": JwksVerifier(
                    "https://supabase.test/jwks", "https://supabase.test", "authenticated"
                ),
            }
        )
        assert composite.verify(factory.issue())["iss"] == ISSUER
        assert composite.verify(supabase.issue(supabase.claims()))["iss"] == "https://supabase.test"
        stranger = JwtFactory(issuer="https://desconhecido.test").issue()
        with pytest.raises(Unauthenticated) as unknown:
            composite.verify(stranger)
        assert unknown.value.detail_id == "unknown_issuer"
        # um token do emissor A assinado pela chave do emissor B falha na assinatura
        forged = supabase.issue(supabase.claims(iss=ISSUER, aud=AUDIENCE))
        with pytest.raises(Unauthenticated):
            composite.verify(forged)
        with pytest.raises(Unauthenticated) as malformed:
            composite.verify("lixo")
        assert malformed.value.detail_id == "malformed"


def test_service_token_without_tenant_rejected(factory: JwtFactory) -> None:
    for claims in (
        factory.service_claims(tenant_id=None),
        factory.service_claims(tenant_id=""),
        factory.service_claims(user_id=""),
        {k: v for k, v in factory.service_claims().items() if k != "user_id"},
    ):
        with pytest.raises(Unauthenticated) as exc:
            parse_service_claims(claims)
        assert exc.value.detail_id == "missing_tenant_or_user"
    with pytest.raises(Unauthenticated) as wrong_type:
        parse_service_claims(factory.claims())  # sem typ="service"
    assert wrong_type.value.detail_id == "not_service_token"
    with pytest.raises(Unauthenticated) as purpose:
        parse_service_claims(factory.service_claims(purpose="admin"))
    assert purpose.value.detail_id == "wrong_purpose"


def test_service_token_ttl_over_60s_rejected(factory: JwtFactory) -> None:
    now = int(time.time())
    assert parse_service_claims(factory.service_claims(iat=now, exp=now + 60))
    with pytest.raises(Unauthenticated) as exc:
        parse_service_claims(factory.service_claims(iat=now, exp=now + 61))
    assert exc.value.detail_id == "ttl_too_long"
    broken = factory.service_claims()
    broken["exp"] = "amanhã"
    with pytest.raises(Unauthenticated) as missing:
        parse_service_claims(broken)
    assert missing.value.detail_id == "missing_claim"


def test_reason_codes_never_carry_free_text() -> None:
    import jwt as pyjwt
    from rag_core.auth.jwks import _reason

    assert _reason(pyjwt.ExpiredSignatureError("texto livre")) == "expired"
    assert _reason(pyjwt.DecodeError("texto livre")) == "invalid_token"

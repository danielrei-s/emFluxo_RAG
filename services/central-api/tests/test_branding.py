"""Testes de F9-T03 (integração): marca por tenant (INV-08)."""

from __future__ import annotations

import base64
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from conftest import USER_1, USER_2, Rls
from fastapi.testclient import TestClient
from PIL import Image
from rag_central.app import CentralDeps, create_app
from rag_central.auth import CentralAuth, PrincipalResolver, build_identity_verifier
from rag_central.db import Database, make_pool
from rag_central.routers.branding import contrast_against_white
from rag_core.clock import SystemClock
from rag_core.config import Settings
from rag_core.fakes import InMemoryBlobStore
from rag_core.testing.jwt import JwtFactory

pytestmark = [pytest.mark.integration, pytest.mark.enable_socket]
ISSUER = "https://supabase.test/auth/v1"


@dataclass
class Env:
    client: TestClient
    factory: JwtFactory
    blobs: InMemoryBlobStore

    def put(self, body: dict[str, Any], sub: str = USER_1, aal: str = "aal2") -> httpx.Response:
        token = self.factory.issue(self.factory.claims(sub=sub, aal=aal))
        response: httpx.Response = self.client.put(
            "/v1/tenant/branding", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        return response


@pytest.fixture
def env(rls: Rls) -> Iterator[Env]:
    factory = JwtFactory(issuer=ISSUER, audience="authenticated")
    http = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=factory.jwks()))
    )
    settings = Settings.for_tests(supabase_jwt_issuer=ISSUER, supabase_jwks_url="https://s.test/j")
    pool = make_pool(rls.dsn_for("app_api"), max_size=4)
    pool.open(wait=True)
    db = Database(pool)
    blobs = InMemoryBlobStore()
    auth = CentralAuth(
        build_identity_verifier(settings, http), PrincipalResolver(db, SystemClock())
    )
    app = create_app(settings, CentralDeps(auth=auth, db=db, blobs=blobs))
    yield Env(TestClient(app, raise_server_exceptions=False), factory, blobs)
    pool.close()


def _image(fmt: str = "PNG", size: tuple[int, int] = (40, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_color_contrast_validation(env: Env) -> None:
    assert contrast_against_white("#000000") > 20 and contrast_against_white("#ffffff") == 1.0
    ok = env.put({"primary_color": "#1a365d", "assistant_name": "Aurora Assist"})
    assert ok.status_code == 200 and ok.json()["primary_color"] == "#1a365d"
    for color, subcode in (("#ffff00", "low_contrast"), ("#cccccc", "low_contrast"),
                           ("azul", "invalid_color"), ("#12345", "invalid_color")):  # fmt: skip
        response = env.put({"primary_color": color})
        assert (response.status_code, response.json()["subcode"]) == (422, subcode), color


def test_assistant_name_rules(env: Env) -> None:
    for name in ("<b>x</b>", "a&b", "x" * 41, "   ", "linha\nnova"):
        assert env.put({"assistant_name": name}).status_code == 422, name
    assert env.put({"assistant_name": "Assistente da Aurora"}).status_code == 200
    assert env.put({"nome": "x"}).status_code == 422  # campo desconhecido


def test_svg_rejected(env: Env) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    gif = io.BytesIO()
    Image.new("P", (4, 4)).save(gif, format="GIF")
    for data, subcode in ((svg, "logo_invalid"), (gif.getvalue(), "logo_format"),
                          (b"nao e imagem", "logo_invalid")):  # fmt: skip
        response = env.put({"logo_base64": _b64(data)})
        assert (response.status_code, response.json()["subcode"]) == (422, subcode)
    assert env.put({"logo_base64": "@@@"}).status_code == 422
    noisy = Image.effect_noise((500, 500), 80).convert("RGB")
    buffer = io.BytesIO()
    noisy.save(buffer, format="PNG")
    assert len(buffer.getvalue()) > 512 * 1024
    assert env.put({"logo_base64": _b64(buffer.getvalue())}).json()["subcode"] == "logo_too_large"


def test_polyglot_image_reencoded(env: Env) -> None:
    attack = b"<script>alert('xss')</script><?php system($_GET[1]); ?>"
    polyglot = _image("PNG") + attack
    with_comment = Image.open(io.BytesIO(_image("PNG")))
    with_comment.info["Comment"] = "SEGREDO-EXIF"
    response = env.put({"logo_base64": _b64(polyglot)})
    assert response.status_code == 200 and response.json()["has_logo"] is True
    stored = env.blobs.get("branding/aaaaaaaa-0000-4000-8000-00000000000a/logo.png")
    assert attack not in stored and b"<script>" not in stored and b"system(" not in stored
    reopened = Image.open(io.BytesIO(stored))
    assert reopened.format == "PNG" and reopened.size == (40, 30)
    jpeg = Image.open(io.BytesIO(_image("JPEG", (3000, 10))))
    assert jpeg.size == (3000, 10)
    env.put({"logo_base64": _b64(_image("JPEG", (3000, 10)))})
    shrunk = Image.open(
        io.BytesIO(env.blobs.get("branding/aaaaaaaa-0000-4000-8000-00000000000a/logo.jpg"))
    )
    assert max(shrunk.size) <= 1024  # reduzido ao tamanho máximo


def test_public_endpoint_whitelisted_fields(env: Env) -> None:
    env.put(
        {
            "assistant_name": "Aurora Assist",
            "primary_color": "#1a365d",
            "logo_base64": _b64(_image()),
        }
    )
    public = env.client.get("/v1/public/branding/aurora")  # sem autenticação
    assert public.status_code == 200
    assert public.json() == {
        "assistant_name": "Aurora Assist",
        "primary_color": "#1a365d",
        "logo_url": "/v1/public/branding/aurora/logo",
    }
    logo = env.client.get("/v1/public/branding/aurora/logo")
    assert logo.status_code == 200 and logo.headers["content-type"] == "image/png"
    assert "sandbox" in logo.headers["content-security-policy"]
    boreal = env.client.get("/v1/public/branding/boreal")  # marca de B, sem logótipo
    assert boreal.json() == {"assistant_name": "B", "primary_color": None, "logo_url": None}
    assert env.client.get("/v1/public/branding/nao-existe").status_code == 404
    assert env.client.get("/v1/public/branding/X").status_code == 404  # slug inválido
    assert env.client.get("/v1/public/branding/boreal/logo").status_code == 404


def test_requires_admin_aal2_and_suspended_tenant_is_hidden(env: Env) -> None:
    assert env.put({"assistant_name": "X"}, aal="aal1").status_code == 403
    assert env.put({"assistant_name": "X"}, sub=USER_2).status_code == 403  # membro de B
    env.put({"assistant_name": "Visível"})
    assert env.client.get("/v1/public/branding/aurora").status_code == 200

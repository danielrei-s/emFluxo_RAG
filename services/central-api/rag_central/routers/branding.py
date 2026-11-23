"""Marca por tenant (F9-T03; INV-08): nome, cor e logótipo, validados e re-codificados.

O logótipo nunca é guardado como chegou: é decodificado e escrito de novo com Pillow, o que
remove metadados e quaisquer bytes anexados (polyglots). SVG é recusado.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field
from rag_core.errors import NotFound, UpstreamError, ValidationFailed
from rag_core.policy import Action
from rag_core.types import Principal

from rag_central.audit import AuditLogger
from rag_central.auth import require_action
from rag_central.db import Database

router = APIRouter(tags=["branding"])
ManageSettings = Annotated[Principal, Depends(require_action(Action.TENANT_MANAGE_SETTINGS))]
MAX_LOGO_BYTES = 512 * 1024
MAX_SIDE = 1024
MIN_CONTRAST = 4.5
FORMATS = {
    "PNG": ("png", "image/png"),
    "JPEG": ("jpg", "image/jpeg"),
    "WEBP": ("webp", "image/webp"),
}
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_SLUG = re.compile(r"^[a-z0-9-]{3,40}$")
Image.MAX_IMAGE_PIXELS = 20_000_000  # defesa contra bombas de descompressão


def contrast_against_white(color: str) -> float:
    """Razão de contraste WCAG entre ``#RRGGBB`` e branco."""
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return float(1.05 / (luminance + 0.05))


def reencode_logo(data: bytes) -> tuple[bytes, str, str]:
    """Devolve ``(bytes novos, extensão, content-type)`` ou ``ValidationFailed``."""
    if len(data) > MAX_LOGO_BYTES:
        raise ValidationFailed(subcode="logo_too_large")
    try:
        image: Image.Image = Image.open(io.BytesIO(data))
        fmt = image.format or ""
        if fmt not in FORMATS:
            raise ValidationFailed(subcode="logo_format")  # SVG, GIF, etc.
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationFailed(subcode="logo_invalid") from exc
    image = image.convert("RGBA" if fmt != "JPEG" else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    clean = Image.new(image.mode, image.size)
    clean.putdata(list(image.getdata()))  # só píxeis: sem metadados nem bytes anexados
    buffer = io.BytesIO()
    clean.save(buffer, format=fmt)
    extension, content_type = FORMATS[fmt]
    return buffer.getvalue(), extension, content_type


class BrandingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant_name: str | None = Field(default=None, max_length=40)
    primary_color: str | None = None
    logo_base64: str | None = Field(default=None, max_length=1_400_000)


def _db(request: Request) -> Database:
    db: Database | None = request.app.state.deps.db
    if db is None:
        raise UpstreamError("database_not_configured")
    return db


@router.put("/tenant/branding")
def put_branding(
    body: BrandingRequest, request: Request, principal: ManageSettings
) -> dict[str, Any]:
    name = body.assistant_name
    if name is not None and (not name.strip() or re.search(r"[<>&\x00-\x1f]", name)):
        raise ValidationFailed(subcode="invalid_assistant_name")  # sem HTML nem controlo
    if body.primary_color is not None:
        if not _COLOR.fullmatch(body.primary_color):
            raise ValidationFailed(subcode="invalid_color")
        if contrast_against_white(body.primary_color) < MIN_CONTRAST:
            raise ValidationFailed(subcode="low_contrast")
    logo: tuple[bytes, str, str] | None = None
    if body.logo_base64 is not None:
        try:
            raw = base64.b64decode(body.logo_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationFailed(subcode="logo_invalid") from exc
        logo = reencode_logo(raw)
    key: str | None = None
    if logo is not None:
        blobs = request.app.state.deps.blobs
        if blobs is None:
            raise UpstreamError("blob_store_not_configured")
        key = f"branding/{principal.tenant_id}/logo.{logo[1]}"
        blobs.put(key, logo[0])
    with _db(request).tenant_tx(principal.tenant_id, principal.user_id) as cur:
        cur.execute(
            "insert into app.tenant_branding (tenant_id, assistant_name, primary_color, "
            "logo_blob_key) values (%s, %s, %s, %s) on conflict (tenant_id) do update set "
            "assistant_name = coalesce(excluded.assistant_name, "
            "app.tenant_branding.assistant_name), "
            "primary_color = coalesce(excluded.primary_color, "
            "app.tenant_branding.primary_color), "
            "logo_blob_key = coalesce(excluded.logo_blob_key, "
            "app.tenant_branding.logo_blob_key) "
            "returning assistant_name, primary_color, logo_blob_key",
            (principal.tenant_id, name, body.primary_color, key),
        )
        row = cur.fetchone()
        AuditLogger(request.app.state.deps.clock).record(
            cur,
            tenant_id=principal.tenant_id,
            actor_type="user",
            actor_id=principal.user_id,
            action="tenant.branding_update",
            resource_type="tenant",
            resource_id=principal.tenant_id,
        )
    assert row is not None  # noqa: S101 - upsert ... returning devolve sempre uma linha
    return {
        "assistant_name": row["assistant_name"],
        "primary_color": row["primary_color"],
        "has_logo": row["logo_blob_key"] is not None,
    }


def _public(request: Request, slug: str) -> dict[str, Any]:
    if not _SLUG.fullmatch(slug):
        raise NotFound()
    with _db(request).public_tx() as cur:
        cur.execute("select * from app.public_branding(%s)", (slug,))
        row = cur.fetchone()
    if row is None:
        raise NotFound()
    return row


@router.get("/public/branding/{slug}")
def public_branding(slug: str, request: Request) -> dict[str, Any]:
    """Só campos da lista branca, para o ecrã de login (sem autenticação)."""
    row = _public(request, slug)
    return {
        "assistant_name": row["assistant_name"],
        "primary_color": row["primary_color"],
        "logo_url": f"/v1/public/branding/{slug}/logo" if row["logo_blob_key"] else None,
    }


@router.get("/public/branding/{slug}/logo", response_model=None)
def public_logo(slug: str, request: Request) -> Response:
    row = _public(request, slug)
    key = row["logo_blob_key"]
    blobs = request.app.state.deps.blobs
    if not key or blobs is None:
        raise NotFound()
    extension = key.rsplit(".", 1)[-1]
    content_type = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[extension]
    return Response(
        blobs.get(key),
        media_type=content_type,
        headers={
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "public, max-age=300",
        },
    )

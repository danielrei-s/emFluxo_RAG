"""Parser de email ``.eml`` do perfil lite (F3-T07): cabeçalhos, corpo e anexos em bruto."""

from __future__ import annotations

from email import policy
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import PurePath

from rag_core.errors import CorruptedFile, UnsupportedType
from rag_core.ingestion.sanitize import clean_text
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import PARSER_VERSION, split_paragraphs
from rag_core.parsing.html import HtmlParser
from rag_core.types import Block, DetectedType, RawAttachment, StructuredDocument

MIN_INLINE_IMAGE_BYTES = 10 * 1024
_HEADERS = (("Subject", "Assunto"), ("From", "De"), ("To", "Para"), ("Date", "Data"))


def _header_text(msg: Message, name: str) -> str:
    try:
        value = str(msg.get(name, "") or "")
    except Exception:  # cabeçalho com codificação inválida
        return ""
    return " ".join(clean_text(value).text.split())


def _content(part: Message) -> str:
    try:
        content = part.get_content()  # type: ignore[attr-defined]
        return str(content)
    except Exception:  # charset desconhecido ou conteúdo corrompido
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""


def _domain(msg: Message) -> str | None:
    address = parseaddr(_header_text(msg, "From"))[1]
    _, _, domain = address.rpartition("@")
    return domain.lower() or None if "@" in address else None


def _is_small_inline_image(part: Message, data: bytes) -> bool:
    inline = part.get_content_disposition() == "inline" or part.get("Content-ID") is not None
    return part.get_content_maintype() == "image" and inline and len(data) < MIN_INLINE_IMAGE_BYTES


def _attachments(msg: EmailMessage) -> list[RawAttachment]:
    found: list[RawAttachment] = []
    for index, part in enumerate(msg.iter_attachments(), start=1):
        if part.get_content_type() == "message/rfc822":
            inner = part.get_payload(0)
            data = inner.as_bytes() if isinstance(inner, Message) else b""
            default = "mensagem.eml"
        else:
            payload = part.get_payload(decode=True)
            data = payload if isinstance(payload, bytes) else b""
            default = f"anexo-{index}"
        if _is_small_inline_image(part, data):
            continue
        raw_name = part.get_filename() or default
        name = clean_text(PurePath(raw_name.replace("\\", "/")).name).text or default
        found.append(RawAttachment(filename=name, data=data))
    return found


class EmlParser:
    """EML com a biblioteca standard ``email``; os anexos seguem para ingestão recursiva."""

    name = "lite-eml"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.EML})

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"eml_parser:{detected.value}")  # .msg: HR-04
        try:
            msg = BytesParser(policy=policy.default).parsebytes(data)
            lines = [f"{label}: {v}" for key, label in _HEADERS if (v := _header_text(msg, key))]
            blocks = [Block(kind="email_header", text="\n".join(lines))] if lines else []
            warnings: tuple[str, ...] = ()
            body = msg.get_body(preferencelist=("plain", "html"))
            if body is not None and body.get_content_type() == "text/html":
                html = HtmlParser().parse(
                    _content(body).encode("utf-8"),
                    filename=filename,
                    detected=DetectedType.HTML,
                    limits=limits,
                )
                blocks.extend(html.blocks)
                warnings = html.warnings
            elif body is not None:
                text = clean_text(_content(body)).text
                blocks.extend(Block(kind="paragraph", text=p) for p in split_paragraphs(text))
            attachments = _attachments(msg)
            subject = _header_text(msg, "Subject")
            domain = _domain(msg)
        except Exception as exc:  # a biblioteca email é tolerante, mas não infalível
            raise CorruptedFile("eml_unreadable") from exc
        return StructuredDocument(
            title=subject or None,
            detected_type=detected,
            blocks=tuple(blocks),
            parser_name=self.name,
            parser_version=self.version,
            meta={"email_from_domain": domain} if domain else {},
            warnings=warnings,
            attachments=tuple(attachments),
        )

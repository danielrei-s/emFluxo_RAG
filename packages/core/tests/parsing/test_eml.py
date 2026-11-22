"""Testes de F3-T07: parser de email (EML)."""

from __future__ import annotations

import email
from email import policy
from email.message import EmailMessage

import pytest
from rag_core.errors import UnsupportedType
from rag_core.interfaces import ParseLimits, Parser
from rag_core.parsing.eml import EmlParser
from rag_core.testing import corpus
from rag_core.types import DetectedType, StructuredDocument

PARSER = EmlParser()


def _parse(data: bytes, detected: DetectedType = DetectedType.EML) -> StructuredDocument:
    return PARSER.parse(data, filename="m.eml", detected=detected, limits=ParseLimits())


def _msg(body: str = "corpo", *, subtype: str = "plain") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "Ana <Ana@Exemplo.PT>"
    msg["To"] = "rui@exemplo.pt"
    msg["Subject"] = "Assunto de teste"
    msg["Date"] = "Mon, 05 Jan 2026 10:00:00 +0000"
    msg.set_content(body, subtype=subtype)
    return msg


def test_eml_headers_body_and_fact() -> None:
    doc = _parse(corpus.read_bytes("A06"))
    assert isinstance(PARSER, Parser)
    header = doc.blocks[0]
    assert header.kind == "email_header"
    assert header.text == (
        "Assunto: Atualização de preços\n"
        "De: encomendas@papelaria-norte.example\n"
        "Para: compras@aurora.example\n"
        "Data: Mon, 05 Jan 2026 10:00:00 +0000"
    )
    body = " ".join(b.text for b in doc.blocks[1:])
    assert "aumento de 3% a partir de 1 de março de 2026" in body
    assert all(b.kind == "paragraph" for b in doc.blocks[1:])
    assert doc.meta == {"email_from_domain": "papelaria-norte.example"}
    assert doc.title == "Atualização de preços"


def test_eml_attachment_extracted_bytes_equal() -> None:
    raw = corpus.read_bytes("A06")
    doc = _parse(raw)
    (attachment,) = doc.attachments
    assert attachment.filename == "condicoes.pdf"
    original = email.message_from_bytes(raw, policy=policy.default)
    expected = next(original.iter_attachments()).get_payload(decode=True)
    assert attachment.data == expected
    assert attachment.data.startswith(b"%PDF-")


def test_html_only_email() -> None:
    msg = _msg("<p>Olá <b>equipa</b></p><p hidden>OCULTO</p><p>fim</p>", subtype="html")
    doc = _parse(msg.as_bytes())
    texts = [b.text for b in doc.blocks if b.kind == "paragraph"]
    assert texts == ["Olá equipa", "fim"]
    assert "hidden_text_removed" in doc.warnings
    assert doc.meta["email_from_domain"] == "exemplo.pt"


def test_plain_text_is_preferred_over_html() -> None:
    msg = _msg("versão texto")
    msg.add_alternative("<p>versão html</p>", subtype="html")
    texts = [b.text for b in _parse(msg.as_bytes()).blocks if b.kind == "paragraph"]
    assert texts == ["versão texto"]


def test_invisible_characters_are_cleaned_in_headers_and_body() -> None:
    msg = _msg("ola​ mundo\n\n\n\nfim")
    del msg["Subject"]
    msg["Subject"] = "Ass‮unto"
    doc = _parse(msg.as_bytes())
    assert "Assunto: Assunto" in doc.blocks[0].text
    assert [b.text for b in doc.blocks[1:]] == ["ola mundo", "fim"]


def test_small_inline_images_ignored_but_other_attachments_kept() -> None:
    msg = _msg()
    msg.add_attachment(
        b"\x89PNG" + bytes(100), maintype="image", subtype="png", disposition="inline",
        cid="<logo@x>",
    )  # fmt: skip
    msg.add_attachment(
        b"\x89PNG" + bytes(20_000), maintype="image", subtype="png", disposition="inline",
        cid="<foto@x>", filename="foto.png",
    )  # fmt: skip
    msg.add_attachment(b"dados", maintype="application", subtype="octet-stream")
    nested = EmailMessage()
    nested["Subject"] = "interno"
    nested.set_content("texto interno")
    msg.add_attachment(nested)
    msg.add_attachment(
        b"x", maintype="application", subtype="pdf", filename="../../etc/relatório.pdf"
    )
    names = [a.filename for a in _parse(msg.as_bytes()).attachments]
    assert names == ["foto.png", "anexo-3", "mensagem.eml", "relatório.pdf"]
    nested_attachment = _parse(msg.as_bytes()).attachments[2]
    assert b"texto interno" in nested_attachment.data


def test_malformed_email_does_not_crash() -> None:
    for raw in (
        b"",
        b"\x00\xff\xfe lixo sem cabecalhos",
        b"Subject: so cabecalho",
        b"From: <>\r\nContent-Type: multipart/mixed; boundary=xx\r\n\r\n--xx\r\nbroken",
        b"From: a@b\r\nContent-Type: text/plain; charset=nao-existe\r\n\r\ncaf\xe9 texto",
        b"From: sem-arroba\r\n\r\ncorpo",
    ):
        doc = _parse(raw)
        assert isinstance(doc, StructuredDocument)
    assert "email_from_domain" not in _parse(b"From: sem-arroba\r\n\r\ncorpo").meta
    assert _parse(b"").blocks == ()


def test_msg_unsupported_in_lite() -> None:
    with pytest.raises(UnsupportedType):
        _parse(b"\xd0\xcf\x11\xe0", DetectedType.MSG)


def test_unexpected_library_errors_become_corrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    from email.parser import BytesParser

    from rag_core.errors import CorruptedFile

    def boom(self: BytesParser, data: bytes) -> None:
        raise ValueError("falha")

    monkeypatch.setattr(BytesParser, "parsebytes", boom)
    with pytest.raises(CorruptedFile):
        _parse(b"Subject: x\r\n\r\ny")


def test_header_with_undecodable_value_is_dropped() -> None:
    from rag_core.parsing.eml import _header_text

    class Broken:
        def get(self, name: str, default: object = None) -> object:
            raise ValueError("cabeçalho inválido")

    assert _header_text(Broken(), "Subject") == ""  # type: ignore[arg-type]

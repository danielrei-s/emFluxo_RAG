"""Testes de F3-T08: OCR opcional (motor injetável; testes com motor real: marcador ocr)."""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from rag_core.errors import CorruptedFile, UnsupportedType, ValidationFailed
from rag_core.interfaces import ParseLimits
from rag_core.parsing import ocr as ocr_module
from rag_core.parsing.image import ImageParser
from rag_core.parsing.ocr import (
    DEFAULT_MODELS_FILE,
    ModelFile,
    RapidOcrEngine,
    load_model_files,
    verify_model_files,
)
from rag_core.parsing.pdf_lite import PdfParser
from rag_core.testing import corpus
from rag_core.types import DetectedType
from reportlab.pdfgen import canvas

OCR_ON = ParseLimits(ocr=True)


class FakeOcr:
    """Motor de teste: devolve linhas fixas e guarda as imagens recebidas."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.images: list[bytes] = []

    def recognize(self, image_bytes: bytes) -> list[str]:
        self.images.append(image_bytes)
        return list(self.lines)


def _png(size: tuple[int, int] = (40, 20), fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, format=fmt)
    return buf.getvalue()


def _tiff(frames: int) -> bytes:
    images = [Image.new("RGB", (30, 30), color) for color in ("red", "blue", "green")[:frames]]
    buf = io.BytesIO()
    images[0].save(buf, format="TIFF", save_all=True, append_images=images[1:])
    return buf.getvalue()


def _parse_image(data: bytes, detected: DetectedType, engine: FakeOcr | None, limits: ParseLimits):  # type: ignore[no-untyped-def]
    return ImageParser(engine).parse(data, filename="f", detected=detected, limits=limits)


# ------------------------------------------------------------------- PDF digitalizado


def test_scanned_pdf_uses_ocr_text_at_200_dpi() -> None:
    engine = FakeOcr(["LimpaTudo", "450 € mensais"])
    doc = PdfParser(engine).parse(
        corpus.read_bytes("A10"), filename="a10.pdf", detected=DetectedType.PDF, limits=OCR_ON
    )
    (block,) = doc.blocks
    assert (block.text, block.page, block.flags) == (
        "LimpaTudo 450 € mensais",
        1,
        frozenset({"ocr"}),
    )
    (rendered,) = engine.images
    with Image.open(io.BytesIO(rendered)) as image:
        # a página do corpus é A4/Letter em pontos: 200 DPI = 200/72 pixéis por ponto
        assert image.width in range(1650, 1710)
        assert image.height in range(2190, 2350)


def test_pdf_without_ocr_enabled_or_engine_keeps_needs_ocr_flag() -> None:
    data = corpus.read_bytes("A10")
    for parser, limits in [(PdfParser(FakeOcr(["x"])), ParseLimits()), (PdfParser(), OCR_ON)]:
        doc = parser.parse(data, filename="f", detected=DetectedType.PDF, limits=limits)
        assert doc.blocks[0].flags == {"needs_ocr"}
        assert doc.blocks[0].text == ""


def test_pdf_ocr_with_no_result_keeps_flag_and_only_blank_pages_are_processed() -> None:
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, invariant=1)
    pdf.drawString(50, 780, "uma página com texto de sobra para passar")
    pdf.showPage()
    pdf.showPage()  # página vazia
    pdf.save()

    empty = FakeOcr([])
    doc = PdfParser(empty).parse(
        buf.getvalue(), filename="f", detected=DetectedType.PDF, limits=OCR_ON
    )
    assert len(empty.images) == 1
    assert [(b.page, b.flags) for b in doc.blocks] == [(1, frozenset()), (2, {"needs_ocr"})]

    doc = PdfParser(FakeOcr(["texto OCR"])).parse(
        buf.getvalue(), filename="f", detected=DetectedType.PDF, limits=OCR_ON
    )
    assert [(b.page, b.text) for b in doc.blocks][1] == (2, "texto OCR")


def test_pdf_with_text_never_calls_the_engine() -> None:
    engine = FakeOcr(["x"])
    PdfParser(engine).parse(
        corpus.read_bytes("A01"), filename="f", detected=DetectedType.PDF, limits=OCR_ON
    )
    assert engine.images == []


# ----------------------------------------------------------------------------- imagens


def test_image_parser_png() -> None:
    engine = FakeOcr(["Fatura", "123"])
    doc = _parse_image(_png(), DetectedType.PNG, engine, OCR_ON)
    (block,) = doc.blocks
    assert (block.text, block.page, block.flags) == ("Fatura 123", None, {"ocr"})
    assert doc.page_count is None
    assert engine.images[0].startswith(b"\x89PNG")


def test_image_parser_jpeg_and_multi_page_tiff() -> None:
    assert (
        _parse_image(_png(fmt="JPEG"), DetectedType.JPEG, FakeOcr(["a"]), OCR_ON).blocks[0].text
        == "a"
    )
    engine = FakeOcr(["pág"])
    doc = _parse_image(_tiff(3), DetectedType.TIFF, engine, OCR_ON)
    assert [(b.page, b.text) for b in doc.blocks] == [(1, "pág"), (2, "pág"), (3, "pág")]
    assert doc.page_count == 3
    limited = _parse_image(
        _tiff(3), DetectedType.TIFF, FakeOcr(["x"]), ParseLimits(ocr=True, max_pages=2)
    )
    assert limited.page_count == 2


def test_image_without_ocr_is_flagged_needs_ocr() -> None:
    for engine, limits in [(None, OCR_ON), (FakeOcr(["x"]), ParseLimits())]:
        doc = _parse_image(_png(), DetectedType.PNG, engine, limits)
        assert [(b.text, b.flags) for b in doc.blocks] == [("", {"needs_ocr"})]
    assert _parse_image(_png(), DetectedType.PNG, FakeOcr([]), OCR_ON).blocks[0].flags == {
        "needs_ocr"
    }


def test_image_errors() -> None:
    with pytest.raises(CorruptedFile):
        _parse_image(b"\x89PNG\r\n\x1a\n lixo", DetectedType.PNG, None, OCR_ON)
    with pytest.raises(UnsupportedType):
        _parse_image(b"x", DetectedType.PDF, None, OCR_ON)


def test_image_bomb_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rag_core.parsing.image.MAX_PIXELS", 100)
    with pytest.raises(ValidationFailed) as exc:
        _parse_image(_png((50, 50)), DetectedType.PNG, None, OCR_ON)
    assert exc.value.subcode == "image_too_large"


def test_pillow_decompression_bomb_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ValidationFailed) as exc:
        _parse_image(_png((50, 50)), DetectedType.PNG, None, OCR_ON)
    assert exc.value.subcode == "image_too_large"


# ------------------------------------------------------------------- modelos (INV-22)


def _models_yaml(tmp_path: Path, sha: str, revision: str = "1.0") -> Path:
    path = tmp_path / "models.yaml"
    files = "".join(
        f"      - {{name: {role}.onnx, role: {role}, sha256: {sha}}}\n"
        for role in ("det", "rec", "cls")
    )
    path.write_text(
        "ocr_models:\n  rapidocr:\n"
        f'    package: x\n    revision: "{revision}"\n    license: Apache-2.0\n    files:\n{files}',
        encoding="utf-8",
    )
    return path


def test_inv22_ocr_model_hash_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    for role in ("det", "rec", "cls"):
        (tmp_path / f"{role}.onnx").write_bytes(b"modelo")
    good = hashlib.sha256(b"modelo").hexdigest()

    def must_not_load() -> None:
        raise AssertionError("o modelo foi carregado antes da verificação")

    monkeypatch.setattr(ocr_module, "_import_rapidocr", must_not_load)
    with pytest.raises(ValidationFailed) as exc:
        RapidOcrEngine(_models_yaml(tmp_path, "0" * 64), model_dir=tmp_path)
    assert exc.value.subcode == "model_hash_mismatch"

    files = load_model_files(_models_yaml(tmp_path, good))
    assert set(verify_model_files(tmp_path, files)) == {"det", "rec", "cls"}

    (tmp_path / "rec.onnx").unlink()
    with pytest.raises(ValidationFailed) as exc2:
        verify_model_files(tmp_path, files)
    assert exc2.value.subcode == "model_file_missing"

    with pytest.raises(ValidationFailed) as exc3:
        load_model_files(_models_yaml(tmp_path, good, revision=""))
    assert exc3.value.subcode == "model_revision_missing"


def test_models_yaml_pins_revision_and_hashes() -> None:
    files = load_model_files(DEFAULT_MODELS_FILE)
    assert {f.role for f in files} == {"det", "rec", "cls"}
    assert all(len(f.sha256) == 64 for f in files)
    assert ModelFile("a", "det", "b").role == "det"


def test_missing_ocr_package_raises_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    with pytest.raises(UnsupportedType):
        RapidOcrEngine()


# -------------------------------------------------------------- motor real (marcador ocr)


@pytest.mark.ocr
def test_installed_models_match_models_yaml() -> None:
    files = load_model_files(DEFAULT_MODELS_FILE)
    assert verify_model_files(ocr_module._package_dir(), files)


@pytest.mark.ocr
def test_scanned_contract_ocr_finds_keywords() -> None:
    engine = RapidOcrEngine()
    doc = PdfParser(engine).parse(
        corpus.read_bytes("A10"), filename="a10.pdf", detected=DetectedType.PDF, limits=OCR_ON
    )
    text = " ".join(b.text for b in doc.blocks).replace(" ", "").lower()
    assert "limpatudo" in text
    assert "450" in text
    assert doc.blocks[0].flags == {"ocr"}


@pytest.mark.ocr
def test_image_parser_png_real_engine() -> None:
    image = Image.new("RGB", (600, 120), "white")
    ImageDraw.Draw(image).text(
        (20, 30), "Fatura 12345", fill="black", font=ImageFont.load_default(size=40)
    )
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    doc = _parse_image(buf.getvalue(), DetectedType.PNG, RapidOcrEngine(), OCR_ON)  # type: ignore[arg-type]
    assert "12345" in doc.blocks[0].text.replace(" ", "")
    assert struct.calcsize("I") == 4


def test_rapid_engine_wiring_with_a_fake_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    from types import SimpleNamespace

    pkg = tmp_path / "rapidocr_onnxruntime"
    pkg.mkdir()
    for role in ("det", "rec", "cls"):
        (pkg / f"{role}.onnx").write_bytes(b"modelo")
    models = _models_yaml(tmp_path, hashlib.sha256(b"modelo").hexdigest())
    seen: dict[str, str] = {}

    class FakeRapid:
        def __init__(self, **paths: str) -> None:
            seen.update(paths)

        def __call__(self, image: bytes) -> tuple[list[list[object]], float]:
            return [[[], "linha um", 0.9], [[], "  ", 0.9]], 0.0

    monkeypatch.setattr(ocr_module, "_import_rapidocr", lambda: FakeRapid)
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: SimpleNamespace(origin=str(pkg / "__init__.py")),
    )
    engine = RapidOcrEngine(models)  # sem model_dir: usa a pasta do pacote
    assert engine.recognize(b"img") == ["linha um"]
    assert set(seen) == {"det_model_path", "rec_model_path", "cls_model_path"}

    class Empty(FakeRapid):
        def __call__(self, image: bytes) -> tuple[None, float]:  # type: ignore[override]
            return None, 0.0

    monkeypatch.setattr(ocr_module, "_import_rapidocr", lambda: Empty)
    assert RapidOcrEngine(models).recognize(b"img") == []

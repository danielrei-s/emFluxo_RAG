"""OCR opcional (F3-T08, extra ``ocr``): protocolo, verificação de modelos e motor RapidOCR.

Os modelos só são carregados depois de o sha256 de cada ficheiro bater com o ``models.yaml``
(INV-22). O import do RapidOCR é adiado: sem o extra instalado, o resto do core funciona.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from rag_core.errors import UnsupportedType, ValidationFailed
from rag_core.ids import sha256_file

DEFAULT_MODELS_FILE = Path(__file__).resolve().parents[4] / "models.yaml"
OCR_SECTION = "rapidocr"


class OcrEngine(Protocol):
    """Reconhece o texto de uma imagem (PNG/JPEG/…); devolve uma linha de texto por item."""

    def recognize(self, image_bytes: bytes) -> list[str]: ...


@dataclass(frozen=True)
class ModelFile:
    name: str  # relativo à pasta do pacote que embute os modelos
    role: str  # det | rec | cls
    sha256: str


def load_model_files(models_file: Path = DEFAULT_MODELS_FILE) -> list[ModelFile]:
    """Lê do ``models.yaml`` os ficheiros do OCR (com a revisão e o sha256 fixados)."""
    data: dict[str, Any] = yaml.safe_load(models_file.read_text(encoding="utf-8"))
    section = data["ocr_models"][OCR_SECTION]
    if not section.get("revision"):
        raise ValidationFailed(subcode="model_revision_missing")
    return [ModelFile(f["name"], f["role"], f["sha256"]) for f in section["files"]]


def verify_model_files(base_dir: Path, files: list[ModelFile]) -> dict[str, Path]:
    """Confirma o sha256 de cada ficheiro; devolve ``role -> caminho``. Falha antes de carregar."""
    paths: dict[str, Path] = {}
    for model in files:
        path = base_dir / model.name
        if not path.is_file():
            raise ValidationFailed(subcode="model_file_missing")
        if sha256_file(path) != model.sha256:
            raise ValidationFailed(subcode="model_hash_mismatch")
        paths[model.role] = path
    return paths


def _package_dir() -> Path:
    spec = importlib.util.find_spec("rapidocr_onnxruntime")
    if spec is None or spec.origin is None:
        raise UnsupportedType("ocr_not_installed")
    return Path(spec.origin).parent


def _import_rapidocr() -> Any:  # pragma: no cover - exige o extra ocr
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR


class RapidOcrEngine:
    """OCR com RapidOCR (ONNX). Verifica os hashes dos modelos antes de os carregar."""

    def __init__(
        self, models_file: Path = DEFAULT_MODELS_FILE, *, model_dir: Path | None = None
    ) -> None:
        files = load_model_files(models_file)
        paths = verify_model_files(model_dir or _package_dir(), files)
        rapid_ocr = _import_rapidocr()
        self._engine = rapid_ocr(
            det_model_path=str(paths["det"]),
            rec_model_path=str(paths["rec"]),
            cls_model_path=str(paths["cls"]),
        )

    def recognize(self, image_bytes: bytes) -> list[str]:
        result, _ = self._engine(image_bytes)
        return [str(item[1]) for item in result or [] if str(item[1]).strip()]

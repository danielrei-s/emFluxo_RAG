"""Parser de imagens (PNG, JPEG, TIFF) por OCR (F3-T08)."""

from __future__ import annotations

import io

from PIL import Image, ImageSequence, UnidentifiedImageError

from rag_core.errors import CorruptedFile, UnsupportedType, ValidationFailed
from rag_core.interfaces import ParseLimits
from rag_core.parsing.base import PARSER_VERSION
from rag_core.parsing.ocr import OcrEngine
from rag_core.types import Block, DetectedType, StructuredDocument

MAX_PIXELS = 50_000_000
OCR_FLAG = "ocr"
NEEDS_OCR_FLAG = "needs_ocr"


def _frames(data: bytes, max_frames: int) -> list[bytes]:
    """Cada fotograma como PNG (um TIFF pode ter várias páginas)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValidationFailed(subcode="image_too_large")
            frames = []
            for frame in ImageSequence.Iterator(image):
                buffer = io.BytesIO()
                frame.convert("RGB").save(buffer, format="PNG")
                frames.append(buffer.getvalue())
                if len(frames) >= max_frames:
                    break
            return frames
    except ValidationFailed:
        raise
    except Image.DecompressionBombError as exc:
        raise ValidationFailed(subcode="image_too_large") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise CorruptedFile("image_unreadable") from exc


class ImageParser:
    """Imagens: texto por OCR. Sem OCR ligado, devolve um bloco vazio com a flag ``needs_ocr``."""

    name = "lite-image"
    version = PARSER_VERSION
    supported = frozenset({DetectedType.PNG, DetectedType.JPEG, DetectedType.TIFF})

    def __init__(self, ocr_engine: OcrEngine | None = None) -> None:
        self._ocr = ocr_engine

    def parse(
        self, data: bytes, *, filename: str, detected: DetectedType, limits: ParseLimits
    ) -> StructuredDocument:
        if detected not in self.supported:
            raise UnsupportedType(f"image_parser:{detected.value}")
        frames = _frames(data, limits.max_pages)
        multi = len(frames) > 1
        blocks: list[Block] = []
        for number, png in enumerate(frames, start=1):
            page = number if multi else None
            lines = self._ocr.recognize(png) if limits.ocr and self._ocr is not None else []
            if lines:
                blocks.append(
                    Block(
                        kind="paragraph",
                        text=" ".join(lines),
                        page=page,
                        flags=frozenset({OCR_FLAG}),
                    )
                )
            else:
                blocks.append(
                    Block(kind="paragraph", text="", page=page, flags=frozenset({NEEDS_OCR_FLAG}))
                )
        return StructuredDocument(
            detected_type=detected,
            blocks=tuple(blocks),
            page_count=len(frames) if multi else None,
            parser_name=self.name,
            parser_version=self.version,
        )

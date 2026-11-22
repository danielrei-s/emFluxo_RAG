"""Ingestão: deteção de tipo, parsing, chunking (F3)."""

from rag_core.ingestion.detect import detect_type, sniff, validate_file

__all__ = ["detect_type", "sniff", "validate_file"]

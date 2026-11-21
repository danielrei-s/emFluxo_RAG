"""Hierarquia de erros do core (C6).

INV-03: a mensagem nunca contém conteúdo; só o código e, opcionalmente, um ID opaco.
"""

from __future__ import annotations


class RagError(Exception):
    """Erro base. ``str(erro)`` devolve só o código (e o ``detail_id``, se existir)."""

    code: str = "internal_error"

    def __init__(self, detail_id: str | None = None) -> None:
        self.detail_id = detail_id
        message = self.code if detail_id is None else f"{self.code}:{detail_id}"
        super().__init__(message)


class ValidationFailed(RagError):
    code = "validation_failed"

    def __init__(self, detail_id: str | None = None, subcode: str | None = None) -> None:
        super().__init__(detail_id)
        self.subcode = subcode


class UnsupportedType(RagError):
    code = "unsupported_type"


class FileTooLarge(RagError):
    code = "file_too_large"


class EncryptedFile(RagError):
    code = "encrypted_file"


class CorruptedFile(RagError):
    code = "corrupted_file"


class ParseTimeout(RagError):
    code = "parse_timeout"


class ParseMemoryLimit(RagError):
    code = "parse_memory_limit"


class SandboxViolation(RagError):
    code = "sandbox_violation"


class AccessDenied(RagError):
    code = "access_denied"


class NotFound(RagError):
    code = "not_found"


class QuotaExceeded(RagError):
    code = "quota_exceeded"


class RateLimited(RagError):
    code = "rate_limited"


class UpstreamError(RagError):
    code = "upstream_error"


class ConsentError(RagError):
    code = "consent_error"

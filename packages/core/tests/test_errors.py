"""Testes de ``rag_core.errors``."""

from __future__ import annotations

import inspect

import pytest
from rag_core import errors

CODES = {
    "ValidationFailed": "validation_failed",
    "UnsupportedType": "unsupported_type",
    "FileTooLarge": "file_too_large",
    "EncryptedFile": "encrypted_file",
    "CorruptedFile": "corrupted_file",
    "ParseTimeout": "parse_timeout",
    "ParseMemoryLimit": "parse_memory_limit",
    "SandboxViolation": "sandbox_violation",
    "AccessDenied": "access_denied",
    "NotFound": "not_found",
    "QuotaExceeded": "quota_exceeded",
    "RateLimited": "rate_limited",
    "UpstreamError": "upstream_error",
    "ConsentError": "consent_error",
}


def test_base_error_defaults_to_internal_error() -> None:
    assert errors.RagError().code == "internal_error"
    assert str(errors.RagError()) == "internal_error"


@pytest.mark.parametrize(("name", "code"), sorted(CODES.items()))
def test_each_error_has_its_code_and_subclasses_rag_error(name: str, code: str) -> None:
    cls = getattr(errors, name)
    assert issubclass(cls, errors.RagError)
    assert cls.code == code
    assert str(cls()) == code


def test_inv03_error_str_never_contains_free_text() -> None:
    params = inspect.signature(errors.RagError.__init__).parameters
    assert list(params) == ["self", "detail_id"]
    error = errors.NotFound("doc-123")
    assert str(error) == "not_found:doc-123"
    assert error.detail_id == "doc-123"
    assert error.args == ("not_found:doc-123",)


def test_validation_failed_accepts_subcode_without_leaking_it_into_str() -> None:
    error = errors.ValidationFailed(subcode="zip_bomb")
    assert error.subcode == "zip_bomb"
    assert str(error) == "validation_failed"
    assert errors.ValidationFailed().subcode is None


def test_inv03_validation_failed_subcode_is_the_only_extra_parameter() -> None:
    params = inspect.signature(errors.ValidationFailed.__init__).parameters
    assert list(params) == ["self", "detail_id", "subcode"]

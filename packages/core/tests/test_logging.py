"""Testes de ``rag_core.logging`` e ``rag_core.testing`` (INV-03)."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest
from rag_core.logging import (
    ALLOWED_KEYS,
    configure_logging,
    get_logger,
    reset_logging_handlers,
)
from rag_core.testing import DEFAULT_CANARIES, assert_no_canary

Events = list[dict[str, Any]]


def test_inv03_disallowed_keys_dropped(captured_logs: Events) -> None:
    get_logger("svc").info("question_asked", text="CANARIO-1", doc_id="d1")
    (event,) = captured_logs
    assert "text" not in event
    assert event["doc_id"] == "d1"
    assert event["dropped_keys"] == 1
    assert_no_canary(json.dumps(event))


def test_inv03_event_name_must_be_constant(captured_logs: Events) -> None:
    get_logger("svc").info("Pergunta: CANARIO-2")
    (event,) = captured_logs
    assert event["event"] == "invalid_event_name"
    assert_no_canary(json.dumps(event))


@pytest.mark.parametrize("name", ["doc.indexed", "stage_2_done", "a"])
def test_valid_event_names_are_kept(captured_logs: Events, name: str) -> None:
    get_logger("svc").info(name)
    assert captured_logs[0]["event"] == name


@pytest.mark.parametrize("name", ["Upper", "with space", "acção", "a-b", ""])
def test_invalid_event_names_are_replaced(captured_logs: Events, name: str) -> None:
    get_logger("svc").info(name)
    assert captured_logs[0]["event"] == "invalid_event_name"


def test_inv03_exception_message_not_logged(captured_logs: Events) -> None:
    secret_local = "CANARIO-local"  # noqa: F841, S105
    try:
        raise ValueError("CANARIO-3")
    except ValueError:
        get_logger("svc").exception("parse_failed")
    (event,) = captured_logs
    assert event["exc_type"] == "ValueError"
    assert "exc_frames" not in event
    assert "exc_info" not in event
    assert_no_canary(json.dumps(event))


def test_exception_frames_only_when_tracebacks_enabled() -> None:
    events: Events = []
    configure_logging("svc", "DEBUG", tracebacks=True, stream=io.StringIO(), sink=events.append)
    try:
        try:
            raise RuntimeError("CANARIO-4")
        except RuntimeError as exc:
            local_secret = "CANARIO-5"  # noqa: S105
            get_logger("svc").error("boom", exc_info=exc)
            assert local_secret
    finally:
        reset_logging_handlers()
    (event,) = events
    assert event["exc_type"] == "RuntimeError"
    assert event["exc_frames"][-1].startswith("test_logging.py:")
    assert_no_canary(json.dumps(event))


def test_allowed_keys_kept(captured_logs: Events) -> None:
    fields = {
        key: "x" for key in ALLOWED_KEYS - {"ts", "level", "event", "service", "dropped_keys"}
        - {"exc_type", "exc_frames"}
    }
    get_logger("svc").info("all_keys", **fields)
    (event,) = captured_logs
    assert {k: event[k] for k in fields} == fields
    assert "dropped_keys" not in event
    assert event["service"] == "svc"
    assert event["level"] == "info"
    assert event["ts"].endswith("Z")


def test_stdlib_logging_goes_through_filter(captured_logs: Events) -> None:
    logging.getLogger("uvicorn.error").warning("Pergunta: CANARIO-6 %s", "PWNED-7")
    (event,) = captured_logs
    assert event["event"] == "invalid_event_name"
    assert event["level"] == "warning"
    assert event["service"] == "test"
    assert set(event) <= ALLOWED_KEYS
    assert_no_canary(json.dumps(event))


def test_stdlib_exception_message_not_logged(captured_logs: Events) -> None:
    try:
        raise KeyError("HIDDEN-8")
    except KeyError:
        logging.getLogger("lib").exception("failed")
    (event,) = captured_logs
    assert event["exc_type"] == "KeyError"
    assert_no_canary(json.dumps(event))


def test_output_is_one_json_line_per_event() -> None:
    stream = io.StringIO()
    configure_logging("svc", "INFO", stream=stream)
    try:
        get_logger("svc").info("hello", count=3)
        logging.getLogger("lib").info("plain")
    finally:
        reset_logging_handlers()
    lines = stream.getvalue().strip().splitlines()
    parsed = [json.loads(line) for line in lines]
    assert [p["event"] for p in parsed] == ["hello", "plain"]
    assert parsed[0]["count"] == 3
    assert all(set(p) <= ALLOWED_KEYS for p in parsed)


def test_log_level_is_respected() -> None:
    stream = io.StringIO()
    configure_logging("svc", "WARNING", stream=stream)
    try:
        get_logger("svc").info("quiet")
        get_logger("svc").warning("loud")
    finally:
        reset_logging_handlers()
    assert [json.loads(line)["event"] for line in stream.getvalue().splitlines()] == ["loud"]


def test_configure_logging_twice_does_not_duplicate_output() -> None:
    stream = io.StringIO()
    configure_logging("svc", "INFO", stream=io.StringIO())
    configure_logging("svc", "INFO", stream=stream)
    try:
        get_logger("svc").info("once")
    finally:
        reset_logging_handlers()
    assert len(stream.getvalue().splitlines()) == 1


def test_assert_no_canary_detects_each_default_canary() -> None:
    for canary in DEFAULT_CANARIES:
        with pytest.raises(AssertionError) as info:
            assert_no_canary("ok", f"texto {canary}123")
        assert "#1" in str(info.value)
        assert f"{canary}123" not in str(info.value)


def test_assert_no_canary_accepts_clean_text_and_bytes() -> None:
    assert_no_canary("limpo", b"tambem limpo")
    with pytest.raises(AssertionError):
        assert_no_canary(b"xx CANARIO-9")
    with pytest.raises(AssertionError):
        assert_no_canary("MEU-TOKEN", canaries=("MEU-",))

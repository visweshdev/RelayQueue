import base64
import json
from datetime import UTC, datetime
from itertools import product
from uuid import uuid4

import pytest
from pydantic import ValidationError

from forgequeue.api.schemas import JobCreate
from forgequeue.config import Settings
from forgequeue.core.backoff import retry_delay
from forgequeue.core.cursors import decode_cursor, encode_cursor
from forgequeue.core.states import InvalidTransition, Status, transition

# Independent specification, not imported from the implementation transition table.
LEGAL = {
    (None, "queued"),
    (None, "scheduled"),
    ("scheduled", "queued"),
    ("queued", "running"),
    ("running", "succeeded"),
    ("running", "failed_retrying"),
    ("running", "dead"),
    ("failed_retrying", "queued"),
    ("dead", "queued"),
    ("queued", "cancelled"),
    ("scheduled", "cancelled"),
    ("failed_retrying", "cancelled"),
    ("running", "cancelled"),
}


@pytest.mark.parametrize("current,target", product([None, *Status], Status))
def test_all_state_pairs(current, target):
    if (current, target) in LEGAL:
        assert transition(current, target, manual=current == Status.DEAD) == target
    else:
        with pytest.raises(InvalidTransition):
            transition(current, target, manual=True)


def test_dead_requires_explicit_manual_retry():
    with pytest.raises(InvalidTransition):
        transition(Status.DEAD, Status.QUEUED)


@pytest.mark.parametrize("attempt,cap", [(1, 2), (2, 4), (8, 256), (9, 300), (1000, 300)])
def test_full_jitter_bounds(attempt, cap):
    samples = [retry_delay(attempt) for _ in range(100)]
    assert all(0 <= value <= cap for value in samples)
    assert len(set(samples)) > 1


@pytest.mark.parametrize("args", [(0, 2, 300), (1, -1, 300), (1, 10, 2)])
def test_invalid_backoff(args):
    with pytest.raises(ValueError):
        retry_delay(*args)


@pytest.mark.parametrize(
    "overrides",
    [
        {"heartbeat_ms": 10001},
        {"lease_ms": 0},
        {"api_keys": ""},
        {"queues": ""},
        {"max_backoff_s": 1},
        {"worker_concurrency": 0},
        {"queues": "invalid:queue"},
        {"base_backoff_s": float("nan")},
        {"reconcile_interval_s": float("inf")},
    ],
)
def test_invalid_settings(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


def test_settings_defaults_and_lists():
    settings = Settings(_env_file=None, api_keys="one, two", queues="default,other")
    assert settings.key_set == {"one", "two"}
    assert settings.queue_names == ("default", "other")
    assert settings.lease_ms == 30000 and settings.heartbeat_ms == 10000


@pytest.mark.parametrize(
    "change",
    [
        {"priority": -1},
        {"priority": 3},
        {"task": "missing"},
        {"run_at": "bad"},
        {"run_at": "2026-01-01T00:00:00"},
        {"max_attempts": 21},
        {"timeout_s": 0},
        {"queue": "evil:ready:0"},
        {"idempotency_key": ""},
        {"task": "sleep", "payload": {"seconds": -1}},
        {"task": "flaky", "payload": {"fail_rate": 2}},
        {"task": "cpu_hash", "payload": {"iterations": 0}},
    ],
)
def test_request_validation(change):
    with pytest.raises(ValidationError):
        JobCreate.model_validate({"task": "noop", **change})


def test_oversized_utf8_payload():
    with pytest.raises(ValidationError) as exc:
        JobCreate(task="noop", payload={"data": "é" * 32768})
    assert exc.value.errors()[0]["type"] == "payload_size"


def test_cursor_roundtrip():
    now, identifier = datetime.now(UTC), uuid4()
    assert decode_cursor(encode_cursor(now, identifier)) == (now, identifier)


@pytest.mark.parametrize(
    "value",
    [
        "?",
        "x" * 300,
        base64.b64encode(b"{}").decode(),
        base64.b64encode(json.dumps(["2026-01-01", str(uuid4())]).encode()).decode(),
    ],
)
def test_cursor_rejects_invalid(value):
    with pytest.raises(ValueError):
        decode_cursor(value)

import importlib
import json
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def test_package_is_importable():
    assert importlib.import_module("agenttrace").__name__ == "agenttrace"


def test_valid_trace_fixture_has_expected_events():
    lines = (FIXTURES / "valid_trace.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines if line.strip()]

    assert [event["type"] for event in events] == [
        "tool_schema", "tool_call", "tool_result", "tool_call", "tool_result"
    ]
    assert all(event["schema_version"] == 1 and event["trace_id"] == "t1" for event in events)
    assert len({event["event_id"] for event in events}) == len(events)
    assert events[0]["parameters"]["properties"]["id"]["type"] == "string"
    assert events[1]["arguments"]["id"] == 42
    assert [(events[i]["call_id"], events[i + 1]["call_id"]) for i in (1, 3)] == [
        ("call-1", "call-1"), ("call-2", "call-2")
    ]
    assert [events[2]["status"], events[4]["status"]] == ["error", "timeout"]


def test_invalid_json_fixture_is_malformed():
    with pytest.raises(json.JSONDecodeError):
        json.loads((FIXTURES / "invalid_json.jsonl").read_text(encoding="utf-8"))


def test_orphan_result_fixture_has_no_prior_call():
    event = json.loads((FIXTURES / "invalid_orphan_result.jsonl").read_text(encoding="utf-8"))
    assert event["type"] == "tool_result"
    assert event["call_id"] == "missing-call"

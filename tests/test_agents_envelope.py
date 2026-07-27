"""Test della busta applicativa (Envelope) e del tracer leggero usati per
correlare le chiamate A2A tra Advisor, Strategy Agent e Signal Agent.
Nessuna dipendenza da beeai_framework: girano sempre, anche prima di
installare lo stack AI pesante (vedi aitrade/agents/tracing.py sul perche'
non si usa OpenTelemetry qui)."""
from __future__ import annotations

import json

from aitrade.agents.envelope import Envelope
from aitrade.agents.tracing import new_trace_id, span


def test_envelope_roundtrip_preserves_data_trace_and_auth():
    env = Envelope(data={"snapshot": "equity=1000"}, auth="s3cret")
    parsed = Envelope.loads(env.dumps())
    assert parsed.data == {"snapshot": "equity=1000"}
    assert parsed.trace_id == env.trace_id
    assert parsed.auth == "s3cret"
    assert parsed.v == 1


def test_envelope_loads_plain_dict_as_legacy_payload():
    raw = json.dumps({"snapshot": "equity=1000", "headlines": ["a"]})
    env = Envelope.loads(raw)
    assert env.v == 0
    assert env.data == {"snapshot": "equity=1000", "headlines": ["a"]}
    assert env.trace_id  # generato comunque: anche i chiamanti legacy restano tracciabili


def test_envelope_loads_non_json_text_as_raw_legacy_payload():
    env = Envelope.loads("questo non e' JSON")
    assert env.v == 0
    assert env.data == {"raw": "questo non e' JSON"}


def test_check_auth_open_when_no_secret_required():
    env = Envelope(data={}, auth="")
    assert env.check_auth("") is True


def test_check_auth_rejects_when_secret_required_but_missing():
    env = Envelope(data={}, auth="")
    assert env.check_auth("s3cret") is False


def test_check_auth_accepts_matching_and_rejects_mismatched_secret():
    env = Envelope(data={}, auth="s3cret")
    assert env.check_auth("s3cret") is True
    assert env.check_auth("altro-valore") is False


def test_new_trace_id_is_short_and_unique():
    a, b = new_trace_id(), new_trace_id()
    assert a != b
    assert 8 <= len(a) <= 32


def test_span_records_ok_status_as_jsonline(tmp_path, monkeypatch):
    trace_file = tmp_path / "traces.jsonl"
    monkeypatch.setattr("aitrade.agents.tracing._TRACE_FILE", trace_file)
    with span("unit.test", "trace123", foo="bar"):
        pass
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["trace_id"] == "trace123"
    assert record["name"] == "unit.test"
    assert record["status"] == "ok"
    assert record["foo"] == "bar"
    assert record["duration_ms"] >= 0


def test_span_records_error_status_and_still_reraises(tmp_path, monkeypatch):
    trace_file = tmp_path / "traces.jsonl"
    monkeypatch.setattr("aitrade.agents.tracing._TRACE_FILE", trace_file)
    try:
        with span("unit.test.fail", "trace456"):
            raise ValueError("boom")
    except ValueError:
        pass
    else:
        raise AssertionError("l'eccezione originale doveva propagare")
    record = json.loads(trace_file.read_text(encoding="utf-8").splitlines()[0])
    assert record["status"] == "error"
    assert "boom" in record["error"]


def test_span_never_raises_if_disk_write_fails(monkeypatch):
    def _boom(_record):
        raise OSError("disco pieno")
    monkeypatch.setattr("aitrade.agents.tracing._write", _boom)
    with span("unit.test.disk_full", "trace789"):
        pass  # non deve sollevare nulla, anche se la scrittura su disco fallisce

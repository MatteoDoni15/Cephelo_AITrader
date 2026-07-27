"""Test di check_budget: nessuna chiamata di rete vera, requests.get e' sempre
sostituito con un doppio finto."""
from aitrade.agents import budget_guard as bg


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_ok_when_spend_below_threshold(monkeypatch):
    monkeypatch.setattr(bg.requests, "get",
                         lambda *a, **k: _FakeResponse({"spend": 3.0, "max_budget": 10.0}))
    status = bg.check_budget("key", "https://ai.ltp-contest.com", safety_margin=0.9)
    assert status.ok
    assert status.spend == 3.0
    assert status.max_budget == 10.0


def test_blocked_when_spend_above_threshold(monkeypatch):
    monkeypatch.setattr(bg.requests, "get",
                         lambda *a, **k: _FakeResponse({"spend": 9.5, "max_budget": 10.0}))
    status = bg.check_budget("key", "https://ai.ltp-contest.com", safety_margin=0.9)
    assert not status.ok


def test_exactly_at_threshold_is_blocked(monkeypatch):
    monkeypatch.setattr(bg.requests, "get",
                         lambda *a, **k: _FakeResponse({"spend": 9.0, "max_budget": 10.0}))
    status = bg.check_budget("key", "https://ai.ltp-contest.com", safety_margin=0.9)
    assert not status.ok  # 9.0 non e' < 9.0


def test_fail_open_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("timeout")
    monkeypatch.setattr(bg.requests, "get", boom)
    status = bg.check_budget("key", "https://ai.ltp-contest.com")
    assert status.ok  # fail-open: si procede comunque
    assert status.error


def test_fail_open_on_malformed_response(monkeypatch):
    monkeypatch.setattr(bg.requests, "get", lambda *a, **k: _FakeResponse({"unexpected": "shape"}))
    status = bg.check_budget("key", "https://ai.ltp-contest.com")
    assert status.ok
    assert status.error


def test_fail_open_when_not_configured():
    status = bg.check_budget("", "")
    assert status.ok
    assert status.error


def test_origin_derived_from_base_url_with_path(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse({"spend": 1.0, "max_budget": 10.0})

    monkeypatch.setattr(bg.requests, "get", fake_get)
    bg.check_budget("mykey", "https://ai.ltp-contest.com/v1")
    assert captured["url"] == "https://ai.ltp-contest.com/key/info"
    assert captured["headers"] == {"Authorization": "Bearer mykey"}

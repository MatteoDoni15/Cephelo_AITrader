"""Test degli agenti BeeAI (Signal/Strategy). Richiedono beeai-framework
installato (`pip install -r requirements.txt`): se assente, il modulo viene
saltato invece di fallire, cosi' il resto della suite resta eseguibile anche
prima di installare le dipendenze pesanti dell'AI stack."""
import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("beeai_framework")

from aitrade.agents.budget_guard import BudgetStatus  # noqa: E402
from aitrade.agents.signal_agent import _format_hit, _last_text  # noqa: E402
from aitrade.agents.strategy_agent import StrategyAgent, _search_query  # noqa: E402

_BUDGET_OK = BudgetStatus(ok=True, spend=1.0, max_budget=10.0)


def test_format_hit_combines_title_and_snippet():
    assert _format_hit({"title": "BTC pumps", "snippet": "up 5%"}) == "BTC pumps: up 5%"


def test_format_hit_empty_returns_empty_string():
    assert _format_hit({}) == ""


def test_format_hit_truncates_long_text():
    hit = {"title": "x" * 400, "snippet": "y"}
    assert len(_format_hit(hit)) <= 300


def test_last_text_returns_most_recent_nonempty():
    messages = [SimpleNamespace(text="prima"), SimpleNamespace(text=""), SimpleNamespace(text="ultima")]
    assert _last_text(messages) == "ultima"


def test_search_query_builds_from_real_symbols():
    assert _search_query(["BTC", "ETH"]) == "BTC ETH crypto news"


def test_search_query_caps_at_six_symbols():
    query = _search_query(["A", "B", "C", "D", "E", "F", "G", "H"])
    assert query == "A B C D E F crypto news"


def test_search_query_defaults_when_no_symbols():
    assert _search_query([]) == "crypto market news today"


def _run_agent(agent, request):
    """`agent.run(...)` (decorato con @runnable_entry) restituisce un oggetto
    beeai_framework.context.Run: awaitable, ma non un coroutine puro, quindi
    asyncio.run() lo rifiuta se passato direttamente (ValueError: 'a
    coroutine was expected'). Va atteso con `await` dentro una funzione
    async, esattamente come fa il codice di produzione (advisor.py,
    strategy_agent.py chiamano sempre `await agent.run(...)`)."""
    async def _invoke():
        return await agent.run(request)
    return asyncio.run(_invoke())


def test_strategy_agent_returns_valid_payload_on_success(monkeypatch):
    agent = StrategyAgent(api_key="k", base_url="http://x", model="MiniMax-M3",
                           signal_agent_url="http://127.0.0.1:8801")

    fake_response = SimpleNamespace(
        get_text_content=lambda: '\n\n{"risk_multiplier": 0.3, "regime": "volatile", "comment": "test"}')

    class FakeLLM:
        async def run(self, *a, **kw):
            return fake_response

    monkeypatch.setattr(agent, "_get_llm", lambda: FakeLLM())
    monkeypatch.setattr(agent, "_fetch_web_context", _async_return([]))
    monkeypatch.setattr("aitrade.agents.strategy_agent.check_budget", lambda *a, **k: _BUDGET_OK)

    request = json.dumps({"snapshot": "equity=1000", "headlines": ["news 1"]})
    out = _run_agent(agent, request)
    payload = json.loads(out.output[0].text)
    assert payload["risk_multiplier"] == 0.3


def test_strategy_agent_returns_error_payload_on_llm_failure(monkeypatch):
    agent = StrategyAgent(api_key="k", base_url="http://x", model="MiniMax-M3",
                           signal_agent_url="http://127.0.0.1:8801")

    class FailingLLM:
        async def run(self, *a, **kw):
            raise TimeoutError("AI Gateway timeout")

    monkeypatch.setattr(agent, "_get_llm", lambda: FailingLLM())
    monkeypatch.setattr(agent, "_fetch_web_context", _async_return([]))
    monkeypatch.setattr("aitrade.agents.strategy_agent.check_budget", lambda *a, **k: _BUDGET_OK)

    request = json.dumps({"snapshot": "equity=1000", "headlines": []})
    out = _run_agent(agent, request)
    payload = json.loads(out.output[0].text)
    assert "error" in payload


def test_strategy_agent_returns_error_payload_on_empty_content(monkeypatch):
    """Regressione: con MiniMax-M3 il response_format di BeeAI a volte
    restituiva contenuto vuoto (visto in produzione). Il parsing manuale deve
    gestirlo con un errore esplicito, mai un'eccezione non catturata."""
    agent = StrategyAgent(api_key="k", base_url="http://x", model="MiniMax-M3",
                           signal_agent_url="http://127.0.0.1:8801")

    fake_response = SimpleNamespace(get_text_content=lambda: "")

    class FakeLLM:
        async def run(self, *a, **kw):
            return fake_response

    monkeypatch.setattr(agent, "_get_llm", lambda: FakeLLM())
    monkeypatch.setattr(agent, "_fetch_web_context", _async_return([]))
    monkeypatch.setattr("aitrade.agents.strategy_agent.check_budget", lambda *a, **k: _BUDGET_OK)

    request = json.dumps({"snapshot": "equity=1000", "headlines": []})
    out = _run_agent(agent, request)
    payload = json.loads(out.output[0].text)
    assert "error" in payload


def test_strategy_agent_skips_llm_call_when_budget_exhausted(monkeypatch):
    agent = StrategyAgent(api_key="k", base_url="http://x", model="MiniMax-M3",
                           signal_agent_url="http://127.0.0.1:8801")

    def _must_not_be_called():
        raise AssertionError("l'AI Gateway non deve mai essere chiamato col budget esaurito")

    exhausted = BudgetStatus(ok=False, spend=9.5, max_budget=10.0)
    monkeypatch.setattr(agent, "_get_llm", lambda: _must_not_be_called())
    monkeypatch.setattr(agent, "_fetch_web_context", _async_return([]))
    monkeypatch.setattr("aitrade.agents.strategy_agent.check_budget", lambda *a, **k: exhausted)

    request = json.dumps({"snapshot": "equity=1000", "headlines": []})
    out = _run_agent(agent, request)
    payload = json.loads(out.output[0].text)
    assert payload == {"error": "ai_budget_exhausted"}


def test_strategy_agent_rejects_request_without_matching_secret(monkeypatch):
    from aitrade.agents.envelope import Envelope

    agent = StrategyAgent(api_key="k", base_url="http://x", model="MiniMax-M3",
                           signal_agent_url="http://127.0.0.1:8801", shared_secret="s3cret")

    def _must_not_be_called():
        raise AssertionError("l'AI Gateway non deve mai essere chiamato su una richiesta non autorizzata")

    monkeypatch.setattr(agent, "_get_llm", lambda: _must_not_be_called())

    request = Envelope(data={"snapshot": "equity=1000", "headlines": []}, auth="wrong").dumps()
    out = _run_agent(agent, request)
    payload = json.loads(out.output[0].text)
    assert payload == {"error": "unauthorized"}


def test_strategy_agent_accepts_request_with_matching_secret(monkeypatch):
    from aitrade.agents.envelope import Envelope

    agent = StrategyAgent(api_key="k", base_url="http://x", model="MiniMax-M3",
                           signal_agent_url="http://127.0.0.1:8801", shared_secret="s3cret")

    fake_response = SimpleNamespace(
        get_text_content=lambda: '{"risk_multiplier": 1.0, "regime": "normal", "comment": "ok"}')

    class FakeLLM:
        async def run(self, *a, **kw):
            return fake_response

    monkeypatch.setattr(agent, "_get_llm", lambda: FakeLLM())
    monkeypatch.setattr(agent, "_fetch_web_context", _async_return([]))
    monkeypatch.setattr("aitrade.agents.strategy_agent.check_budget", lambda *a, **k: _BUDGET_OK)

    request = Envelope(data={"snapshot": "equity=1000", "headlines": []}, auth="s3cret").dumps()
    out = _run_agent(agent, request)
    payload = json.loads(out.output[0].text)
    assert payload["risk_multiplier"] == 1.0


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner

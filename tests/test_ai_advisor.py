"""Test dell'Advisor come client A2A: la chiamata reale allo Strategy Agent
(`_call_strategy_agent`) viene sostituita con un doppio finto, cosi' il test
non richiede beeai-framework installato ne' un agente in ascolto."""
from aitrade.agents.envelope import Envelope
from aitrade.ai.advisor import Advisor
from aitrade.config import AiCfg
from aitrade.portfolio import AiBudget


def make_advisor(**overrides) -> Advisor:
    cfg = AiCfg(enabled=True, api_key="k", base_url="http://x", model="MiniMax-M3",
                strategy_agent_url="http://127.0.0.1:8802", max_calls_per_day=3, interval_hours=8)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return Advisor(cfg)


def test_is_ready_requires_full_config():
    assert make_advisor().is_ready()
    assert not make_advisor(enabled=False).is_ready()
    assert not make_advisor(api_key="").is_ready()
    assert not make_advisor(base_url="").is_ready()


def test_should_call_respects_daily_budget():
    adv = make_advisor()
    budget = AiBudget(day="2026-07-23", calls_today=3, last_call_ts=0.0)
    assert not adv.should_call(budget, now=1000.0)  # gia' al limite giornaliero


def test_should_call_respects_interval():
    adv = make_advisor()
    budget = AiBudget(day="2026-07-23", calls_today=1, last_call_ts=1000.0)
    assert not adv.should_call(budget, now=1000.0 + 3600)   # < 8h dopo
    assert adv.should_call(budget, now=1000.0 + 8 * 3600)   # >= 8h dopo


def test_assess_updates_multiplier_on_success(monkeypatch):
    adv = make_advisor()
    budget = AiBudget(risk_multiplier=1.0)

    async def fake_call(envelope: Envelope):
        assert envelope.data == {"snapshot": "snapshot", "headlines": ["headline"]}
        return {"risk_multiplier": 0.4, "regime": "volatile", "comment": "spike"}

    monkeypatch.setattr(adv, "_call_strategy_agent", fake_call)
    result = adv.assess(budget, "snapshot", ["headline"])
    assert result == 0.4
    assert budget.risk_multiplier == 0.4
    assert "volatile" in budget.last_comment


def test_assess_builds_envelope_with_trace_id_and_configured_secret(monkeypatch):
    adv = make_advisor(shared_secret="s3cret")
    budget = AiBudget(risk_multiplier=1.0)
    captured = {}

    async def fake_call(envelope: Envelope):
        captured["envelope"] = envelope
        return {"risk_multiplier": 1.0, "regime": "normal", "comment": ""}

    monkeypatch.setattr(adv, "_call_strategy_agent", fake_call)
    adv.assess(budget, "snapshot", [])
    envelope = captured["envelope"]
    assert envelope.auth == "s3cret"
    assert envelope.trace_id  # generato per correlare i log dei 3 processi


def test_assess_falls_back_neutral_on_strategy_agent_error(monkeypatch):
    adv = make_advisor()
    budget = AiBudget(risk_multiplier=0.8)

    async def fake_call(envelope: Envelope):
        raise ConnectionError("Strategy Agent non raggiungibile")

    monkeypatch.setattr(adv, "_call_strategy_agent", fake_call)
    result = adv.assess(budget, "snapshot", [])
    assert result == 0.8  # invariato


def test_assess_falls_back_neutral_on_error_payload(monkeypatch):
    adv = make_advisor()
    budget = AiBudget(risk_multiplier=0.9)

    async def fake_call(envelope: Envelope):
        return {"error": "AI Gateway timeout"}

    monkeypatch.setattr(adv, "_call_strategy_agent", fake_call)
    result = adv.assess(budget, "snapshot", [])
    assert result == 0.9  # invariato


def test_assess_clamps_out_of_range_multiplier(monkeypatch):
    adv = make_advisor()
    budget = AiBudget(risk_multiplier=1.0)

    async def fake_call(envelope: Envelope):
        return {"risk_multiplier": 5.0, "regime": "x", "comment": "y"}

    monkeypatch.setattr(adv, "_call_strategy_agent", fake_call)
    result = adv.assess(budget, "snapshot", [])
    assert result == 1.0

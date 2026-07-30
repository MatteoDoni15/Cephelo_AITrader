"""Test di Engine._maybe_alert: notifica solo alla transizione di livello,
mai ripetuta finche' si resta nello stesso livello critico."""
from aitrade.config import Config
from aitrade.engine import Engine
from aitrade.risk import HARD_KILL, NORMAL, SOFT_KILL


def make_engine(tmp_path, **risk_overrides) -> Engine:
    cfg = Config(mode="paper", root=tmp_path)
    for k, v in risk_overrides.items():
        setattr(cfg.risk, k, v)
    return Engine(cfg, mode="paper")


def test_no_alert_in_normal_level(tmp_path, monkeypatch):
    sent = []
    tg_sent = []
    monkeypatch.setattr("aitrade.engine.send_alert", lambda url, msg: sent.append((url, msg)))
    monkeypatch.setattr("aitrade.engine.send_telegram", lambda token, chat_id, msg: tg_sent.append((token, chat_id, msg)))
    engine = make_engine(tmp_path, alert_webhook_url="https://example.com/hook",
                         telegram_bot_token="tok", telegram_chat_id="chat")

    engine._maybe_alert(NORMAL, 1000.0, 0.0)
    assert sent == []
    assert tg_sent == []


def test_alert_fires_once_per_transition_into_critical_level(tmp_path, monkeypatch):
    sent = []
    tg_sent = []
    monkeypatch.setattr("aitrade.engine.send_alert", lambda url, msg: sent.append((url, msg)))
    monkeypatch.setattr("aitrade.engine.send_telegram", lambda token, chat_id, msg: tg_sent.append((token, chat_id, msg)))
    engine = make_engine(tmp_path, alert_webhook_url="https://example.com/hook",
                         telegram_bot_token="tok", telegram_chat_id="chat")

    engine._maybe_alert(SOFT_KILL, 880.0, 0.12)
    assert len(sent) == 1
    assert "SOFT_KILL" in sent[0][1]
    assert len(tg_sent) == 1
    assert "SOFT_KILL" in tg_sent[0][2]

    engine._maybe_alert(SOFT_KILL, 878.0, 0.122)  # resta in SOFT_KILL: nessuna ripetizione
    assert len(sent) == 1
    assert len(tg_sent) == 1

    engine._maybe_alert(HARD_KILL, 840.0, 0.16)  # transizione a un livello peggiore: nuova notifica
    assert len(sent) == 2
    assert "HARD_KILL" in sent[1][1]
    assert len(tg_sent) == 2
    assert "HARD_KILL" in tg_sent[1][2]


def test_no_repeat_alert_after_recovery_and_relapse(tmp_path, monkeypatch):
    sent = []
    tg_sent = []
    monkeypatch.setattr("aitrade.engine.send_alert", lambda url, msg: sent.append((url, msg)))
    monkeypatch.setattr("aitrade.engine.send_telegram", lambda token, chat_id, msg: tg_sent.append((token, chat_id, msg)))
    engine = make_engine(tmp_path, alert_webhook_url="https://example.com/hook",
                         telegram_bot_token="tok", telegram_chat_id="chat")

    engine._maybe_alert(SOFT_KILL, 880.0, 0.12)
    engine._maybe_alert(NORMAL, 950.0, 0.05)  # recupero: nessuna notifica di "rientro"
    engine._maybe_alert(SOFT_KILL, 880.0, 0.12)  # ricade: nuova notifica, e' una nuova transizione
    assert len(sent) == 2
    assert len(tg_sent) == 2

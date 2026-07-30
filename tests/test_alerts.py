from aitrade import alerts


def test_send_alert_does_nothing_when_no_webhook_configured(monkeypatch):
    called = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: called.append(1))
    alerts.send_alert("", "messaggio")
    assert called == []


def test_send_alert_posts_text_and_content_for_slack_and_discord(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout

    monkeypatch.setattr(alerts.requests, "post", fake_post)
    alerts.send_alert("https://example.com/webhook", "livello SOFT_KILL")
    assert captured["url"] == "https://example.com/webhook"
    assert captured["json"] == {"text": "livello SOFT_KILL", "content": "livello SOFT_KILL"}
    assert captured["timeout"] == alerts.TIMEOUT_SEC


def test_send_alert_never_raises_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("timeout")
    monkeypatch.setattr(alerts.requests, "post", boom)
    alerts.send_alert("https://example.com/webhook", "messaggio")  # non deve sollevare nulla


def test_send_telegram_does_nothing_when_not_configured(monkeypatch):
    called = []
    monkeypatch.setattr(alerts.requests, "post", lambda *a, **k: called.append(1))
    alerts.send_telegram("", "", "messaggio")
    alerts.send_telegram("token123", "", "messaggio")
    alerts.send_telegram("", "chat123", "messaggio")
    assert called == []


def test_send_telegram_posts_chat_id_and_text(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout

    monkeypatch.setattr(alerts.requests, "post", fake_post)
    alerts.send_telegram("token123", "chat456", "livello SOFT_KILL")
    assert captured["url"] == "https://api.telegram.org/bottoken123/sendMessage"
    assert captured["json"] == {"chat_id": "chat456", "text": "livello SOFT_KILL"}
    assert captured["timeout"] == alerts.TIMEOUT_SEC


def test_send_telegram_never_raises_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("timeout")
    monkeypatch.setattr(alerts.requests, "post", boom)
    alerts.send_telegram("token123", "chat456", "messaggio")  # non deve sollevare nulla

from aitrade.portfolio import State, Store
from aitrade.telegram_status_bot import handle_update


def make_store(tmp_path) -> Store:
    return Store(tmp_path / "state.json", tmp_path / "trades.csv")


def _update(chat_id, text) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


def test_ignores_message_from_unauthorized_chat(tmp_path):
    store = make_store(tmp_path)
    reply = handle_update(_update(999, "status"), chat_id="140703768", store=store)
    assert reply is None


def test_ignores_text_that_is_not_a_status_command(tmp_path):
    store = make_store(tmp_path)
    reply = handle_update(_update(140703768, "ciao come va?"), chat_id="140703768", store=store)
    assert reply is None


def test_replies_with_status_for_authorized_chat(tmp_path):
    store = make_store(tmp_path)
    store.save(State(equity=900.0, risk={"hwm": 1000.0}))
    reply = handle_update(_update(140703768, "status"), chat_id="140703768", store=store)
    assert reply is not None
    assert "900.00 USDT" in reply


def test_status_command_is_case_and_slash_insensitive(tmp_path):
    store = make_store(tmp_path)
    assert handle_update(_update(1, "STATUS"), chat_id="1", store=store) is not None
    assert handle_update(_update(1, "/status"), chat_id="1", store=store) is not None
    assert handle_update(_update(1, "  status  "), chat_id="1", store=store) is not None


def test_ignores_update_without_message(tmp_path):
    store = make_store(tmp_path)
    reply = handle_update({"update_id": 1}, chat_id="140703768", store=store)
    assert reply is None

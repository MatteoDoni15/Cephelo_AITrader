import csv

from aitrade.portfolio import AiBudget, Store


def make_store(tmp_path) -> Store:
    return Store(tmp_path / "state.json", tmp_path / "trades.csv")


def _read_rows(trades_file) -> list[dict]:
    with trades_file.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_open_trade_logs_ai_multiplier_and_trace_id(tmp_path):
    store = make_store(tmp_path)
    store.log_trade("paper", "BINANCE_PERP_BTC_USDT", "OPEN", "LONG", 1.0, 100.0,
                    0.5, 0.0, "momentum rank 1", ai_multiplier=0.75, ai_trace_id="abc123")
    rows = _read_rows(store.trades_file)
    assert len(rows) == 1
    assert rows[0]["ai_multiplier"] == "0.7500"
    assert rows[0]["ai_trace_id"] == "abc123"


def test_close_trade_leaves_ai_fields_blank(tmp_path):
    """L'AI scala solo il sizing delle aperture: le chiusure non passano mai
    ai_multiplier/ai_trace_id (default), e il log lo riflette per costruzione."""
    store = make_store(tmp_path)
    store.log_trade("paper", "BINANCE_PERP_BTC_USDT", "CLOSE", "LONG", 1.0, 110.0,
                    0.5, 10.0, "trailing stop")
    rows = _read_rows(store.trades_file)
    assert rows[0]["ai_multiplier"] == ""
    assert rows[0]["ai_trace_id"] == ""


def test_trade_log_header_includes_ai_correlation_columns(tmp_path):
    store = make_store(tmp_path)
    store.log_trade("paper", "BINANCE_PERP_BTC_USDT", "OPEN", "LONG", 1.0, 100.0,
                    0.5, 0.0, "momentum rank 1")
    header = store.trades_file.read_text(encoding="utf-8").splitlines()[0]
    assert "ai_multiplier" in header
    assert "ai_trace_id" in header


def test_ai_budget_state_roundtrips_last_trace_id(tmp_path):
    store = make_store(tmp_path)
    state = store.load()
    state.ai = AiBudget(risk_multiplier=0.6, last_trace_id="trace-xyz")
    store.save(state)
    reloaded = store.load()
    assert reloaded.ai.last_trace_id == "trace-xyz"
    assert reloaded.ai.risk_multiplier == 0.6

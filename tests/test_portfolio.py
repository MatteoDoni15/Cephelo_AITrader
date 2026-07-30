import csv

from aitrade.portfolio import AiBudget, Position, State, Store, format_status


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


def test_format_status_reports_equity_drawdown_and_no_positions():
    state = State(equity=950.0, risk={"hwm": 1000.0, "hard_killed": False})
    text = format_status(state)
    assert "950.00 USDT" in text
    assert "HWM 1000.00" in text
    assert "5.00%" in text
    assert "Hard killed: False" in text
    assert "Posizioni:   nessuna" in text


def test_format_status_lists_open_positions():
    state = State(equity=1000.0, risk={"hwm": 1000.0})
    state.positions["BINANCE_PERP_BTC_USDT"] = Position(
        sym="BINANCE_PERP_BTC_USDT", side="LONG", qty=0.5, entry_price=60000.0,
        best_price=61000.0, stop_price=58000.0, atr_at_entry=500.0, opened_at=0.0,
    )
    text = format_status(state)
    assert "LONG " in text
    assert "BINANCE_PERP_BTC_USDT" in text
    assert "entry=60000" in text
    assert "stop=58000" in text


def test_format_status_shows_ai_comment_when_present():
    state = State(ai=AiBudget(risk_multiplier=0.4, calls_today=2, last_comment="regime nervoso"))
    text = format_status(state)
    assert "mult=0.40" in text
    assert "calls_oggi=2" in text
    assert "regime nervoso" in text

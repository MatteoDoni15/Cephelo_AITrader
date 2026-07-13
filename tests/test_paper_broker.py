from aitrade.broker.paper import PaperBroker
from aitrade.config import ExecutionCfg


def make_broker() -> PaperBroker:
    cfg = ExecutionCfg(paper_fee_bps=10.0, paper_slippage_bps=0.0)
    return PaperBroker(cfg, starting_cash=1000.0)


def test_long_round_trip():
    b = make_broker()
    fill = b.open_position("S", "LONG", 1.0, 100.0)
    assert fill.price == 100.0 and abs(fill.fee - 0.1) < 1e-9
    assert abs(b.cash - 999.9) < 1e-9

    b.update_marks({"S": 110.0})
    assert abs(b.get_equity() - (999.9 + 10.0)) < 1e-9

    out = b.close_position("S", "LONG", 110.0)
    assert abs(out.realized_pnl - (10.0 - 0.11)) < 1e-9
    assert abs(b.cash - (999.9 + 10.0 - 0.11)) < 1e-9
    assert b.get_equity() == b.cash
    assert not b.positions


def test_short_profits_when_price_falls():
    b = make_broker()
    b.open_position("S", "SHORT", 2.0, 50.0)
    b.update_marks({"S": 40.0})
    assert b.get_equity() > 1000.0
    out = b.close_position("S", "SHORT", 40.0)
    assert out.realized_pnl > 19.0  # 2 * 10 meno le fee


def test_no_duplicate_position():
    b = make_broker()
    assert b.open_position("S", "LONG", 1.0, 100.0) is not None
    assert b.open_position("S", "LONG", 1.0, 100.0) is None


def test_flatten_all():
    b = make_broker()
    b.open_position("A", "LONG", 1.0, 100.0)
    b.open_position("B", "SHORT", 1.0, 100.0)
    b.flatten_all({"A": 100.0, "B": 100.0})
    assert not b.positions

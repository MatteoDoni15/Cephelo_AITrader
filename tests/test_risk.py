from aitrade.config import RiskCfg
from aitrade.risk import HARD_KILL, NORMAL, SOFT_KILL, WARN, RiskManager, SizingInput


def make_rm() -> RiskManager:
    rm = RiskManager(RiskCfg())
    rm.update_equity(1000.0)  # fissa l'high-water mark
    return rm


def test_drawdown_levels():
    rm = make_rm()
    assert rm.update_equity(950.0) == NORMAL      # -5%
    assert rm.update_equity(915.0) == WARN        # -8.5%
    assert rm.update_equity(875.0) == SOFT_KILL   # -12.5%
    assert rm.update_equity(845.0) == HARD_KILL   # -15.5%
    # il kill e' permanente finche' non viene resettato
    assert rm.update_equity(999.0) == HARD_KILL
    rm.reset_kill()
    assert rm.update_equity(999.0) == NORMAL


def test_sizing_vol_target():
    rm = make_rm()
    qty = rm.position_qty(SizingInput(equity=1000, price=100, atr=2, gross_notional_open=0))
    # rischio 0.75% a distanza 3*ATR=6 -> 1000*0.0075/6 = 1.25
    assert abs(qty - 1.25) < 1e-9


def test_sizing_respects_single_position_cap():
    rm = make_rm()
    # ATR piccolissimo -> qty risk enorme -> deve valere il cap del 35% nozionale
    qty = rm.position_qty(SizingInput(equity=1000, price=100, atr=0.01, gross_notional_open=0))
    assert qty * 100 <= 350 + 1e-9


def test_sizing_respects_gross_leverage_cap():
    rm = make_rm()
    qty = rm.position_qty(SizingInput(equity=1000, price=100, atr=0.01,
                                      gross_notional_open=1500))
    assert qty == 0.0


def test_sizing_halved_in_warn():
    rm = make_rm()
    full = rm.position_qty(SizingInput(equity=1000, price=100, atr=2, gross_notional_open=0))
    rm2 = make_rm()
    rm2.update_equity(910.0)  # WARN
    half = rm2.position_qty(SizingInput(equity=910, price=100, atr=2, gross_notional_open=0))
    assert half < full * 0.6  # ~la meta' (equity anche leggermente inferiore)


def test_no_new_positions_in_soft_kill():
    rm = make_rm()
    rm.update_equity(875.0)
    assert not rm.can_open(875.0)
    assert rm.position_qty(SizingInput(equity=875, price=100, atr=2, gross_notional_open=0)) == 0.0


def test_trailing_stop_never_retreats():
    rm = make_rm()
    stop = rm.initial_stop("LONG", 100.0, 2.0)
    assert stop == 94.0
    stop = rm.trail_stop("LONG", 110.0, 2.0, stop)
    assert stop == 104.0
    stop = rm.trail_stop("LONG", 105.0, 2.0, stop)   # il best e' sceso: stop fermo
    assert stop == 104.0
    assert rm.stop_hit("LONG", 103.9, stop)
    assert not rm.stop_hit("LONG", 104.1, stop)


def test_trailing_stop_short():
    rm = make_rm()
    stop = rm.initial_stop("SHORT", 100.0, 2.0)
    assert stop == 106.0
    stop = rm.trail_stop("SHORT", 90.0, 2.0, stop)
    assert stop == 96.0
    assert rm.stop_hit("SHORT", 96.5, stop)

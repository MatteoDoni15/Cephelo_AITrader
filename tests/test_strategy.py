import numpy as np
import pandas as pd

from aitrade.config import StrategyCfg
from aitrade.strategy.momentum import MomentumStrategy


def make_cfg() -> StrategyCfg:
    return StrategyCfg(
        ema_fast=10, ema_slow=40, momentum_bars=20, min_abs_momentum=0.02,
        atr_period=14, max_longs=2, max_shorts=1, allow_short=True,
        entry_rank=2, exit_rank=4, warmup_bars=60,
        min_atr_pct=0.0001, max_atr_pct=0.5,
    )


def make_df(trend_per_bar: float, n: int = 200, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    closes = start * np.cumprod(1 + trend_per_bar + rng.normal(0, 0.001, n))
    opens = np.roll(closes, 1)
    opens[0] = start
    highs = np.maximum(opens, closes) * 1.002
    lows = np.minimum(opens, closes) * 0.998
    return pd.DataFrame({
        "open_time": np.arange(n) * 14_400_000,
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": np.full(n, 1000.0),
    })


def test_uptrend_generates_long():
    strat = MomentumStrategy(make_cfg())
    feats = {
        "UP": strat.latest_features("UP", make_df(+0.01)),
        "FLAT": strat.latest_features("FLAT", make_df(0.0)),
    }
    decisions = strat.decide(feats, held={})
    opens = [d for d in decisions if d.action == "OPEN"]
    assert any(d.sym == "UP" and d.side == "LONG" for d in opens)
    assert not any(d.sym == "FLAT" for d in opens)


def test_downtrend_generates_short():
    strat = MomentumStrategy(make_cfg())
    feats = {
        "DOWN": strat.latest_features("DOWN", make_df(-0.01)),
        "FLAT": strat.latest_features("FLAT", make_df(0.0)),
    }
    decisions = strat.decide(feats, held={})
    assert any(d.sym == "DOWN" and d.side == "SHORT" and d.action == "OPEN"
               for d in decisions)


def test_broken_trend_closes_position():
    strat = MomentumStrategy(make_cfg())
    feats = {"X": strat.latest_features("X", make_df(-0.01))}  # trend giu'
    decisions = strat.decide(feats, held={"X": "LONG"})        # ma siamo long
    assert any(d.sym == "X" and d.action == "CLOSE" for d in decisions)


def test_max_positions_respected():
    strat = MomentumStrategy(make_cfg())
    feats = {s: strat.latest_features(s, make_df(+0.01 + i * 0.001))
             for i, s in enumerate(["A", "B", "C", "D"])}
    decisions = strat.decide(feats, held={})
    opens = [d for d in decisions if d.action == "OPEN" and d.side == "LONG"]
    assert len(opens) <= 2  # max_longs=2 e entry_rank=2


def test_warmup_returns_none():
    strat = MomentumStrategy(make_cfg())
    assert strat.latest_features("X", make_df(0.01, n=30)) is None

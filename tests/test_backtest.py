import numpy as np
import pandas as pd

from aitrade.backtest import run_backtest
from aitrade.config import Config, StrategyCfg


def make_df(trend_per_bar: float, n: int = 400, start: float = 100.0,
            seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = start * np.cumprod(1 + trend_per_bar + rng.normal(0, 0.002, n))
    opens = np.roll(closes, 1)
    opens[0] = start
    highs = np.maximum(opens, closes) * 1.003
    lows = np.minimum(opens, closes) * 0.997
    return pd.DataFrame({
        "open_time": np.arange(n) * 14_400_000,
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": np.full(n, 1000.0),
    })


def make_cfg() -> Config:
    cfg = Config()
    cfg.strategy = StrategyCfg(
        ema_fast=10, ema_slow=40, momentum_bars=20, min_abs_momentum=0.02,
        atr_period=14, max_longs=2, max_shorts=1, allow_short=True,
        entry_rank=2, exit_rank=4, warmup_bars=60,
        min_atr_pct=0.0001, max_atr_pct=0.5,
    )
    return cfg


def test_backtest_runs_and_reports_metrics():
    data = {
        "UP": make_df(+0.008, seed=1),
        "DOWN": make_df(-0.008, seed=2),
        "FLAT": make_df(0.0, seed=3),
    }
    result = run_backtest(make_cfg(), data, starting_cash=1000.0)
    assert result.final_equity > 0
    assert result.n_trades >= 1
    assert 0.0 <= result.max_drawdown <= 1.0
    assert not result.equity_curve.empty
    # trend forti e puliti in entrambe le direzioni: il momentum deve guadagnare
    assert result.total_return > 0
    assert "RISULTATI BACKTEST" in result.report()


def test_backtest_requires_history():
    import pytest
    with pytest.raises(ValueError):
        run_backtest(make_cfg(), {"X": make_df(0.01, n=10)})

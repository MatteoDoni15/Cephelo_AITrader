"""Indicatori in puro pandas/numpy (nessuna dipendenza da TA-Lib)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (smoothing di Wilder)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def momentum(close: pd.Series, bars: int) -> pd.Series:
    """Rendimento percentuale sugli ultimi `bars` periodi."""
    return close / close.shift(bars) - 1.0


def realized_vol(close: pd.Series, bars: int = 30) -> pd.Series:
    """Deviazione standard dei log-rendimenti (per barra, non annualizzata)."""
    ret = np.log(close / close.shift(1))
    return ret.rolling(bars).std()

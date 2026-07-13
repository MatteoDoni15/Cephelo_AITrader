"""Backtest della strategia sugli stessi moduli usati live (strategia, rischio, fill).

Riporta ESATTAMENTE le quattro metriche con cui la gara assegna il punteggio:
Return, Sharpe, Max Drawdown, Win Rate — piu' il numero di trade e l'esito
del kill-switch. Esecuzione: segnali sulla candela chiusa, fill all'open della
candela successiva (niente look-ahead), stop controllati intrabar su low/high.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

import pandas as pd

from .broker.base import Fill
from .broker.paper import PaperBroker
from .config import Config
from .data.klines import interval_ms
from .portfolio import Position
from .risk import HARD_KILL, RiskManager, SizingInput
from .strategy.momentum import MomentumStrategy

log = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    total_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    n_trades: int = 0
    final_equity: float = 0.0
    hard_killed: bool = False
    equity_curve: pd.Series = field(default_factory=pd.Series)
    trades: list[Fill] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            "================ RISULTATI BACKTEST ================",
            f"  Return totale : {self.total_return:+.2%}",
            f"  Sharpe (ann.) : {self.sharpe:.2f}",
            f"  Max Drawdown  : {self.max_drawdown:.2%}",
            f"  Win Rate      : {self.win_rate:.1%}",
            f"  Trade chiusi  : {self.n_trades}",
            f"  Equity finale : {self.final_equity:.2f} USDT",
        ]
        if self.hard_killed:
            lines.append("  !!! HARD KILL scattato durante il backtest !!!")
        lines.append("====================================================")
        return "\n".join(lines)


def run_backtest(cfg: Config, data: dict[str, pd.DataFrame],
                 starting_cash: float = 1000.0) -> BacktestResult:
    strategy = MomentumStrategy(cfg.strategy)
    risk = RiskManager(cfg.risk)
    broker = PaperBroker(cfg.execution, starting_cash=starting_cash)
    step = interval_ms(cfg.timeframe)
    warmup = cfg.strategy.warmup_bars

    frames: dict[str, pd.DataFrame] = {}
    for sym, df in data.items():
        if df is None or len(df) < warmup + 5:
            continue
        f = strategy.compute_features_frame(df)
        f["bar_idx"] = range(len(f))
        frames[sym] = f.set_index("open_time")

    if not frames:
        raise ValueError("Nessun simbolo con storico sufficiente: esegui prima download-data")

    times = sorted(set().union(*[set(f.index) for f in frames.values()]))
    positions: dict[str, Position] = {}
    trades: list[Fill] = []
    equity_points: dict[int, float] = {}
    hard_killed = False

    def next_open(sym: str, t: int) -> float | None:
        fr = frames[sym]
        nxt = t + step
        if nxt in fr.index:
            return float(fr.loc[nxt, "open"])
        return None

    for t in times:
        rows = {sym: fr.loc[t] for sym, fr in frames.items() if t in fr.index}

        # --- 1. stop intrabar (gap all'open compreso)
        for sym, pos in list(positions.items()):
            row = rows.get(sym)
            if row is None:
                continue
            fill_px = None
            if pos.side == "LONG":
                if float(row["open"]) <= pos.stop_price:
                    fill_px = float(row["open"])
                elif float(row["low"]) <= pos.stop_price:
                    fill_px = pos.stop_price
            else:
                if float(row["open"]) >= pos.stop_price:
                    fill_px = float(row["open"])
                elif float(row["high"]) >= pos.stop_price:
                    fill_px = pos.stop_price
            if fill_px is not None:
                fill = broker.close_position(sym, pos.side, fill_px)
                if fill:
                    trades.append(fill)
                del positions[sym]
                continue
            # trailing sul prezzo migliore raggiunto nella barra
            if pos.side == "LONG":
                pos.best_price = max(pos.best_price, float(row["high"]))
            else:
                pos.best_price = min(pos.best_price, float(row["low"]))
            pos.stop_price = risk.trail_stop(pos.side, pos.best_price,
                                             pos.atr_at_entry, pos.stop_price)

        # --- 2. equity a chiusura barra
        closes = {sym: float(r["close"]) for sym, r in rows.items()}
        broker.update_marks(closes)
        equity = broker.get_equity()
        level = risk.update_equity(equity)
        equity_points[t + step] = equity

        if level == HARD_KILL:
            broker.flatten_all(closes)
            positions.clear()
            hard_killed = True
            equity_points[t + step] = broker.get_equity()
            break

        # --- 3. segnali a chiusura barra, esecuzione all'open successivo
        feats = {}
        for sym, row in rows.items():
            if row["bar_idx"] < warmup or pd.isna(row["mom"]):
                continue
            feats[sym] = strategy.features_from_row(sym, row)

        held = {sym: p.side for sym, p in positions.items()}
        decisions = strategy.decide(feats, held)

        for d in [d for d in decisions if d.action == "CLOSE"]:
            pos = positions.get(d.sym)
            if pos is None:
                continue
            px = next_open(d.sym, t) or closes.get(d.sym)
            if px:
                fill = broker.close_position(d.sym, pos.side, px)
                if fill:
                    trades.append(fill)
                del positions[d.sym]

        equity = broker.get_equity()
        if risk.can_open(equity):
            for d in [d for d in decisions if d.action == "OPEN"]:
                f = d.features
                px = next_open(d.sym, t)
                if f is None or px is None:
                    continue
                gross = sum(p.qty * closes.get(s, p.entry_price)
                            for s, p in positions.items())
                qty = risk.position_qty(SizingInput(
                    equity=equity, price=px, atr=f.atr, gross_notional_open=gross))
                fill = broker.open_position(d.sym, d.side, qty, px)
                if fill:
                    trades.append(fill)
                    positions[d.sym] = Position(
                        sym=d.sym, side=d.side, qty=fill.qty, entry_price=fill.price,
                        best_price=fill.price, atr_at_entry=f.atr,
                        stop_price=risk.initial_stop(d.side, fill.price, f.atr),
                        opened_at=t / 1000.0,
                    )

    # ------------------------------------------------------------- metriche
    eq = pd.Series(equity_points).sort_index()
    result = BacktestResult(equity_curve=eq, trades=trades, hard_killed=hard_killed)
    if eq.empty:
        return result
    result.final_equity = float(eq.iloc[-1])
    result.total_return = result.final_equity / starting_cash - 1.0
    rets = eq.pct_change().dropna()
    if len(rets) > 2 and rets.std() > 0:
        bars_per_year = 365.0 * 24 * 3_600_000 / step
        result.sharpe = float(rets.mean() / rets.std() * math.sqrt(bars_per_year))
    result.max_drawdown = float(-(eq / eq.cummax() - 1.0).min())
    closed = [f for f in trades if f.action == "CLOSE"]
    result.n_trades = len(closed)
    if closed:
        result.win_rate = sum(1 for f in closed if f.realized_pnl > 0) / len(closed)
    return result

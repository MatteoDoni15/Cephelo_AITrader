"""Strategia: momentum cross-sectional con filtro di trend, su barre 4h.

Razionale per questa gara:
  - rate limit 1 ordine/5s -> impossibile fare HFT/market making: si lavora a
    bassa frequenza (poche operazioni al giorno);
  - punteggio = Return + Sharpe + MDD + Win Rate -> serve rendimento con
    drawdown contenuto: trend following con vol-targeting e trailing stop;
  - 50 coppie fisse -> la selezione cross-sectional (comprare i piu' forti,
    eventualmente shortare i piu' deboli) sfrutta tutta la whitelist.

Regole:
  LONG:  trend up (EMA fast > EMA slow, close > EMA fast) e momentum tra i
         primi `entry_rank` della whitelist con momentum >= min_abs_momentum.
  SHORT: speculare sui piu' deboli (se allow_short).
  EXIT:  trend rotto, oppure rank oltre `exit_rank` (isteresi), oppure
         trailing stop ATR (gestito da engine/backtest via RiskManager).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import StrategyCfg
from . import indicators as ind


@dataclass
class Features:
    """Ultima riga di features per un simbolo (candela chiusa piu' recente)."""
    sym: str
    close: float
    atr: float
    momentum: float
    trend_up: bool
    trend_down: bool

    @property
    def atr_pct(self) -> float:
        return self.atr / self.close if self.close else 0.0


@dataclass
class Decision:
    sym: str
    action: str          # "OPEN" | "CLOSE" | "HOLD"
    side: str            # "LONG" | "SHORT"
    reason: str
    features: Features | None = None


class MomentumStrategy:
    def __init__(self, cfg: StrategyCfg):
        self.cfg = cfg

    # ------------------------------------------------------------- features

    def compute_features_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggiunge le colonne di features all'intero storico (per il backtest)."""
        out = df.copy()
        out["ema_fast"] = ind.ema(out["close"], self.cfg.ema_fast)
        out["ema_slow"] = ind.ema(out["close"], self.cfg.ema_slow)
        out["atr"] = ind.atr(out, self.cfg.atr_period)
        out["mom"] = ind.momentum(out["close"], self.cfg.momentum_bars)
        out["trend_up"] = (out["ema_fast"] > out["ema_slow"]) & (out["close"] > out["ema_fast"])
        out["trend_down"] = (out["ema_fast"] < out["ema_slow"]) & (out["close"] < out["ema_fast"])
        return out

    def latest_features(self, sym: str, df: pd.DataFrame) -> Features | None:
        if df is None or len(df) < self.cfg.warmup_bars:
            return None
        f = self.compute_features_frame(df).iloc[-1]
        return self.features_from_row(sym, f)

    @staticmethod
    def features_from_row(sym: str, row: pd.Series) -> Features:
        return Features(
            sym=sym,
            close=float(row["close"]),
            atr=float(row["atr"]),
            momentum=float(row["mom"]) if pd.notna(row["mom"]) else 0.0,
            trend_up=bool(row["trend_up"]),
            trend_down=bool(row["trend_down"]),
        )

    # ------------------------------------------------------------- decisions

    def decide(self, feats: dict[str, Features],
               held: dict[str, str]) -> list[Decision]:
        """feats: features per simbolo; held: {sym: 'LONG'|'SHORT'} posizioni aperte.

        Restituisce le decisioni (CLOSE prima di OPEN, cosi' l'engine libera margine).
        """
        cfg = self.cfg
        valid = {
            s: f for s, f in feats.items()
            if f is not None and cfg.min_atr_pct <= f.atr_pct <= cfg.max_atr_pct
        }
        # classifica per momentum: rank 1 = piu' forte; rank inverso per gli short
        by_mom = sorted(valid.values(), key=lambda f: f.momentum, reverse=True)
        long_rank = {f.sym: i + 1 for i, f in enumerate(by_mom)}
        short_rank = {f.sym: i + 1 for i, f in enumerate(reversed(by_mom))}

        decisions: list[Decision] = []

        # --- uscite (sempre valutate, anche in de-risking)
        for sym, side in held.items():
            f = feats.get(sym)
            if f is None:
                continue  # niente dati: lascia agire il trailing stop dell'engine
            if side == "LONG":
                broken = not f.trend_up
                ranked_out = long_rank.get(sym, 10**6) > cfg.exit_rank
            else:
                broken = not f.trend_down
                ranked_out = short_rank.get(sym, 10**6) > cfg.exit_rank
            if broken or ranked_out:
                why = "trend rotto" if broken else f"fuori dai top {cfg.exit_rank}"
                decisions.append(Decision(sym, "CLOSE", side, why, f))

        closing = {d.sym for d in decisions}
        held_after = {s: side for s, side in held.items() if s not in closing}
        n_longs = sum(1 for v in held_after.values() if v == "LONG")
        n_shorts = sum(1 for v in held_after.values() if v == "SHORT")

        # --- entrate long: i piu' forti in trend up
        for f in by_mom[:cfg.entry_rank]:
            if n_longs >= cfg.max_longs:
                break
            if f.sym in held_after or f.sym in closing:
                continue
            if f.trend_up and f.momentum >= cfg.min_abs_momentum:
                decisions.append(Decision(f.sym, "OPEN", "LONG",
                                          f"momentum rank {long_rank[f.sym]}", f))
                n_longs += 1

        # --- entrate short: i piu' deboli in trend down
        if cfg.allow_short:
            for f in list(reversed(by_mom))[:cfg.entry_rank]:
                if n_shorts >= cfg.max_shorts:
                    break
                if f.sym in held_after or f.sym in closing:
                    continue
                if f.trend_down and f.momentum <= -cfg.min_abs_momentum:
                    decisions.append(Decision(f.sym, "OPEN", "SHORT",
                                              f"momentum rank -{short_rank[f.sym]}", f))
                    n_shorts += 1

        return decisions

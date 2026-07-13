"""Risk management: la priorita' assoluta della gara.

La competizione SQUALIFICA a Max Drawdown storico > 20%. Questo modulo tiene
il bot molto lontano da quella soglia con tre livelli progressivi:

  WARN      (default  8% dd): dimezza la size delle nuove posizioni
  SOFT_KILL (default 12% dd): vieta nuove posizioni (solo gestione/uscite)
  HARD_KILL (default 15% dd): chiude tutto e ferma il trading (serve reset manuale)

Il sizing e' vol-targeted: si rischia una frazione fissa di equity per trade
alla distanza dello stop ATR, con cap sul nozionale singolo e sull'esposizione
lorda totale (sotto il limite di leva 2x della gara).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import RiskCfg

log = logging.getLogger(__name__)

NORMAL = "NORMAL"
WARN = "WARN"
SOFT_KILL = "SOFT_KILL"
HARD_KILL = "HARD_KILL"


@dataclass
class SizingInput:
    equity: float
    price: float
    atr: float
    gross_notional_open: float   # somma |qty*price| delle posizioni gia' aperte
    multiplier: float = 1.0      # es. moltiplicatore dell'AI advisor (0..1)


class RiskManager:
    def __init__(self, cfg: RiskCfg, hwm: float = 0.0, hard_killed: bool = False):
        self.cfg = cfg
        self.hwm = hwm
        self.hard_killed = hard_killed

    # ------------------------------------------------------------- drawdown

    def update_equity(self, equity: float) -> str:
        """Aggiorna high-water mark e restituisce il livello di rischio corrente."""
        if equity > self.hwm:
            self.hwm = equity
        level = self.level(equity)
        if level == HARD_KILL and not self.hard_killed:
            self.hard_killed = True
            log.critical("HARD KILL: drawdown %.2f%% >= %.2f%% — chiusura totale",
                         self.drawdown(equity) * 100, self.cfg.hard_kill_drawdown * 100)
        return level

    def drawdown(self, equity: float) -> float:
        if self.hwm <= 0:
            return 0.0
        return max(0.0, 1.0 - equity / self.hwm)

    def level(self, equity: float) -> str:
        if self.hard_killed:
            return HARD_KILL
        dd = self.drawdown(equity)
        if dd >= self.cfg.hard_kill_drawdown:
            return HARD_KILL
        if dd >= self.cfg.soft_kill_drawdown:
            return SOFT_KILL
        if dd >= self.cfg.warn_drawdown:
            return WARN
        return NORMAL

    def can_open(self, equity: float) -> bool:
        return self.level(equity) in (NORMAL, WARN)

    def reset_kill(self) -> None:
        """Reset manuale del kill switch (comando CLI, da usare con giudizio)."""
        self.hard_killed = False

    # --------------------------------------------------------------- sizing

    def position_qty(self, s: SizingInput) -> float:
        """Quantita' (in base asset) per una nuova posizione. 0 se non consentita."""
        if s.equity <= 0 or s.price <= 0 or s.atr <= 0:
            return 0.0
        if not self.can_open(s.equity):
            return 0.0

        mult = max(0.0, min(1.0, s.multiplier))
        if self.level(s.equity) == WARN:
            mult *= 0.5

        # rischio fisso per trade alla distanza dello stop
        stop_dist = self.cfg.stop_atr_mult * s.atr
        qty_risk = s.equity * self.cfg.risk_per_trade * mult / stop_dist

        # cap nozionale singola posizione
        qty_cap_single = self.cfg.max_position_notional_pct * s.equity / s.price

        # cap esposizione lorda complessiva
        gross_room = self.cfg.max_gross_leverage * s.equity - s.gross_notional_open
        if gross_room <= 0:
            return 0.0
        qty_cap_gross = gross_room / s.price

        return max(0.0, min(qty_risk, qty_cap_single, qty_cap_gross))

    # ------------------------------------------------------- trailing stops

    def initial_stop(self, side: str, entry_price: float, atr: float) -> float:
        d = self.cfg.stop_atr_mult * atr
        return entry_price - d if side == "LONG" else entry_price + d

    def trail_stop(self, side: str, best_price: float, atr: float, current_stop: float) -> float:
        """Lo stop segue il prezzo migliore raggiunto, senza mai arretrare."""
        d = self.cfg.stop_atr_mult * atr
        if side == "LONG":
            return max(current_stop, best_price - d)
        return min(current_stop, best_price + d)

    @staticmethod
    def stop_hit(side: str, price: float, stop: float) -> bool:
        return price <= stop if side == "LONG" else price >= stop

    # ---------------------------------------------------------- persistenza

    def to_dict(self) -> dict:
        return {"hwm": self.hwm, "hard_killed": self.hard_killed}

    @classmethod
    def from_dict(cls, cfg: RiskCfg, d: dict | None) -> "RiskManager":
        d = d or {}
        return cls(cfg, hwm=float(d.get("hwm", 0.0)), hard_killed=bool(d.get("hard_killed", False)))

"""Risk management: la priorita' assoluta della gara.

Le due fasi della competizione usano regole di liquidazione DIVERSE, non solo
soglie diverse — vanno tenute distinte, non solo riparametrizzate:

  Fase I  (regolamento: squalifica a MDD storico > 20%): drawdown percentuale
          dal massimo storico (high-water mark). Tre livelli progressivi:
            WARN      (default  8% dd): dimezza la size delle nuove posizioni
            SOFT_KILL (default 12% dd): vieta nuove posizioni (solo uscite)
            HARD_KILL (default 15% dd): chiude tutto, ferma il trading

  Fase II (regolamento: liquidazione forzata a equity<800U / NAV<0.8): un
          PAVIMENTO FISSO di equity, non un drawdown dal massimo storico — se
          l'equity sale a 1200 e poi scende del 20% a 960, la Fase I ti
          eliminerebbe (960 sotto la soglia MDD) ma la Fase II no (960 > 800).
          Stessi tre livelli, stesso principio (margine di sicurezza PRIMA
          della soglia reale di eliminazione), ma ancorati a valori assoluti
          di equity invece che a percentuali dal picco:
            WARN      (default equity < 900): dimezza la size delle nuove posizioni
            SOFT_KILL (default equity < 850): vieta nuove posizioni
            HARD_KILL (default equity < 800): chiude tutto, ferma il trading
            [regola ufficiale Fase II, non un margine di sicurezza]

`risk.phase` in config.yaml seleziona il regime (1 o 2) — va cambiato a mano
quando l'organizzatore annuncia il passaggio alla Fase II, non e' rilevato
automaticamente dal bot. Il resto (sizing vol-targeted, cap nozionale/leva,
trailing stop) e' identico in entrambe le fasi.
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
        """Aggiorna high-water mark e restituisce il livello di rischio corrente.

        L'high-water mark viene tracciato in entrambe le fasi (utile per
        display/diagnostica) ma e' USATO per la decisione di kill-switch solo
        in Fase I: in Fase II la soglia e' un pavimento fisso di equity."""
        if equity > self.hwm:
            self.hwm = equity
        level = self.level(equity)
        if level == HARD_KILL and not self.hard_killed:
            self.hard_killed = True
            if self.cfg.phase == 2:
                log.critical("HARD KILL (Fase II): equity %.2f < soglia %.2f — chiusura totale",
                             equity, self.cfg.phase2_hard_kill_equity)
            else:
                log.critical("HARD KILL (Fase I): drawdown %.2f%% >= %.2f%% — chiusura totale",
                             self.drawdown(equity) * 100, self.cfg.hard_kill_drawdown * 100)
        return level

    def drawdown(self, equity: float) -> float:
        """Drawdown % dal massimo storico. Ha senso solo come metrica Fase I
        (la Fase II usa un pavimento fisso, vedi _level_phase2)."""
        if self.hwm <= 0:
            return 0.0
        return max(0.0, 1.0 - equity / self.hwm)

    def level(self, equity: float) -> str:
        if self.hard_killed:
            return HARD_KILL
        if self.cfg.phase == 2:
            return self._level_phase2(equity)
        return self._level_phase1(equity)

    def _level_phase1(self, equity: float) -> str:
        dd = self.drawdown(equity)
        if dd >= self.cfg.hard_kill_drawdown:
            return HARD_KILL
        if dd >= self.cfg.soft_kill_drawdown:
            return SOFT_KILL
        if dd >= self.cfg.warn_drawdown:
            return WARN
        return NORMAL

    def _level_phase2(self, equity: float) -> str:
        """Regola ufficiale: eliminazione a equity < phase2_hard_kill_equity
        (default 800, cioe' NAV<0.8 su un capitale iniziale di 1000). WARN e
        SOFT_KILL sono margini di sicurezza PRIMA di quella soglia reale,
        stesso principio della Fase I ma ancorato a valori assoluti invece
        che a un drawdown percentuale dal picco."""
        if equity < self.cfg.phase2_hard_kill_equity:
            return HARD_KILL
        if equity < self.cfg.phase2_soft_kill_equity:
            return SOFT_KILL
        if equity < self.cfg.phase2_warn_equity:
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

"""Paper broker: simula i fill in locale su prezzi reali.

Modello a margine (perpetual): l'apertura non muove il cash (solo fee),
la chiusura realizza il PnL. equity = cash + PnL non realizzato ai mark.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import ExecutionCfg
from .base import Broker, BrokerPosition, Fill

log = logging.getLogger(__name__)


@dataclass
class _Pos:
    side: str
    qty: float
    entry: float


class PaperBroker(Broker):
    def __init__(self, exec_cfg: ExecutionCfg, starting_cash: float = 1000.0):
        self.cfg = exec_cfg
        self.cash = starting_cash
        self.positions: dict[str, _Pos] = {}
        self.marks: dict[str, float] = {}

    # -------------------------------------------------------------- helpers

    @property
    def _fee_rate(self) -> float:
        return self.cfg.paper_fee_bps / 10_000.0

    @property
    def _slip(self) -> float:
        return self.cfg.paper_slippage_bps / 10_000.0

    def update_marks(self, marks: dict[str, float]) -> None:
        self.marks.update(marks)

    def _unrealized(self, p: _Pos, mark: float) -> float:
        d = mark - p.entry
        return d * p.qty if p.side == "LONG" else -d * p.qty

    # ------------------------------------------------------------ interface

    def get_equity(self) -> float:
        eq = self.cash
        for sym, p in self.positions.items():
            mark = self.marks.get(sym, p.entry)
            eq += self._unrealized(p, mark)
        return eq

    def get_positions(self) -> dict[str, BrokerPosition]:
        return {s: BrokerPosition(s, p.side, p.qty, p.entry)
                for s, p in self.positions.items()}

    def open_position(self, sym: str, side: str, qty: float, ref_price: float) -> Fill | None:
        if qty <= 0 or ref_price <= 0 or sym in self.positions:
            return None
        # comprare (LONG) o vendere (SHORT) paga lo spread: slippage sfavorevole
        price = ref_price * (1 + self._slip) if side == "LONG" else ref_price * (1 - self._slip)
        fee = qty * price * self._fee_rate
        self.cash -= fee
        self.positions[sym] = _Pos(side, qty, price)
        self.marks[sym] = ref_price
        return Fill(sym, side, "OPEN", qty, price, fee)

    def close_position(self, sym: str, side: str, ref_price: float) -> Fill | None:
        p = self.positions.get(sym)
        if p is None:
            return None
        price = ref_price * (1 - self._slip) if p.side == "LONG" else ref_price * (1 + self._slip)
        pnl = self._unrealized(p, price)
        fee = p.qty * price * self._fee_rate
        self.cash += pnl - fee
        del self.positions[sym]
        return Fill(sym, p.side, "CLOSE", p.qty, price, fee, realized_pnl=pnl - fee)

    def flatten_all(self, ref_prices: dict[str, float]) -> None:
        for sym in list(self.positions):
            ref = ref_prices.get(sym) or self.marks.get(sym) or self.positions[sym].entry
            self.close_position(sym, self.positions[sym].side, ref)

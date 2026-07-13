"""Stato locale del bot: posizioni (con stop), risk state, budget AI, trade log.

Lo stato viene salvato su JSON a ogni ciclo (scrittura atomica) cosi' un
riavvio riparte esattamente da dove era rimasto: requisito pratico per
l'uptime >= 90% richiesto dalla gara. In modalita' live le POSIZIONI vere
vengono comunque riconciliate dall'API a ogni avvio; qui teniamo cio' che
l'exchange non conosce (stop, best price, timestamp ingresso).
"""
from __future__ import annotations

import csv
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Position:
    sym: str
    side: str            # LONG | SHORT
    qty: float
    entry_price: float
    best_price: float    # prezzo piu' favorevole visto dall'ingresso (per il trailing)
    stop_price: float
    atr_at_entry: float
    opened_at: float     # epoch seconds


@dataclass
class AiBudget:
    day: str = ""              # "YYYY-MM-DD" UTC
    calls_today: int = 0
    last_call_ts: float = 0.0
    risk_multiplier: float = 1.0
    last_comment: str = ""


@dataclass
class State:
    equity: float = 0.0
    paper_cash: float = 0.0     # cash del paper broker (per riprendere dopo un riavvio)
    positions: dict[str, Position] = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    ai: AiBudget = field(default_factory=AiBudget)
    last_signal_bar_ms: int = 0
    updated_at: float = 0.0


class Store:
    def __init__(self, state_file: Path, trades_file: Path):
        self.state_file = Path(state_file)
        self.trades_file = Path(trades_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.trades_file.parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- state

    def load(self) -> State:
        if not self.state_file.exists():
            return State()
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            positions = {s: Position(**p) for s, p in raw.get("positions", {}).items()}
            return State(
                equity=raw.get("equity", 0.0),
                paper_cash=raw.get("paper_cash", 0.0),
                positions=positions,
                risk=raw.get("risk", {}),
                ai=AiBudget(**raw.get("ai", {})),
                last_signal_bar_ms=raw.get("last_signal_bar_ms", 0),
                updated_at=raw.get("updated_at", 0.0),
            )
        except Exception as exc:
            log.error("Stato corrotto (%s): riparto da zero", exc)
            return State()

    def save(self, state: State) -> None:
        state.updated_at = time.time()
        payload = {
            "equity": state.equity,
            "paper_cash": state.paper_cash,
            "positions": {s: asdict(p) for s, p in state.positions.items()},
            "risk": state.risk,
            "ai": asdict(state.ai),
            "last_signal_bar_ms": state.last_signal_bar_ms,
            "updated_at": state.updated_at,
        }
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_file)

    # ------------------------------------------------------------ trade log

    TRADE_FIELDS = ["ts", "iso", "mode", "sym", "action", "side", "qty",
                    "price", "fee", "pnl", "reason"]

    def log_trade(self, mode: str, sym: str, action: str, side: str, qty: float,
                  price: float, fee: float, pnl: float, reason: str) -> None:
        new = not self.trades_file.exists()
        with self.trades_file.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.TRADE_FIELDS)
            if new:
                w.writeheader()
            now = time.time()
            w.writerow({
                "ts": f"{now:.0f}",
                "iso": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)),
                "mode": mode, "sym": sym, "action": action, "side": side,
                "qty": f"{qty:.10g}", "price": f"{price:.10g}",
                "fee": f"{fee:.6f}", "pnl": f"{pnl:.6f}", "reason": reason,
            })

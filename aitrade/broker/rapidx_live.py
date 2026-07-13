"""Broker live su RapidX.

Disciplina imposta dalle regole di gara:
  - ordini distanziati automaticamente dal rate limiter (1 scrittura / 5 s);
  - dopo OGNI scrittura si interroga lo stato (ordine/posizione) — mai
    dedurre il successo senza conferma, mai ritentare alla cieca;
  - leva impostata al valore di config (cap gara: 2x) prima del primo ordine
    su ciascun simbolo.

NOTA: i nomi dei campi nelle risposte (equity, posizioni, regole simbolo) sono
parsati in modo difensivo con piu' alias perche' i docs non mostrano i payload
completi: da VERIFICARE sul portfolio di test prima del 18 luglio (vedi README).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..config import ExecutionCfg, RiskCfg
from ..rapidx.rest import AmbiguousWriteError, RapidXClient, RapidXError
from .base import Broker, BrokerPosition, Fill

log = logging.getLogger(__name__)

FILLED_STATES = {"FILLED"}
DONE_STATES = {"FILLED", "CANCELLED", "REJECTED"}


def _fnum(d: dict, *keys: str, default: float = 0.0) -> float:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _fstr(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _as_list(data: Any) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("list", "rows", "items", "data", "positions"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
        return [data]
    return []


@dataclass
class SymbolRules:
    lot_size: float = 0.0     # step della quantita'
    tick_size: float = 0.0    # step del prezzo
    min_notional: float = 0.0


class RapidXBroker(Broker):
    def __init__(self, client: RapidXClient, exec_cfg: ExecutionCfg, risk_cfg: RiskCfg):
        self.client = client
        self.cfg = exec_cfg
        self.risk_cfg = risk_cfg
        self._rules: dict[str, SymbolRules] = {}
        self._leverage_set: set[str] = set()

    # -------------------------------------------------------- regole simbolo

    def load_symbol_rules(self) -> None:
        try:
            for item in _as_list(self.client.get_symbol_info()):
                sym = _fstr(item, "sym", "symbol")
                if not sym:
                    continue
                self._rules[sym] = SymbolRules(
                    lot_size=_fnum(item, "lotSize", "lotSz", "stepSize", "qtyStep"),
                    tick_size=_fnum(item, "tickSize", "tickSz", "priceStep"),
                    min_notional=_fnum(item, "minNotional", "minNotionalValue", "minOrderValue"),
                )
            log.info("Regole caricate per %d simboli", len(self._rules))
        except Exception as exc:
            log.warning("Regole simbolo non disponibili (%s): arrotondamenti di default", exc)

    @staticmethod
    def _round_step(value: float, step: float) -> float:
        if step <= 0:
            return value
        return int(value / step) * step

    def round_qty(self, sym: str, qty: float) -> float:
        return self._round_step(qty, self._rules.get(sym, SymbolRules()).lot_size)

    def round_price(self, sym: str, price: float) -> float:
        step = self._rules.get(sym, SymbolRules()).tick_size
        return self._round_step(price, step) if step > 0 else price

    def meets_min_notional(self, sym: str, qty: float, price: float) -> bool:
        mn = self._rules.get(sym, SymbolRules()).min_notional
        return qty * price >= mn if mn > 0 else qty > 0

    # -------------------------------------------------------------- leverage

    def prepare_symbol(self, sym: str) -> None:
        if sym in self._leverage_set:
            return
        try:
            self.client.set_leverage(sym, self.risk_cfg.leverage)
            self._leverage_set.add(sym)
            log.info("Leva %dx impostata su %s", self.risk_cfg.leverage, sym)
        except (RapidXError, AmbiguousWriteError) as exc:
            log.warning("set_leverage %s fallita: %s", sym, exc)

    # ------------------------------------------------------- account/position

    def get_equity(self) -> float:
        data = self.client.get_account()
        total = 0.0
        for acct in _as_list(data):
            eq = _fnum(acct, "totalEquity", "equity", "accountEquity",
                       "marginBalance", "netAsset", "balance")
            total += eq
        if total <= 0:
            log.warning("Equity non riconosciuta dalla risposta account: %s", str(data)[:400])
        return total

    def get_positions(self) -> dict[str, BrokerPosition]:
        out: dict[str, BrokerPosition] = {}
        for p in _as_list(self.client.get_positions()):
            sym = _fstr(p, "sym", "symbol")
            qty = abs(_fnum(p, "positionQty", "qty", "positionAmt", "volume", "size"))
            if not sym or qty == 0:
                continue
            side = _fstr(p, "positionSide", "posSide").upper() or "LONG"
            entry = _fnum(p, "entryPrice", "avgEntryPrice", "avgPrice", "openPrice")
            out[sym] = BrokerPosition(sym, side, qty, entry)
        return out

    def get_mark_prices(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for m in _as_list(self.client.get_mark_price()):
            sym = _fstr(m, "sym", "symbol")
            price = _fnum(m, "markPrice", "price", "markPx")
            if sym and price > 0:
                out[sym] = price
        return out

    # ----------------------------------------------------------------- ordini

    def open_position(self, sym: str, side: str, qty: float, ref_price: float) -> Fill | None:
        self.prepare_symbol(sym)
        qty = self.round_qty(sym, qty)
        if qty <= 0 or not self.meets_min_notional(sym, qty, ref_price):
            log.info("Ordine %s %s scartato: qty %.10g sotto i minimi", sym, side, qty)
            return None

        order_side = "BUY" if side == "LONG" else "SELL"
        slip = self.cfg.slippage_tolerance_bps / 10_000.0
        remaining = qty
        filled_qty = 0.0
        filled_value = 0.0

        for attempt in range(1, self.cfg.max_order_attempts + 1):
            use_market = (self.cfg.order_style == "market"
                          or attempt == self.cfg.max_order_attempts)
            limit_price = None
            if not use_market:
                px = ref_price * (1 + slip) if order_side == "BUY" else ref_price * (1 - slip)
                limit_price = f"{self.round_price(sym, px):.10g}"

            client_oid = f"at-{uuid.uuid4().hex[:16]}"
            try:
                self.client.place_order(
                    sym=sym, side=order_side, position_side=side,
                    order_type="MARKET" if use_market else "LIMIT",
                    order_qty=f"{self.round_qty(sym, remaining):.10g}",
                    limit_price=limit_price,
                    time_in_force=None if use_market else "IOC",
                    client_order_id=client_oid,
                )
            except AmbiguousWriteError:
                log.warning("Esito ordine %s ignoto: riconcilio via clientOrderId", client_oid)
            except RapidXError as exc:
                log.error("Ordine %s %s rifiutato: %s", sym, side, exc)
                break

            order = self._confirm_order(sym, client_oid)
            if order:
                exec_qty = _fnum(order, "executedQty", "cumQty", "filledQty")
                exec_px = _fnum(order, "executedAvgPrice", "avgPrice", "avgPx",
                                default=ref_price)
                filled_qty += exec_qty
                filled_value += exec_qty * exec_px
                remaining = self.round_qty(sym, qty - filled_qty)
            if remaining <= 0 or not self.meets_min_notional(sym, remaining, ref_price):
                break

        if filled_qty <= 0:
            return None
        avg = filled_value / filled_qty if filled_qty else ref_price
        return Fill(sym, side, "OPEN", filled_qty, avg, fee=0.0)

    def _confirm_order(self, sym: str, client_oid: str) -> dict | None:
        """Regola di gara: confermare lo stato dopo ogni scrittura."""
        for _ in range(5):
            try:
                data = self.client.get_order(sym=sym, client_order_id=client_oid)
                items = _as_list(data)
                if items:
                    order = items[0]
                    if _fstr(order, "orderState", "status", "state").upper() in DONE_STATES:
                        return order
            except RapidXError as exc:
                if str(getattr(exc, "code", "")) == "401018":  # ordine mai arrivato
                    return None
                log.warning("Query ordine %s: %s", client_oid, exc)
            time.sleep(1.5)
        return None

    def close_position(self, sym: str, side: str, ref_price: float) -> Fill | None:
        before = self.get_positions().get(sym)
        if before is None:
            return None
        try:
            self.client.close_position(sym, side)
        except AmbiguousWriteError:
            log.warning("Esito chiusura %s ignoto: verifico la posizione", sym)
        except RapidXError as exc:
            log.error("Chiusura %s fallita: %s", sym, exc)
            return None

        for _ in range(5):
            time.sleep(1.5)
            if sym not in self.get_positions():
                return Fill(sym, side, "CLOSE", before.qty, ref_price, fee=0.0)
        log.error("Posizione %s ancora aperta dopo la richiesta di chiusura", sym)
        return None

    def flatten_all(self, ref_prices: dict[str, float]) -> None:
        try:
            self.client.cancel_all()
        except Exception as exc:
            log.warning("cancelAll fallita: %s", exc)
        try:
            self.client.close_all_positions()
        except Exception as exc:
            log.error("closeAllPositions fallita: %s — provo chiusure singole", exc)
            for sym, pos in self.get_positions().items():
                self.close_position(sym, pos.side, ref_prices.get(sym, pos.entry_price))

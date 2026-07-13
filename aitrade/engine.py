"""Engine: il loop principale del bot (paper e live condividono tutto tranne il broker).

Ogni `manage_interval_sec` (default 60s):
  1. aggiorna i prezzi e l'equity -> livello di rischio (drawdown);
  2. HARD_KILL? chiudi tutto e resta fermo (protezione squalifica al 20% MDD);
  3. trailing stop: aggiorna e chiudi le posizioni colpite;
  4. se e' appena chiusa una candela del timeframe: scarica le klines
     dell'universo, calcola i segnali e riallinea il portafoglio;
  5. salva lo stato e logga l'heartbeat (evidenza di uptime).

Il loop non muore mai per un'eccezione: logga e riprova al giro dopo.
"""
from __future__ import annotations

import logging
import time

from . import symbols
from .ai.advisor import Advisor
from .ai.news import recent_headlines
from .broker.base import Broker, Fill
from .broker.paper import PaperBroker
from .broker.rapidx_live import RapidXBroker
from .config import Config
from .data.klines import KlineService, interval_ms
from .portfolio import Position, State, Store
from .rapidx.rest import RapidXClient
from .risk import HARD_KILL, RiskManager, SizingInput
from .strategy.momentum import Features, MomentumStrategy

log = logging.getLogger(__name__)

STARTING_CASH = 1000.0  # capitale iniziale della gara


class Engine:
    def __init__(self, cfg: Config, mode: str | None = None):
        self.cfg = cfg
        self.mode = mode or cfg.mode
        self.live = self.mode == "live"
        self.universe = symbols.universe(cfg.exclude)
        self.step_ms = interval_ms(cfg.timeframe)

        self.store = Store(cfg.resolve(cfg.paths.state_file), cfg.resolve(cfg.paths.trades_file))
        self.state: State = self.store.load()
        self.risk = RiskManager.from_dict(cfg.risk, self.state.risk)
        self.strategy = MomentumStrategy(cfg.strategy)
        self.advisor = Advisor(cfg.ai)

        self.client: RapidXClient | None = None
        if self.live:
            self.client = RapidXClient(cfg.rapidx.access_key, cfg.rapidx.secret_key,
                                       cfg.rapidx.api_host)
            self.broker: Broker = RapidXBroker(self.client, cfg.execution, cfg.risk)
        else:
            self.broker = PaperBroker(cfg.execution, starting_cash=STARTING_CASH)

        self.data = KlineService(
            cfg.resolve(cfg.data.cache_dir), rapidx_client=self.client,
            rapidx_klines_path=cfg.rapidx.klines_path,
        )
        self._last_feats: dict[str, Features] = {}

    # ------------------------------------------------------------- startup

    def startup(self) -> None:
        if self.live:
            self.broker.load_symbol_rules()
            self._reconcile_live_positions()
        else:
            self._restore_paper()
        equity = self._safe_equity()
        if equity > 0:
            self.risk.update_equity(equity)
        log.info("Cephelo_AITrader avviato in modalita' %s | equity=%.2f | posizioni=%d | universo=%d simboli",
                 self.mode.upper(), equity, len(self.state.positions), len(self.universe))

    def _restore_paper(self) -> None:
        from .broker.paper import _Pos
        broker: PaperBroker = self.broker  # type: ignore[assignment]
        if self.state.paper_cash > 0 or self.state.positions:
            broker.cash = self.state.paper_cash or STARTING_CASH
            broker.positions = {
                sym: _Pos(p.side, p.qty, p.entry_price)
                for sym, p in self.state.positions.items()
            }
            log.info("Paper trading ripristinato: cash=%.2f, %d posizioni",
                     broker.cash, len(broker.positions))

    def _reconcile_live_positions(self) -> None:
        """Le posizioni vere sono quelle dell'exchange; lo stato locale si adegua."""
        try:
            exchange_pos = self.broker.get_positions()
        except Exception as exc:
            log.error("Riconciliazione posizioni fallita: %s (mantengo lo stato locale)", exc)
            return
        for sym in list(self.state.positions):
            if sym not in exchange_pos:
                log.warning("Posizione %s nello stato locale ma non sull'exchange: rimossa", sym)
                del self.state.positions[sym]
        for sym, bp in exchange_pos.items():
            if sym not in self.state.positions:
                atr_guess = bp.entry_price * 0.02  # in attesa del primo giro di segnali
                self.state.positions[sym] = Position(
                    sym=sym, side=bp.side, qty=bp.qty, entry_price=bp.entry_price,
                    best_price=bp.entry_price, atr_at_entry=atr_guess,
                    stop_price=self.risk.initial_stop(bp.side, bp.entry_price, atr_guess),
                    opened_at=time.time(),
                )
                log.warning("Posizione %s trovata sull'exchange: adottata con stop di emergenza", sym)

    # ---------------------------------------------------------------- loop

    def run_forever(self) -> None:
        self.startup()
        interval = self.cfg.loop.manage_interval_sec
        while True:
            t0 = time.time()
            try:
                self.tick()
            except Exception:
                log.exception("Errore nel tick (il bot continua)")
            time.sleep(max(1.0, interval - (time.time() - t0)))

    def tick(self) -> None:
        marks = self._refresh_marks()
        equity = self._safe_equity()
        level = self.risk.update_equity(equity) if equity > 0 else "N/A"
        dd = self.risk.drawdown(equity) if equity > 0 else 0.0

        if level == HARD_KILL:
            self._hard_kill(marks)
            self._persist(equity)
            log.critical("HALTED (hard kill). Riattivazione: python -m aitrade reset-kill")
            return

        self._manage_stops(marks)

        bar_ms = self._closed_bar_ready()
        if bar_ms is not None:
            self._signal_tick(bar_ms)
            equity = self._safe_equity()

        self._persist(equity)
        log.info("heartbeat | equity=%.2f dd=%.2f%% level=%s pos=%d ai_mult=%.2f",
                 equity, dd * 100, level, len(self.state.positions),
                 self.state.ai.risk_multiplier)

    # -------------------------------------------------------------- prezzi

    def _refresh_marks(self) -> dict[str, float]:
        marks: dict[str, float] = {}
        if self.live:
            try:
                marks = self.broker.get_mark_prices()  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("Mark price non disponibili: %s", exc)
        else:
            for sym in list(self.state.positions):
                try:
                    df = self.data.fetch(sym, "1m", 2)
                    if not df.empty:
                        marks[sym] = float(df.iloc[-1]["close"])
                except Exception as exc:
                    log.warning("Prezzo %s non disponibile: %s", sym, exc)
            broker: PaperBroker = self.broker  # type: ignore[assignment]
            broker.update_marks(marks)
        return marks

    def _safe_equity(self) -> float:
        try:
            eq = self.broker.get_equity()
            if eq > 0:
                self.state.equity = eq
        except Exception as exc:
            log.warning("Equity non disponibile: %s (uso ultimo valore %.2f)",
                        exc, self.state.equity)
        return self.state.equity

    # ---------------------------------------------------------------- stop

    def _manage_stops(self, marks: dict[str, float]) -> None:
        for sym, pos in list(self.state.positions.items()):
            price = marks.get(sym)
            if not price:
                continue
            if pos.side == "LONG":
                pos.best_price = max(pos.best_price, price)
            else:
                pos.best_price = min(pos.best_price, price)
            pos.stop_price = self.risk.trail_stop(pos.side, pos.best_price,
                                                  pos.atr_at_entry, pos.stop_price)
            if self.risk.stop_hit(pos.side, price, pos.stop_price):
                log.info("STOP %s %s @ %.6g (stop %.6g)", pos.side, sym, price, pos.stop_price)
                self._close(sym, pos, price, "trailing stop")

    # ------------------------------------------------------------- segnali

    def _closed_bar_ready(self) -> int | None:
        """Open (ms) dell'ultima candela chiusa, se nuova e oltre il grace period."""
        now_ms = int(time.time() * 1000)
        current_open = (now_ms // self.step_ms) * self.step_ms
        last_closed_open = current_open - self.step_ms
        if last_closed_open <= self.state.last_signal_bar_ms:
            return None
        if now_ms < current_open + self.cfg.loop.signal_grace_sec * 1000:
            return None
        return last_closed_open

    def _signal_tick(self, bar_ms: int) -> None:
        log.info("Nuova candela %s chiusa: calcolo segnali su %d simboli",
                 self.cfg.timeframe, len(self.universe))
        need = max(self.cfg.strategy.warmup_bars, self.cfg.strategy.ema_slow) + 10
        feats: dict[str, Features] = {}
        closes: dict[str, float] = {}
        for sym in self.universe:
            try:
                df = self.data.fetch(sym, self.cfg.timeframe, need)
                f = self.strategy.latest_features(sym, df)
                if f is not None:
                    feats[sym] = f
                    closes[sym] = f.close
            except Exception as exc:
                log.warning("Klines %s non disponibili: %s", sym, exc)
        self._last_feats = feats
        if not self.live:
            broker: PaperBroker = self.broker  # type: ignore[assignment]
            broker.update_marks(closes)

        self._maybe_ask_ai(feats)

        held = {sym: p.side for sym, p in self.state.positions.items()}
        decisions = self.strategy.decide(feats, held)
        equity = self._safe_equity()

        for d in [d for d in decisions if d.action == "CLOSE"]:
            pos = self.state.positions.get(d.sym)
            price = closes.get(d.sym, pos.best_price if pos else 0.0)
            if pos and price:
                self._close(d.sym, pos, price, d.reason)

        if not self.risk.can_open(equity):
            log.warning("Drawdown %.1f%%: nessuna nuova posizione (%s)",
                        self.risk.drawdown(equity) * 100, self.risk.level(equity))
        else:
            for d in [d for d in decisions if d.action == "OPEN"]:
                self._open(d.sym, d.side, d.features, d.reason)

        self.state.last_signal_bar_ms = bar_ms

    # ------------------------------------------------------------ operazioni

    def _gross_open_notional(self, marks: dict[str, float] | None = None) -> float:
        total = 0.0
        for sym, p in self.state.positions.items():
            price = (marks or {}).get(sym) or closes_or_entry(p)
            total += p.qty * price
        return total

    def _open(self, sym: str, side: str, f: Features | None, reason: str) -> None:
        if f is None:
            return
        equity = self.state.equity
        qty = self.risk.position_qty(SizingInput(
            equity=equity, price=f.close, atr=f.atr,
            gross_notional_open=self._gross_open_notional(),
            multiplier=self.state.ai.risk_multiplier,
        ))
        if qty <= 0:
            return
        try:
            fill: Fill | None = self.broker.open_position(sym, side, qty, f.close)
        except Exception as exc:
            log.error("Apertura %s %s fallita: %s", side, sym, exc)
            return
        if fill is None:
            return
        self.state.positions[sym] = Position(
            sym=sym, side=side, qty=fill.qty, entry_price=fill.price,
            best_price=fill.price, atr_at_entry=f.atr,
            stop_price=self.risk.initial_stop(side, fill.price, f.atr),
            opened_at=time.time(),
        )
        self.store.log_trade(self.mode, sym, "OPEN", side, fill.qty, fill.price,
                             fill.fee, 0.0, reason)
        log.info("OPEN %s %s qty=%.10g @ %.6g (%s)", side, sym, fill.qty, fill.price, reason)

    def _close(self, sym: str, pos: Position, ref_price: float, reason: str) -> None:
        try:
            fill = self.broker.close_position(sym, pos.side, ref_price)
        except Exception as exc:
            log.error("Chiusura %s fallita: %s", sym, exc)
            return
        if fill is None:
            # broker senza posizione: allinea lo stato locale
            self.state.positions.pop(sym, None)
            return
        pnl = fill.realized_pnl
        if self.live:  # stima locale: il PnL ufficiale lo calcola l'exchange
            d = fill.price - pos.entry_price
            pnl = d * pos.qty if pos.side == "LONG" else -d * pos.qty
        self.state.positions.pop(sym, None)
        self.store.log_trade(self.mode, sym, "CLOSE", pos.side, fill.qty, fill.price,
                             fill.fee, pnl, reason)
        log.info("CLOSE %s %s qty=%.10g @ %.6g pnl=%.2f (%s)",
                 pos.side, sym, fill.qty, fill.price, pnl, reason)

    def _hard_kill(self, marks: dict[str, float]) -> None:
        if self.state.positions:
            log.critical("HARD KILL: chiudo tutte le %d posizioni", len(self.state.positions))
            try:
                self.broker.flatten_all(marks)
            except Exception:
                log.exception("flatten_all fallita — RIPROVARE MANUALMENTE: python -m aitrade close-all")
            for sym, pos in list(self.state.positions.items()):
                price = marks.get(sym, pos.entry_price)
                d = price - pos.entry_price
                pnl = d * pos.qty if pos.side == "LONG" else -d * pos.qty
                self.store.log_trade(self.mode, sym, "CLOSE", pos.side, pos.qty,
                                     price, 0.0, pnl, "HARD KILL drawdown")
            self.state.positions.clear()

    # ----------------------------------------------------------------- ai

    def _maybe_ask_ai(self, feats: dict[str, Features]) -> None:
        if not self.advisor.should_call(self.state.ai):
            return
        ranked = sorted(feats.values(), key=lambda f: f.momentum, reverse=True)
        top = ", ".join(f"{symbols.to_base(f.sym)} {f.momentum:+.1%}" for f in ranked[:5])
        bottom = ", ".join(f"{symbols.to_base(f.sym)} {f.momentum:+.1%}" for f in ranked[-5:])
        pos = ", ".join(f"{p.side} {symbols.to_base(s)}" for s, p in self.state.positions.items()) or "none"
        snapshot = (f"equity={self.state.equity:.2f} USDT, drawdown={self.risk.drawdown(self.state.equity):.1%}, "
                    f"open positions: {pos}\nmomentum leaders: {top}\nmomentum laggards: {bottom}")
        headlines: list[str] = []
        if self.client is not None:
            headlines = recent_headlines(self.client, hours=24)
        self.advisor.assess(self.state.ai, snapshot, headlines)

    # ---------------------------------------------------------- persistenza

    def _persist(self, equity: float) -> None:
        self.state.equity = equity
        self.state.risk = self.risk.to_dict()
        if not self.live:
            broker: PaperBroker = self.broker  # type: ignore[assignment]
            self.state.paper_cash = broker.cash
        self.store.save(self.state)


def closes_or_entry(p: Position) -> float:
    return p.best_price or p.entry_price

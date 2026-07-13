"""CLI del bot.

  python -m aitrade run [--mode paper|live]   avvia il bot (loop infinito)
  python -m aitrade download-data [--bars N]  scarica lo storico 4h (cache)
  python -m aitrade backtest [--refresh]      backtest con le metriche di gara
  python -m aitrade status                    stato: equity, posizioni, drawdown
  python -m aitrade close-all --yes           EMERGENZA: chiude tutto
  python -m aitrade reset-kill                riattiva il bot dopo un hard kill
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import symbols
from .config import Config, load_config


def setup_logging(cfg: Config) -> None:
    log_file = cfg.resolve(cfg.paths.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    fileh = RotatingFileHandler(log_file, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    fileh.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(fileh)


def cmd_run(cfg: Config, args) -> int:
    from .engine import Engine
    mode = args.mode or cfg.mode
    if mode == "live" and not cfg.rapidx.access_key:
        print("ERRORE: modalita' live senza LTP_ACCESS_KEY/LTP_SECRET_KEY nel .env")
        return 1
    Engine(cfg, mode).run_forever()
    return 0


def cmd_download(cfg: Config, args) -> int:
    from .data.klines import KlineService
    svc = KlineService(cfg.resolve(cfg.data.cache_dir))
    universe = symbols.universe(cfg.exclude)
    bars = args.bars or cfg.data.history_bars
    print(f"Scarico {bars} barre {cfg.timeframe} per {len(universe)} simboli...")
    got = svc.download_history(universe, cfg.timeframe, bars)
    print(f"Fatto: {len(got)}/{len(universe)} simboli in cache ({cfg.data.cache_dir}/)")
    return 0


def cmd_backtest(cfg: Config, args) -> int:
    from .backtest import run_backtest
    from .data.klines import KlineService
    svc = KlineService(cfg.resolve(cfg.data.cache_dir))
    universe = symbols.universe(cfg.exclude)
    data = {} if args.refresh else svc.load_cached(universe, cfg.timeframe)
    if not data:
        print("Scarico lo storico...")
        data = svc.download_history(universe, cfg.timeframe, args.bars or cfg.data.history_bars)
    print(f"Backtest su {len(data)} simboli, timeframe {cfg.timeframe}...")
    result = run_backtest(cfg, data)
    print(result.report())
    out = cfg.resolve("logs/backtest_equity.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    result.equity_curve.rename("equity").to_csv(out, index_label="close_time_ms")
    print(f"Equity curve salvata in {out}")
    return 0


def cmd_status(cfg: Config, args) -> int:
    from .portfolio import Store
    store = Store(cfg.resolve(cfg.paths.state_file), cfg.resolve(cfg.paths.trades_file))
    st = store.load()
    hwm = st.risk.get("hwm", 0.0) or 0.0
    dd = (1 - st.equity / hwm) if hwm > 0 else 0.0
    print(f"Equity:      {st.equity:.2f} USDT (HWM {hwm:.2f}, drawdown {dd:.2%})")
    print(f"Hard killed: {st.risk.get('hard_killed', False)}")
    print(f"AI:          mult={st.ai.risk_multiplier:.2f} calls_oggi={st.ai.calls_today} "
          f"({st.ai.last_comment or 'nessuna valutazione'})")
    if st.positions:
        print("Posizioni:")
        for sym, p in st.positions.items():
            print(f"  {p.side:5s} {sym:28s} qty={p.qty:.10g} entry={p.entry_price:.6g} "
                  f"stop={p.stop_price:.6g}")
    else:
        print("Posizioni:   nessuna")
    return 0


def cmd_close_all(cfg: Config, args) -> int:
    if not args.yes:
        print("Chiude TUTTE le posizioni. Conferma con: python -m aitrade close-all --yes")
        return 1
    mode = args.mode or cfg.mode
    if mode == "live":
        from .broker.rapidx_live import RapidXBroker
        from .rapidx.rest import RapidXClient
        client = RapidXClient(cfg.rapidx.access_key, cfg.rapidx.secret_key, cfg.rapidx.api_host)
        broker = RapidXBroker(client, cfg.execution, cfg.risk)
        broker.flatten_all({})
        print("Richiesta di chiusura totale inviata. Verifica con: python -m aitrade status")
    from .portfolio import Store
    store = Store(cfg.resolve(cfg.paths.state_file), cfg.resolve(cfg.paths.trades_file))
    st = store.load()
    st.positions.clear()
    store.save(st)
    print("Stato locale ripulito.")
    return 0


def cmd_reset_kill(cfg: Config, args) -> int:
    from .portfolio import Store
    store = Store(cfg.resolve(cfg.paths.state_file), cfg.resolve(cfg.paths.trades_file))
    st = store.load()
    st.risk["hard_killed"] = False
    store.save(st)
    print("Kill switch resettato. ATTENZIONE: l'high-water mark resta invariato,")
    print("quindi il limite di drawdown continua a valere dai massimi storici.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aitrade",
        description="Cephelo_AITrader - bot per Liquidity Arena 2026 (Track A)")
    parser.add_argument("--root", default=None, help="cartella del progetto (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="avvia il bot")
    p_run.add_argument("--mode", choices=["paper", "live"], default=None)

    p_dl = sub.add_parser("download-data", help="scarica lo storico in cache")
    p_dl.add_argument("--bars", type=int, default=None)

    p_bt = sub.add_parser("backtest", help="backtest con metriche di gara")
    p_bt.add_argument("--bars", type=int, default=None)
    p_bt.add_argument("--refresh", action="store_true", help="riscarica lo storico")

    sub.add_parser("status", help="stato corrente")

    p_ca = sub.add_parser("close-all", help="EMERGENZA: chiudi tutte le posizioni")
    p_ca.add_argument("--yes", action="store_true")
    p_ca.add_argument("--mode", choices=["paper", "live"], default=None)

    sub.add_parser("reset-kill", help="riattiva dopo hard kill")

    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    cfg = load_config(root)
    setup_logging(cfg)

    commands = {
        "run": cmd_run,
        "download-data": cmd_download,
        "backtest": cmd_backtest,
        "status": cmd_status,
        "close-all": cmd_close_all,
        "reset-kill": cmd_reset_kill,
    }
    return commands[args.command](cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())

"""Bot Telegram "in ascolto": risponde con lo stato del portafoglio quando si
scrive "status" nella chat col bot, e manda in automatico un report esteso
(stato + riepilogo trade + errori/warning dal log) due volte al giorno (le
notifiche automatiche in uscita su SOFT_KILL/HARD_KILL restano separate,
vedi aitrade/alerts.py).

Processo indipendente dal bot di trading: se e' giu' o non parte, il trading
continua normalmente, si perde solo la possibilita' di chiedere lo stato via
Telegram - per questo gira come servizio a se stante, non dentro engine.py.
Per lo stesso motivo lo scheduling dei report non e' persistito su disco: se
il servizio riparte a cavallo di un orario di invio, quel report puo' essere
mandato di nuovo (o in ritardo) - non e' un problema per un report informativo.

Sicurezza: risponde SOLO ai messaggi provenienti dalla chat configurata in
TELEGRAM_CHAT_ID (.env). Chiunque altro scriva al bot viene ignorato in
silenzio, cosi' lo stato del portafoglio non e' esposto a chi trova il bot
per caso (es. lo username finisce in qualche indice pubblico di Telegram).

Uso: python -m aitrade.telegram_status_bot
"""
from __future__ import annotations

import csv
import logging
import re
import time
from pathlib import Path

import requests

from .alerts import TELEGRAM_API, send_telegram
from .config import load_config
from .portfolio import Store, format_status

log = logging.getLogger(__name__)

POLL_TIMEOUT_SEC = 30
ERROR_RETRY_SEC = 5
STATUS_COMMANDS = {"status", "/status"}

# Orari di invio del report automatico, ora locale della macchina dove gira
# il bot (di norma UTC su una VM cloud) - confrontati con time.localtime().
REPORT_SLOTS = [("mattina", 8, 0), ("sera", 20, 0)]
MAX_LOG_LINES_IN_REPORT = 15
LOG_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ (\w+)")


def _get_updates(token: str, offset: int | None) -> list[dict]:
    params: dict = {"timeout": POLL_TIMEOUT_SEC}
    if offset is not None:
        params["offset"] = offset
    resp = requests.get(f"{TELEGRAM_API}/bot{token}/getUpdates", params=params,
                         timeout=POLL_TIMEOUT_SEC + 5)
    resp.raise_for_status()
    return resp.json().get("result", [])


def _initial_offset(token: str) -> int | None:
    """Scarta gli update gia' presenti al momento dell'avvio (es. vecchi
    messaggi mai letti) cosi' un riavvio del servizio non risponde a un
    backlog di messaggi passati."""
    try:
        stale = _get_updates(token, None)
    except Exception as exc:
        log.warning("getUpdates iniziale fallito, riparto senza offset: %s", exc)
        return None
    return stale[-1]["update_id"] + 1 if stale else None


def handle_update(update: dict, chat_id: str, store: Store) -> str | None:
    """Ritorna il testo di risposta se l'update e' un comando "status"
    autorizzato, altrimenti None (nessuna risposta)."""
    msg = update.get("message") or {}
    sender_chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip().lower()
    if sender_chat_id != str(chat_id) or text not in STATUS_COMMANDS:
        return None
    return format_status(store.load())


def _trade_summary(trades_file: Path, since_ts: float) -> str:
    """Conta OPEN/CLOSE e somma il pnl delle chiusure in trades.csv dal
    timestamp since_ts (epoch) in poi."""
    if not trades_file.exists():
        return "Trade: nessuno"
    opens = closes = 0
    pnl_total = 0.0
    with trades_file.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts = float(row["ts"])
            except (KeyError, ValueError):
                continue
            if ts < since_ts:
                continue
            if row["action"] == "OPEN":
                opens += 1
            elif row["action"] == "CLOSE":
                closes += 1
                try:
                    pnl_total += float(row["pnl"])
                except ValueError:
                    pass
    if opens == 0 and closes == 0:
        return "Trade nel periodo: nessuno"
    return f"Trade nel periodo: {opens} aperti, {closes} chiusi, pnl chiusure={pnl_total:+.2f} USDT"


def _log_summary(log_file: Path, since_ts: float) -> str:
    """Estrae le righe ERROR/WARNING di logs/aitrade.log dal timestamp
    since_ts in poi (parsato dall'asctime di ogni riga)."""
    if not log_file.exists():
        return "Log: file non trovato"
    hits = []
    with log_file.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LOG_LINE_RE.match(line)
            if not m or m.group(2) not in ("ERROR", "WARNING"):
                continue
            try:
                ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue
            if ts >= since_ts:
                hits.append(line.rstrip())
    if not hits:
        return "Log: nessun errore/warning nel periodo"
    tail = hits[-MAX_LOG_LINES_IN_REPORT:]
    header = f"Log: {len(hits)} errori/warning nel periodo"
    if len(hits) > len(tail):
        header += f" (ultime {len(tail)})"
    return header + "\n" + "\n".join(tail)


def build_scheduled_report(store: Store, trades_file: Path, log_file: Path, since_ts: float) -> str:
    return "\n\n".join([
        format_status(store.load()),
        _trade_summary(trades_file, since_ts),
        _log_summary(log_file, since_ts),
    ])


def _due_slot(now: time.struct_time, already_sent_today: dict[str, str]) -> tuple[str, int, int] | None:
    """Ritorna lo slot (nome, ora, minuto) da inviare se l'orario e' passato
    e non e' ancora stato mandato oggi, altrimenti None."""
    today = time.strftime("%Y-%m-%d", now)
    for name, hh, mm in REPORT_SLOTS:
        if (now.tm_hour, now.tm_min) >= (hh, mm) and already_sent_today.get(name) != today:
            return name, hh, mm
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    token = cfg.risk.telegram_bot_token
    chat_id = cfg.risk.telegram_chat_id
    if not token or not chat_id:
        log.info("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID non configurati: nessun listener avviato.")
        return

    trades_file = cfg.resolve(cfg.paths.trades_file)
    log_file = cfg.resolve(cfg.paths.log_file)
    store = Store(cfg.resolve(cfg.paths.state_file), trades_file)
    offset = _initial_offset(token)
    log.info("Listener Telegram avviato (chat autorizzata: %s)", chat_id)

    report_sent_today: dict[str, str] = {}
    since_ts = time.time() - 12 * 3600  # alla primissima esecuzione: ultime 12h

    while True:
        try:
            updates = _get_updates(token, offset)
        except Exception as exc:
            log.warning("getUpdates fallito: %s", exc)
            time.sleep(ERROR_RETRY_SEC)
            continue
        for upd in updates:
            offset = upd["update_id"] + 1
            reply = handle_update(upd, chat_id, store)
            if reply is not None:
                send_telegram(token, chat_id, reply)

        due = _due_slot(time.localtime(), report_sent_today)
        if due is not None:
            name, hh, mm = due
            report = build_scheduled_report(store, trades_file, log_file, since_ts)
            send_telegram(token, chat_id, f"Report {name} ({hh:02d}:{mm:02d})\n\n{report}")
            report_sent_today[name] = time.strftime("%Y-%m-%d")
            since_ts = time.time()


if __name__ == "__main__":
    main()

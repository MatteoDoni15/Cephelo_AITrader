"""Bot Telegram "in ascolto": risponde con lo stato del portafoglio quando si
scrive "status" nella chat col bot (le notifiche automatiche in uscita su
SOFT_KILL/HARD_KILL restano separate, vedi aitrade/alerts.py).

Processo indipendente dal bot di trading: se e' giu' o non parte, il trading
continua normalmente, si perde solo la possibilita' di chiedere lo stato via
Telegram - per questo gira come servizio a se stante, non dentro engine.py.

Sicurezza: risponde SOLO ai messaggi provenienti dalla chat configurata in
TELEGRAM_CHAT_ID (.env). Chiunque altro scriva al bot viene ignorato in
silenzio, cosi' lo stato del portafoglio non e' esposto a chi trova il bot
per caso (es. lo username finisce in qualche indice pubblico di Telegram).

Uso: python -m aitrade.telegram_status_bot
"""
from __future__ import annotations

import logging
import time

import requests

from .alerts import TELEGRAM_API, send_telegram
from .config import load_config
from .portfolio import Store, format_status

log = logging.getLogger(__name__)

POLL_TIMEOUT_SEC = 30
ERROR_RETRY_SEC = 5
STATUS_COMMANDS = {"status", "/status"}


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    token = cfg.risk.telegram_bot_token
    chat_id = cfg.risk.telegram_chat_id
    if not token or not chat_id:
        log.info("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID non configurati: nessun listener avviato.")
        return

    store = Store(cfg.resolve(cfg.paths.state_file), cfg.resolve(cfg.paths.trades_file))
    offset = _initial_offset(token)
    log.info("Listener Telegram avviato (chat autorizzata: %s)", chat_id)

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


if __name__ == "__main__":
    main()

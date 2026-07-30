"""Notifica opzionale (webhook Discord/Slack e/o Telegram) quando il bot
entra in SOFT_KILL o HARD_KILL — altrimenti l'unico modo per accorgersene e'
controllare `status` a mano.

Opt-in indipendente per canale: se un canale non e' configurato, la funzione
corrispondente non fa nulla — nessuno dei due e' mai un requisito per il
funzionamento del bot, e puoi usarli anche insieme per ridondanza.

Fail-safe: un guasto nell'invio di una notifica non deve mai interrompere il
ciclo di trading che l'ha generata — per questo chi chiama queste funzioni
non deve mai vedersi propagare le loro eccezioni (gia' gestite qui dentro).
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

TIMEOUT_SEC = 10.0
TELEGRAM_API = "https://api.telegram.org"


def send_alert(webhook_url: str, message: str) -> None:
    """Webhook generico (Discord/Slack/altro). Il payload include sia "text"
    (Slack e molti webhook generici) sia "content" (Discord), cosi' funziona
    con entrambi senza bisogno di configurare il formato per provider."""
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json={"text": message, "content": message}, timeout=TIMEOUT_SEC)
    except Exception as exc:
        log.warning("Invio notifica webhook fallito: %s", exc)


def send_telegram(bot_token: str, chat_id: str, message: str) -> None:
    """Notifica via bot Telegram (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID nel
    .env). Vedi README per come creare il bot e trovare il proprio chat_id."""
    if not bot_token or not chat_id:
        return
    try:
        requests.post(
            f"{TELEGRAM_API}/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
            timeout=TIMEOUT_SEC,
        )
    except Exception as exc:
        log.warning("Invio notifica Telegram fallito: %s", exc)

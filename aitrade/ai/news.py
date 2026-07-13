"""News feed della piattaforma (api.ltp-contest.com/api/v1/feeds/*).

Usato come contesto per l'AI advisor: titoli delle ultime ore, gia' filtrati
dalla piattaforma. Retention: news 15 giorni, hot 7 giorni.
"""
from __future__ import annotations

import logging
import re
import time

from ..rapidx.rest import RapidXClient

log = logging.getLogger(__name__)

_TAG = re.compile(r"<[^>]+>")


def _clean(text: str, max_len: int = 200) -> str:
    return _TAG.sub("", text or "").strip()[:max_len]


def recent_headlines(client: RapidXClient, hours: int = 24, max_items: int = 25) -> list[str]:
    """Titoli recenti (hot + news), dal piu' nuovo. Best effort: [] se il feed non risponde."""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - hours * 3_600_000
    heads: list[str] = []
    for fetch in (client.query_hot, client.query_news):
        try:
            data = fetch(start_ms, end_ms, page_size=max_items) or {}
            for item in data.get("list", []) or []:
                title = _clean(item.get("title") or item.get("content") or "")
                if title:
                    heads.append(title)
        except Exception as exc:
            log.warning("News feed non disponibile: %s", exc)
    seen: set[str] = set()
    unique = [h for h in heads if not (h in seen or seen.add(h))]
    return unique[:max_items]

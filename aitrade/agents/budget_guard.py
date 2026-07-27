"""Controllo del budget reale dell'AI Gateway, prima di spendere una chiamata.

`max_calls_per_day`/`interval_hours` (vedi ai/advisor.py) limitano quante
VOLTE si prova a chiamare il modello, ma non sanno nulla della spesa reale in
dollari: non vedono i retry sullo schema (ogni retry e' un'altra chiamata a
pagamento), ne' le chiamate fatte da altri membri del team sulla stessa
chiave condivisa. L'unica fonte di verita' sulla spesa e' l'endpoint
dell'organizzatore:

    GET {base_url}/key/info
    Authorization: Bearer <AI_API_KEY>
    -> {"spend": ..., "max_budget": ..., "budget_reset_at": ...}

Fail-OPEN per design (a differenza dell'injection scanner): se questo
controllo non risponde (rete, timeout, payload inatteso), si procede
comunque con la chiamata al modello. Bloccare qui "per sicurezza" costa
certo (un ciclo di valutazione legittimo perso); non bloccare costa poco
(nel peggiore dei casi la chiamata vera fallisce lato organizzatore e
l'Advisor fa comunque il solito fallback neutro).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 10.0


@dataclass
class BudgetStatus:
    ok: bool                        # False = non chiamare il modello: budget quasi esaurito
    spend: float | None = None
    max_budget: float | None = None
    error: str | None = None


def check_budget(api_key: str, base_url: str, safety_margin: float = 0.9,
                  timeout: float = DEFAULT_TIMEOUT_SEC) -> BudgetStatus:
    """Interroga {origin}/key/info. Fail-open su qualunque errore (vedi sopra)."""
    if not api_key or not base_url:
        return BudgetStatus(ok=True, error="api_key/base_url non configurati")
    try:
        parts = urlsplit(base_url)
        origin = f"{parts.scheme}://{parts.netloc}"
        resp = requests.get(f"{origin}/key/info",
                            headers={"Authorization": f"Bearer {api_key}"},
                            timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        spend = float(data["spend"])
        max_budget = float(data["max_budget"])
    except Exception as exc:
        log.warning("Controllo budget AI Gateway fallito (%s): procedo comunque (fail-open)", exc)
        return BudgetStatus(ok=True, error=str(exc))

    ok = max_budget <= 0 or spend < safety_margin * max_budget
    if not ok:
        log.warning("Budget AI Gateway quasi esaurito: spend=%.2f / max_budget=%.2f (soglia %.0f%%)",
                    spend, max_budget, safety_margin * 100)
    return BudgetStatus(ok=ok, spend=spend, max_budget=max_budget)

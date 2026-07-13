"""AI advisor: valutazione del regime di mercato con l'AI API dell'organizzatore.

Vincoli di gara:
  - SOLO l'AI API fornita dall'organizzatore (API di terze parti = squalifica);
  - budget 10 USD/giorno di token -> poche chiamate mirate (default 3/giorno),
    non una chiamata per ogni trade.

Uso: a intervalli regolari il bot chiede all'AI un "risk multiplier" (0..1)
dato lo stato del portafoglio, i top mover e le news recenti. Il multiplier
scala la size delle NUOVE posizioni; non forza mai aperture e non blocca mai
le uscite. In caso di qualsiasi errore il bot continua con multiplier neutro:
l'AI e' un miglioramento opzionale, mai un punto di rottura.

I dettagli dell'endpoint arrivano con la distribuzione degli AI token (entro
il 18/7): compila AI_API_BASE_URL / AI_API_KEY / AI_MODEL nel .env e imposta
ai.enabled=true nel config. Supporta formato OpenAI e Anthropic.
"""
from __future__ import annotations

import json
import logging
import re
import time

import requests

from ..config import AiCfg
from ..portfolio import AiBudget

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a risk officer for a crypto perpetual-futures momentum bot in a trading "
    "competition (scored on return, Sharpe, max drawdown, win rate; disqualified at 20% "
    "drawdown). Given the portfolio, momentum leaders and recent headlines, assess the "
    "market regime. Reply ONLY with JSON: {\"risk_multiplier\": <0.0-1.0>, "
    "\"regime\": \"<short label>\", \"comment\": \"<one sentence>\"}. "
    "1.0 = normal conditions, lower it only for elevated systemic risk."
)


class Advisor:
    def __init__(self, cfg: AiCfg):
        self.cfg = cfg

    def is_ready(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.api_key and self.cfg.base_url and self.cfg.model)

    def should_call(self, budget: AiBudget, now: float | None = None) -> bool:
        if not self.is_ready():
            return False
        now = now or time.time()
        today = time.strftime("%Y-%m-%d", time.gmtime(now))
        if budget.day != today:
            budget.day = today
            budget.calls_today = 0
        if budget.calls_today >= self.cfg.max_calls_per_day:
            return False
        return now - budget.last_call_ts >= self.cfg.interval_hours * 3600

    def assess(self, budget: AiBudget, snapshot: str, headlines: list[str]) -> float:
        """Chiama l'AI e aggiorna budget.risk_multiplier. Neutro (invariato) su errore."""
        user_msg = (
            f"PORTFOLIO & MARKET SNAPSHOT:\n{snapshot}\n\n"
            "RECENT HEADLINES:\n" + ("\n".join(f"- {h}" for h in headlines) or "(none)")
        )
        budget.last_call_ts = time.time()
        budget.calls_today += 1
        try:
            text = self._chat(user_msg)
            data = self._parse_json(text)
            mult = float(data.get("risk_multiplier", 1.0))
            budget.risk_multiplier = min(1.0, max(0.0, mult))
            budget.last_comment = f"{data.get('regime', '?')}: {data.get('comment', '')}"
            log.info("AI advisor: multiplier=%.2f (%s)", budget.risk_multiplier, budget.last_comment)
        except Exception as exc:
            log.warning("AI advisor fallito (%s): multiplier invariato %.2f",
                        exc, budget.risk_multiplier)
        return budget.risk_multiplier

    # ------------------------------------------------------------- providers

    def _chat(self, user_msg: str) -> str:
        base = self.cfg.base_url.rstrip("/")
        if self.cfg.provider == "anthropic":
            resp = requests.post(
                f"{base}/v1/messages",
                headers={"x-api-key": self.cfg.api_key,
                         "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": self.cfg.model, "max_tokens": 300,
                      "system": SYSTEM_PROMPT,
                      "messages": [{"role": "user", "content": user_msg}]},
                timeout=60,
            )
            resp.raise_for_status()
            return "".join(b.get("text", "") for b in resp.json().get("content", []))
        # default: formato OpenAI chat/completions
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {self.cfg.api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.cfg.model, "max_tokens": 300,
                  "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                               {"role": "user", "content": user_msg}]},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_json(text: str) -> dict:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"nessun JSON nella risposta: {text[:200]}")
        return json.loads(match.group(0))

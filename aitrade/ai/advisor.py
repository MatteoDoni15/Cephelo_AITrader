"""AI advisor: client A2A verso lo Strategy Agent (aitrade/agents/strategy_agent.py).

Vincoli di gara:
  - SOLO l'AI API fornita dall'organizzatore (API di terze parti = squalifica);
  - budget 10 USD/giorno di token -> poche chiamate mirate (default 3/giorno),
    non una chiamata per ogni trade.

Da qui in poi l'Advisor NON parla piu' direttamente con l'AI Gateway: e' un
client leggero che interroga lo Strategy Agent via protocollo A2A su
localhost. Le credenziali dell'AI Gateway vivono solo nel processo dello
Strategy Agent (vedi agents/strategy_agent.py) — questo processo (l'engine)
non le detiene mai. Vale lo stesso principio di sempre: il multiplier scala
SOLO la size delle NUOVE posizioni; non forza mai aperture e non blocca mai
le uscite. In caso di qualsiasi errore (Strategy Agent giu', timeout,
risposta malformata) il bot continua con multiplier neutro invariato:
l'AI e' un miglioramento opzionale, mai un punto di rottura.

Ogni chiamata porta un trace_id (correlabile nei log dei 3 processi, vedi
agents/tracing.py) e un shared secret opzionale (AGENTS_SHARED_SECRET, vedi
agents/envelope.py) che lo Strategy Agent verifica prima di consumare budget
AI Gateway o interpellare il Signal Agent. Il secret viaggia sia dentro la
busta applicativa sia come vero header HTTP "Authorization: Bearer" (via
beeai_framework.adapters.a2a.agents.HttpxAsyncClientParameters — verificato
sul pacchetto reale, non tutte le versioni potrebbero esporlo): a livello di
trasporto A2A questa versione di beeai-framework non espone pero' un modo
per FAR VERIFICARE quell'header al server (A2AServerConfig non ha hook di
autenticazione/middleware), quindi la verifica effettiva resta applicativa,
dentro Envelope.check_auth().
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from ..agents.envelope import Envelope
from ..agents.tracing import span
from ..config import AiCfg
from ..portfolio import AiBudget

log = logging.getLogger(__name__)

A2A_TIMEOUT_SEC = 45


class Advisor:
    def __init__(self, cfg: AiCfg):
        self.cfg = cfg

    def is_ready(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.api_key and self.cfg.base_url
                    and self.cfg.model and self.cfg.strategy_agent_url)

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
        """Chiama lo Strategy Agent (A2A) e aggiorna budget.risk_multiplier. Neutro su errore."""
        budget.last_call_ts = time.time()
        budget.calls_today += 1
        envelope = Envelope(data={"snapshot": snapshot, "headlines": headlines},
                            auth=self.cfg.shared_secret)
        trace_id = envelope.trace_id
        try:
            with span("advisor.call_strategy_agent", trace_id, endpoint=self.cfg.strategy_agent_url):
                payload = asyncio.run(self._call_strategy_agent(envelope))
            if "error" in payload:
                raise RuntimeError(payload["error"])
            mult = float(payload["risk_multiplier"])
            budget.risk_multiplier = min(1.0, max(0.0, mult))
            regime = str(payload.get("regime", "?"))
            comment = str(payload.get("comment", ""))
            budget.last_comment = f"{regime}: {comment}"
            log.info("[trace=%s] Strategy Agent: multiplier=%.2f (%s)",
                     trace_id, budget.risk_multiplier, budget.last_comment)
        except Exception as exc:
            log.warning("[trace=%s] Strategy Agent fallito (%s): multiplier invariato %.2f",
                        trace_id, exc, budget.risk_multiplier)
        return budget.risk_multiplier

    # ------------------------------------------------------------- a2a client

    async def _call_strategy_agent(self, envelope: Envelope) -> dict:
        from beeai_framework.adapters.a2a.agents import A2AAgent
        from beeai_framework.adapters.a2a.agents.agent import (
            A2AAgentParameters, HttpxAsyncClientParameters,
        )
        from beeai_framework.memory import UnconstrainedMemory

        headers = {"Authorization": f"Bearer {envelope.auth}"} if envelope.auth else None
        agent = A2AAgent(
            url=self.cfg.strategy_agent_url, memory=UnconstrainedMemory(),
            parameters=A2AAgentParameters(httpx_async_client=HttpxAsyncClientParameters(headers=headers)),
        )
        response = await asyncio.wait_for(agent.run(envelope.dumps()), timeout=A2A_TIMEOUT_SEC)
        text = response.last_message.text if response and response.last_message else ""
        return json.loads(text)

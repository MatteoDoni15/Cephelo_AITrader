"""Signal Agent: raccolta di segnali esterni (ricerca web + news), a2a.

Non genera nulla e non chiama alcun modello AI: e' retrieval deterministico
(DuckDuckGo via LangChain, gratuito, senza chiave) seguito dal filtro
prompt-injection locale (injection_scanner). Per questo non detiene alcuna
credenziale — ne' quelle di trading RapidX ne' quelle dell'AI Gateway
dell'organizzatore — e non ha nulla di prezioso da compromettere, coerente
col principio "privilegio minimo per ruolo" adottato in tutta la pipeline AI.

Esposto via A2A (vedi run_agents.py) SOLO su localhost: e' un servizio di
supporto interno allo Strategy Agent, mai raggiungibile dall'esterno.

Accetta sia una busta (Envelope, vedi agents/envelope.py) con trace_id/auth
sia una stringa nuda con la query, per compatibilita' con chi lo chiama
direttamente. Se e' configurato un AGENTS_SHARED_SECRET, una busta con auth
mancante o errato viene rifiutata prima di interrogare DuckDuckGo.
"""
from __future__ import annotations

import logging
from typing import Unpack

from beeai_framework.agents import AgentMeta, AgentOptions, AgentOutput, BaseAgent
from beeai_framework.backend import AnyMessage, AssistantMessage, UserMessage
from beeai_framework.context import RunContext
from beeai_framework.emitter import Emitter
from beeai_framework.memory import BaseMemory, UnconstrainedMemory
from beeai_framework.runnable import runnable_entry

from .envelope import Envelope
from .injection_scanner import filter_clean
from .tracing import span

log = logging.getLogger(__name__)

MAX_SNIPPETS = 8
SNIPPET_MAX_CHARS = 300
DEFAULT_QUERY = "crypto market news today"


def _web_search(query: str, max_results: int = 5) -> list[str]:
    from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
    wrapper = DuckDuckGoSearchAPIWrapper(source="text")
    items = wrapper.results(query, max_results=max_results)
    return [_format_hit(it) for it in items if _format_hit(it)]


def _news_search(query: str, max_results: int = 5) -> list[str]:
    from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
    wrapper = DuckDuckGoSearchAPIWrapper(source="news")
    items = wrapper.results(query, max_results=max_results)
    return [_format_hit(it) for it in items if _format_hit(it)]


def _format_hit(item: dict) -> str:
    title = (item.get("title") or "").strip()
    body = (item.get("snippet") or item.get("body") or "").strip()
    if not title and not body:
        return ""
    return f"{title}: {body}"[:SNIPPET_MAX_CHARS]


class SignalAgent(BaseAgent):
    """Agent non generativo: `run(query)` restituisce contesto esterno gia' filtrato."""

    def __init__(self, memory: BaseMemory | None = None, shared_secret: str = "") -> None:
        super().__init__()
        self._memory = memory or UnconstrainedMemory()
        self._shared_secret = shared_secret

    @property
    def memory(self) -> BaseMemory:
        return self._memory

    @memory.setter
    def memory(self, memory: BaseMemory) -> None:
        self._memory = memory

    def _create_emitter(self) -> Emitter:
        return Emitter.root().child(namespace=["agent", "signal"], creator=self)

    @runnable_entry
    async def run(self, input: str | list[AnyMessage], /, **kwargs: Unpack[AgentOptions]) -> AgentOutput:
        raw_input = input if isinstance(input, str) else _last_text(input) or DEFAULT_QUERY
        envelope = Envelope.loads(raw_input)
        trace_id = envelope.trace_id
        query = str(envelope.data.get("query") or envelope.data.get("raw") or DEFAULT_QUERY)

        async def handler(context: RunContext) -> AgentOutput:
            if not envelope.check_auth(self._shared_secret):
                log.warning("[trace=%s] Richiesta rifiutata: shared secret assente o errato", trace_id)
                result = AssistantMessage("(non autorizzato)")
                await self._memory.add(result)
                return AgentOutput(output=[result], context={"error": "unauthorized"})

            raw: list[str] = []
            with span("signal_agent.run", trace_id, query=query[:80]):
                try:
                    raw.extend(_web_search(query))
                except Exception as exc:
                    log.warning("[trace=%s] Ricerca web DuckDuckGo fallita: %s", trace_id, exc)
                try:
                    raw.extend(_news_search(query))
                except Exception as exc:
                    log.warning("[trace=%s] Ricerca news DuckDuckGo fallita: %s", trace_id, exc)

                clean = filter_clean(raw)[:MAX_SNIPPETS]
            text = "\n".join(f"- {s}" for s in clean) if clean else "(nessun segnale esterno disponibile)"
            result = AssistantMessage(text)
            await self._memory.add(result)
            return AgentOutput(output=[result], context={"snippets": clean})

        return await handler(RunContext.get())

    @property
    def meta(self) -> AgentMeta:
        return AgentMeta(
            name="SignalAgent",
            description="Raccoglie e filtra ricerca web e news per lo Strategy Agent (nessuna generazione AI).",
            tools=[],
        )


def _last_text(messages: list[AnyMessage]) -> str:
    for msg in reversed(messages):
        text = getattr(msg, "text", "") or ""
        if text:
            return text
    return ""


def serve() -> None:
    """Avvia il Signal Agent come server A2A (bloccante). SOLO localhost per design:
    non e' un servizio da esporre in rete, e' supporto interno allo Strategy Agent."""
    from beeai_framework.adapters.a2a import A2AServer, A2AServerConfig
    from beeai_framework.serve.utils import LRUMemoryManager

    from ..config import load_config

    cfg = load_config().ai
    if not cfg.shared_secret:
        log.warning("AGENTS_SHARED_SECRET non configurato: il Signal Agent accetta "
                    "chiamate da qualunque processo locale (nessuna verifica applicativa)")
    log.info("Signal Agent in ascolto su http://127.0.0.1:%d", cfg.signal_agent_port)
    A2AServer(
        config=A2AServerConfig(host="127.0.0.1", port=cfg.signal_agent_port, protocol="jsonrpc"),
        memory_manager=LRUMemoryManager(maxsize=32),
    ).register(SignalAgent(shared_secret=cfg.shared_secret)).serve()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    serve()

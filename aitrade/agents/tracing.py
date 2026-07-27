"""Tracing "lite" per correlare le chiamate A2A tra i tre processi del bot
(engine/Advisor, Strategy Agent, Signal Agent) senza aggiungere OpenTelemetry
come dipendenza.

Perche' non OpenTelemetry: al momento in cui questo modulo e' stato scritto,
l'ambiente di sviluppo aveva pochissimo spazio disco libero e l'installazione
di beeai-framework (gia' richiesta da requirements.txt) falliva per questo
motivo (build Rust di una dipendenza transitiva, litellm). Aggiungere
un'altra libreria in quelle condizioni non era ne' verificabile ne' prudente.
Questo modulo produce span in JSON Lines (logs/traces.jsonl) con la stessa
forma sostanziale di uno span OpenTelemetry (trace_id, span_id, nome,
durata, esito): se in futuro l'ambiente lo permette, sostituirlo con
opentelemetry-sdk e' un cambio isolato a questo file — i chiamanti
(span()/new_trace_id()) non cambiano.

Come per l'injection scanner e l'AI advisor: un guasto nella tracciatura non
deve MAI rompere la chiamata reale che sta misurando.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import time
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_TRACE_FILE = Path(os.environ.get("AITRADE_TRACE_FILE", "logs/traces.jsonl"))


def new_trace_id() -> str:
    """ID breve che lega insieme, nei log dei 3 processi, i passi di una
    stessa richiesta (Advisor -> Strategy Agent -> Signal Agent)."""
    return uuid.uuid4().hex[:16]


def _new_span_id() -> str:
    return uuid.uuid4().hex[:8]


def _write(record: dict) -> None:
    _TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _TRACE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


@contextlib.contextmanager
def span(name: str, trace_id: str, parent_span_id: str | None = None, **attrs):
    """Misura un blocco di codice (una chiamata A2A, una ricerca, una
    chiamata all'AI Gateway) e lo registra come riga JSON in
    logs/traces.jsonl. Propaga sempre l'eccezione originale; non solleva mai
    un'eccezione propria, nemmeno se la scrittura su disco fallisce."""
    span_id = _new_span_id()
    t0 = time.time()
    status, error = "ok", None
    try:
        yield span_id
    except Exception as exc:
        status, error = "error", str(exc)
        raise
    finally:
        record = {
            "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent_span_id,
            "name": name, "start": t0, "end": time.time(),
            "duration_ms": round((time.time() - t0) * 1000, 1),
            "status": status, **({"error": error} if error else {}),
            **attrs,
        }
        try:
            _write(record)
        except Exception as exc:
            log.debug("Scrittura trace fallita (ignorata): %s", exc)

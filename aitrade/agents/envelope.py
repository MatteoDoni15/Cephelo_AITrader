"""Busta applicativa per le chiamate A2A interne (Advisor -> Strategy Agent
-> Signal Agent).

Il protocollo A2A vero e proprio (vedi a2a-sdk) prevede gia' campi nativi per
questo scopo — Message.metadata, Message.extensions, AgentCard.security_schemes
con Bearer/API key/OAuth2/OIDC — ma il wrapper Python di alto livello usato
qui (beeai_framework.adapters.a2a) non e' stato verificabile in questo
ambiente (vedi tracing.py per il perche'). Questo modulo ottiene lo stesso
risultato un livello sopra, dentro il payload JSON che gia' viaggia nel campo
testo dei messaggi A2A esistenti — nessun cambiamento al trasporto.

Campi:
  data       il payload applicativo vero e proprio (dict libero)
  trace_id   per correlare i log/trace dei 3 processi (vedi tracing.py)
  auth       shared secret opzionale (AGENTS_SHARED_SECRET nel .env): se il
             ricevente ne ha uno configurato e non combacia, la richiesta va
             rifiutata PRIMA di consumare budget AI Gateway o fare ricerche
  v          versione della busta (0 = payload legacy senza busta, rilevato
             automaticamente per compatibilita' con chiamanti preesistenti)

Un campo sconosciuto nella busta va sempre ignorato, mai motivo di errore:
stessa regola "ignora cio' che non riconosci" del protocollo A2A per le sue
extension.
"""
from __future__ import annotations

import hmac
import json
from dataclasses import dataclass, field

from .tracing import new_trace_id

ENVELOPE_VERSION = 1


@dataclass
class Envelope:
    data: dict
    trace_id: str = field(default_factory=new_trace_id)
    auth: str = ""
    v: int = ENVELOPE_VERSION

    def dumps(self) -> str:
        return json.dumps({"v": self.v, "trace_id": self.trace_id,
                           "auth": self.auth, "data": self.data})

    @classmethod
    def loads(cls, raw: str) -> "Envelope":
        """Parsa una busta. Se il testo non e' una busta valida (chiamante
        precedente o esterno), lo tratta come payload legacy: v=0, nessun
        auth, trace_id generato al volo (comunque tracciabile), data =
        l'oggetto JSON parsato (o {'raw': raw} se non e' nemmeno JSON)."""
        try:
            obj = json.loads(raw)
        except Exception:
            return cls(data={"raw": raw}, v=0)
        if isinstance(obj, dict) and "v" in obj and "data" in obj:
            return cls(data=obj.get("data") or {},
                       trace_id=obj.get("trace_id") or new_trace_id(),
                       auth=obj.get("auth", ""), v=obj.get("v", ENVELOPE_VERSION))
        return cls(data=obj if isinstance(obj, dict) else {"raw": obj}, v=0)

    def check_auth(self, expected_secret: str) -> bool:
        """True se il secret combacia, o se il ricevente non ne richiede
        alcuno (comportamento di default, retrocompatibile)."""
        if not expected_secret:
            return True
        return hmac.compare_digest(self.auth or "", expected_secret)

"""Scanner locale di prompt injection per testo esterno (news, ricerche web).

Usa un classificatore HuggingFace locale (protectai/deberta-v3-base-prompt-
injection-v2, 184M parametri, gira su CPU senza GPU) caricato una sola volta
per processo. NON e' un modello generativo e non decide nulla sul trading:
filtra solo quale testo esterno puo' entrare nel prompt dello Strategy Agent.
Per questo non rientra nel vincolo di gara "una sola AI, quella
dell'organizzatore" (quel vincolo riguarda i modelli che *decidono*, non
i classificatori di sicurezza locali che *scartano*).

Fail-closed by design: se il classificatore non si carica (torch/transformers
assenti, download fallito), il testo NON viene scartato silenziosamente ne'
lasciato passare — viene escluso per prudenza. E' l'eccezione alla regola
generale "l'AI non e' mai un punto di rottura" usata nel resto della
pipeline: qui il fail-open vanificherebbe lo scopo stesso del filtro.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MODEL_NAME = "protectai/deberta-v3-base-prompt-injection-v2"
SNIPPET_MAX_CHARS = 2000  # oltre, il classificatore tronca comunque internamente

_classifier = None
_load_attempted = False


def _get_classifier():
    """Carica il classificatore in modo pigro; None se non disponibile."""
    global _classifier, _load_attempted
    if _classifier is not None or _load_attempted:
        return _classifier
    _load_attempted = True
    try:
        from transformers import pipeline
        _classifier = pipeline("text-classification", model=MODEL_NAME)
        log.info("Injection scanner caricato (%s)", MODEL_NAME)
    except Exception as exc:
        log.warning("Injection scanner non disponibile (%s): testo esterno scartato per prudenza", exc)
    return _classifier


def _is_injection(label: str, score: float, threshold: float) -> bool:
    tag = str(label).upper()
    flagged = "INJECT" in tag or tag in ("1", "LABEL_1")
    return flagged and score >= threshold


def filter_clean(snippets: list[str], threshold: float = 0.5) -> list[str]:
    """Restituisce solo gli snippet NON classificati come prompt injection.

    Fail-closed: [] se il classificatore non e' disponibile o la lista e' vuota.
    Non solleva mai eccezioni verso il chiamante.
    """
    if not snippets:
        return []
    clf = _get_classifier()
    if clf is None:
        return []

    clean: list[str] = []
    for snippet in snippets:
        text = (snippet or "").strip()
        if not text:
            continue
        try:
            result = clf(text[:SNIPPET_MAX_CHARS])[0]
            if _is_injection(result.get("label", ""), float(result.get("score", 0.0)), threshold):
                log.warning("Prompt injection sospetta scartata (score=%.2f): %.80s",
                            result.get("score", 0.0), text)
                continue
            clean.append(text)
        except Exception as exc:
            log.warning("Scansione injection fallita su uno snippet (%s): scartato", exc)
    return clean

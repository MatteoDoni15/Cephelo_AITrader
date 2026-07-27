"""Schema strutturato per l'output dello Strategy Agent.

Un modello Pydantic passato a BeeAI come `response_format` vincola la
generazione del modello (MiniMax-M3) a rispettare tipi e limiti *durante*
la generazione stessa, non solo in un parsing post-hoc: e' la prima linea
di difesa contro un output malformato o fuori dai limiti attesi.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RiskAssessment(BaseModel):
    risk_multiplier: float = Field(
        ge=0.0, le=1.0,
        description="1.0 = condizioni di mercato normali; abbassalo solo per rischio sistemico elevato",
    )
    regime: str = Field(max_length=40, description="etichetta breve del regime di mercato corrente")
    comment: str = Field(max_length=240, description="una frase che motiva la valutazione")

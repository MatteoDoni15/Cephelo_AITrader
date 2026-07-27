import pytest
from pydantic import ValidationError

from aitrade.agents.schemas import RiskAssessment


def test_valid_assessment():
    a = RiskAssessment(risk_multiplier=0.5, regime="calm", comment="niente di rilevante")
    assert a.risk_multiplier == 0.5


def test_risk_multiplier_out_of_range_rejected():
    with pytest.raises(ValidationError):
        RiskAssessment(risk_multiplier=1.5, regime="calm", comment="x")
    with pytest.raises(ValidationError):
        RiskAssessment(risk_multiplier=-0.1, regime="calm", comment="x")


def test_regime_too_long_rejected():
    with pytest.raises(ValidationError):
        RiskAssessment(risk_multiplier=1.0, regime="x" * 41, comment="ok")


def test_comment_too_long_rejected():
    with pytest.raises(ValidationError):
        RiskAssessment(risk_multiplier=1.0, regime="calm", comment="x" * 241)

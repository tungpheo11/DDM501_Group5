"""
Simulations package for Credit Default Risk Scoring Platform.
Provides realistic applicant traffic, persona-based modeling, and demographic/credit drift injection.
"""

from simulations.data_generator import CreditDataGenerator
from simulations.scenarios import (
    BaseScenario,
    NormalTrafficScenario,
    GenZDriftScenario,
    HolidaySpikeScenario,
    FraudAttackScenario,
)

__all__ = [
    "CreditDataGenerator",
    "BaseScenario",
    "NormalTrafficScenario",
    "GenZDriftScenario",
    "HolidaySpikeScenario",
    "FraudAttackScenario",
]

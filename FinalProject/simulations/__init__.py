"""Simulations package for Credit Default Risk Scoring Platform.
Provides realistic cardholder traffic, persona-based modeling, and demographic/credit drift injection.
"""

from simulations.data_generator import CreditDataGenerator
from simulations.scenarios import (
    BaseScenario,
    FraudAttackScenario,
    GenZDriftScenario,
    HolidaySpikeScenario,
    NormalTrafficScenario,
)

__all__ = [
    "CreditDataGenerator",
    "BaseScenario",
    "NormalTrafficScenario",
    "GenZDriftScenario",
    "HolidaySpikeScenario",
    "FraudAttackScenario",
]

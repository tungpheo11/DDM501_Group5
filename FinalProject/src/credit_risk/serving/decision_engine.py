"""Business decisioning on top of the model's default probability."""

from __future__ import annotations

from dataclasses import dataclass

SCORE_MIN = 300
SCORE_MAX = 850
MAX_APPROVE_LIMIT = 500_000.0
MAX_REVIEW_LIMIT = 100_000.0


@dataclass(frozen=True)
class CreditDecision:
    """Decision, score, tier and recommended limit for one applicant."""

    decision: str
    credit_score: int
    credit_tier: str
    recommended_limit: float


def risk_decision(probability: float, review_threshold: float, decline_threshold: float) -> str:
    """``DECLINE`` above the decline threshold, ``REVIEW`` above the review threshold, else ``APPROVE``."""
    if probability >= decline_threshold:
        return "DECLINE"
    if probability >= review_threshold:
        return "REVIEW"
    return "APPROVE"


def credit_score(probability: float) -> int:
    """Map default probability linearly onto a FICO-like 300-850 scale (higher is better)."""
    score = int(round(SCORE_MAX - probability * (SCORE_MAX - SCORE_MIN)))
    return max(SCORE_MIN, min(SCORE_MAX, score))


def credit_tier(score: int) -> str:
    """Tier boundaries: PRIME >= 740, NEAR_PRIME >= 670, SUBPRIME >= 580, else HIGH_RISK."""
    if score >= 740:
        return "PRIME"
    if score >= 670:
        return "NEAR_PRIME"
    if score >= 580:
        return "SUBPRIME"
    return "HIGH_RISK"


def recommended_limit(decision: str, limit_bal: float) -> float:
    """Suggested credit line rounded to 100 NTD: raise on approve, cut on review, zero on decline."""
    if decision == "APPROVE":
        return round(min(limit_bal * 1.25, MAX_APPROVE_LIMIT), -2)
    if decision == "REVIEW":
        return round(min(limit_bal * 0.50, MAX_REVIEW_LIMIT), -2)
    return 0.0


def decide(probability: float, limit_bal: float, review_threshold: float, decline_threshold: float) -> CreditDecision:
    """Combine all decision rules for one applicant."""
    decision = risk_decision(probability, review_threshold, decline_threshold)
    score = credit_score(probability)
    return CreditDecision(
        decision=decision,
        credit_score=score,
        credit_tier=credit_tier(score),
        recommended_limit=recommended_limit(decision, limit_bal),
    )

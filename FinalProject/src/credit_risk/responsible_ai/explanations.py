"""Rule-based, human-readable risk explanations and policy guardrails.

These rules complement (and will be cross-checked against) model-based
explanations such as SHAP/LIME.
"""

from __future__ import annotations


def top_risk_factors(pay_0: int, utilization: float, age: int, limit_bal: float, limit: int = 3) -> list[str]:
    """Return up to ``limit`` explanations ordered by priority: delinquency, utilization, cohort, ceiling."""
    factors: list[str] = []

    if pay_0 >= 2:
        factors.append(f"Severe Delinquency: PAY_0={pay_0} indicates {pay_0}+ months payment default")
    elif pay_0 == 1:
        factors.append("Payment Lag: 1-month delayed payment recorded on recent billing cycle")
    else:
        factors.append("Repayment Discipline: Timely and structured monthly repayments")

    if utilization >= 0.90:
        factors.append(f"Excessive Credit Line Utilization: {utilization * 100:.1f}% of limit consumed")
    elif utilization <= 0.35:
        factors.append(f"Conservative Debt Ratio: Low credit utilization of {utilization * 100:.1f}%")
    else:
        factors.append(f"Moderate Debt Utilization: {utilization * 100:.1f}% credit utilization")

    if age < 25:
        factors.append(f"Demographic Cohort: Young cardholder profile ({age}yo) with short account history")
    elif age >= 45:
        factors.append(f"Demographic Cohort: Mature cardholder profile ({age}yo) with long account history")

    if limit_bal <= 30000.0:
        factors.append("Sub-prime Credit Ceiling: Low current credit limit")

    return factors[:limit]


def policy_guardrails(age: int, utilization: float, pay_0: int) -> dict[str, str]:
    """Deterministic compliance checks attached to every decision."""
    return {
        "age_verification": "PASS" if age >= 18 else "FAIL",
        "utilization_ceiling_check": "ACCEPTABLE" if utilization < 0.95 else "OVER_UTILIZED_WARNING",
        "delinquency_guardrail": "CLEAR" if pay_0 <= 1 else "ELEVATED_DEFAULT_RISK",
    }

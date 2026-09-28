from credit_risk.responsible_ai.explanations import policy_guardrails, top_risk_factors


def test_severe_delinquency_ranks_first():
    factors = top_risk_factors(pay_0=3, utilization=0.95, age=22, limit_bal=20_000)
    assert factors[0].startswith("Severe Delinquency")
    assert factors[1].startswith("Excessive Credit Line Utilization")
    assert factors[2].startswith("Demographic Cohort: Young")
    assert len(factors) == 3


def test_payment_lag_and_moderate_utilization():
    factors = top_risk_factors(pay_0=1, utilization=0.5, age=35, limit_bal=100_000)
    assert factors == [
        "Payment Lag: 1-month delayed payment recorded on recent billing cycle",
        "Moderate Debt Utilization: 50.0% credit utilization",
    ]


def test_disciplined_mature_low_ceiling():
    factors = top_risk_factors(pay_0=-1, utilization=0.1, age=50, limit_bal=30_000, limit=4)
    assert factors[0].startswith("Repayment Discipline")
    assert factors[1].startswith("Conservative Debt Ratio")
    assert factors[2].startswith("Demographic Cohort: Mature")
    assert factors[3].startswith("Sub-prime Credit Ceiling")


def test_policy_guardrails():
    assert policy_guardrails(age=30, utilization=0.5, pay_0=0) == {
        "age_verification": "PASS",
        "utilization_ceiling_check": "ACCEPTABLE",
        "delinquency_guardrail": "CLEAR",
    }
    flagged = policy_guardrails(age=17, utilization=0.99, pay_0=2)
    assert flagged["age_verification"] == "FAIL"
    assert flagged["utilization_ceiling_check"] == "OVER_UTILIZED_WARNING"
    assert flagged["delinquency_guardrail"] == "ELEVATED_DEFAULT_RISK"

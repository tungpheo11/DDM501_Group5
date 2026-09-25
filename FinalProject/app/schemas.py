"""
Module: schemas.py
Pydantic data models for Credit Default Risk API request and response.
"""

from pydantic import BaseModel, Field, ConfigDict


class CreditPredictRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "LIMIT_BAL": 20000.0,
                "SEX": 2,
                "EDUCATION": 2,
                "MARRIAGE": 1,
                "AGE": 24,
                "PAY_0": 2,
                "PAY_2": 2,
                "PAY_3": -1,
                "PAY_4": -1,
                "PAY_5": -2,
                "PAY_6": -2,
                "BILL_AMT1": 3913.0,
                "BILL_AMT2": 3102.0,
                "BILL_AMT3": 689.0,
                "BILL_AMT4": 0.0,
                "BILL_AMT5": 0.0,
                "BILL_AMT6": 0.0,
                "PAY_AMT1": 0.0,
                "PAY_AMT2": 689.0,
                "PAY_AMT3": 0.0,
                "PAY_AMT4": 0.0,
                "PAY_AMT5": 0.0,
                "PAY_AMT6": 0.0,
            }
        }
    )

    LIMIT_BAL: float = Field(..., description="Amount of given credit (NT dollar)")
    SEX: int = Field(..., description="Gender (1=male, 2=female)")
    EDUCATION: int = Field(
        ..., description="Education (1=graduate, 2=university, 3=high school, 4=others)"
    )
    MARRIAGE: int = Field(
        ..., description="Marital status (1=married, 2=single, 3=others)"
    )
    AGE: int = Field(..., description="Age in years")
    PAY_0: int = Field(
        ...,
        description="Repayment status in September (-1=pay duly, 1=delay one month, ...)",
    )
    PAY_2: int = Field(..., description="Repayment status in August")
    PAY_3: int = Field(..., description="Repayment status in July")
    PAY_4: int = Field(..., description="Repayment status in June")
    PAY_5: int = Field(..., description="Repayment status in May")
    PAY_6: int = Field(..., description="Repayment status in April")
    BILL_AMT1: float = Field(
        ..., description="Amount of bill statement in September (NT dollar)"
    )
    BILL_AMT2: float = Field(..., description="Amount of bill statement in August")
    BILL_AMT3: float = Field(..., description="Amount of bill statement in July")
    BILL_AMT4: float = Field(..., description="Amount of bill statement in June")
    BILL_AMT5: float = Field(..., description="Amount of bill statement in May")
    BILL_AMT6: float = Field(..., description="Amount of bill statement in April")
    PAY_AMT1: float = Field(
        ..., description="Amount of previous payment in September (NT dollar)"
    )
    PAY_AMT2: float = Field(..., description="Amount of previous payment in August")
    PAY_AMT3: float = Field(..., description="Amount of previous payment in July")
    PAY_AMT4: float = Field(..., description="Amount of previous payment in June")
    PAY_AMT5: float = Field(..., description="Amount of previous payment in May")
    PAY_AMT6: float = Field(..., description="Amount of previous payment in April")


class CreditPredictResponse(BaseModel):
    request_id: str
    default_prediction: int = Field(
        ...,
        description="0 = No Default (Credit Approved), 1 = Default Risk (Review/Decline)",
    )
    default_probability: float = Field(
        ..., description="Probability of default (0.0 to 1.0)"
    )
    credit_score: int = Field(
        ..., description="Calibrated credit score on 300-850 scale (higher is better)"
    )
    credit_tier: str = Field(
        ..., description="Risk tier: PRIME, NEAR_PRIME, SUBPRIME, or HIGH_RISK"
    )
    risk_decision: str = Field(
        ..., description="Business decision: APPROVE, REVIEW, or DECLINE"
    )
    recommended_limit_ntd: float = Field(
        ..., description="Algorithmically determined safe credit limit in NT dollars"
    )
    top_risk_factors: list[str] = Field(
        default_factory=list,
        description="Explainability: Top drivers influencing this customer's risk score",
    )
    policy_guardrails: dict[str, str] = Field(
        default_factory=dict,
        description="Automated compliance and policy checks applied during evaluation",
    )
    served_by: str
    latency_ms: float


class HealthResponse(BaseModel):

    status: str
    model_loaded: bool
    model_name: str
    model_source: str
    database_connected: bool

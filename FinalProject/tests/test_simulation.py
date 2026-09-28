"""
Unit Tests for Credit Traffic & Drift Simulation Suite.
Validates data generator distributions, schema adherence, and scenario executions with mock APIs.
"""

from unittest.mock import patch, MagicMock
from pathlib import Path
import yaml
import pytest

from simulations.data_generator import CreditDataGenerator
from simulations.scenarios import (
    NormalTrafficScenario,
    GenZDriftScenario,
    HolidaySpikeScenario,
    FraudAttackScenario,
)
from src.config import ALL_FEATURES


@pytest.fixture
def generator():
    return CreditDataGenerator(seed=42)


def test_generator_normal_sample_schema(generator):
    """Verifies that normal sample contains all 23 features with valid data types."""
    sample = generator.generate_normal_sample()

    for feat in ALL_FEATURES:
        assert feat in sample, f"Missing feature: {feat}"

    assert 35 <= sample["AGE"] <= 55
    assert sample["LIMIT_BAL"] >= 100000.0
    assert sample["PAY_0"] == 0
    assert sample["SEX"] in [1, 2]
    assert sample["BILL_AMT1"] >= 0.0


def test_generator_genz_drift_sample(generator):
    """Verifies that Gen-Z drift sample reflects younger cohort and lower limit."""
    sample = generator.generate_genz_drift_sample()

    for feat in ALL_FEATURES:
        assert feat in sample

    assert 19 <= sample["AGE"] <= 25
    assert sample["LIMIT_BAL"] <= 50000.0
    assert sample["MARRIAGE"] == 2  # Single cohort


def test_generator_holiday_spike_sample(generator):
    """Verifies high bill utilization for holiday shopper sample."""
    sample = generator.generate_holiday_spike_sample()

    for feat in ALL_FEATURES:
        assert feat in sample

    utilization = sample["BILL_AMT1"] / sample["LIMIT_BAL"]
    assert utilization >= 0.70


def test_generator_delinquent_sample(generator):
    """Verifies delinquent borrower has severe past-due indicators."""
    sample = generator.generate_delinquent_sample()

    for feat in ALL_FEATURES:
        assert feat in sample

    assert sample["PAY_0"] >= 2


def test_generator_batch(generator):
    """Verifies batch generation produces correct number of valid records."""
    batch = generator.generate_batch(count=15, scenario="normal")
    assert len(batch) == 15
    for item in batch:
        assert len(item) == len(ALL_FEATURES)


def test_config_yaml_validity():
    """Verifies simulations/config.yaml is syntactically valid and has necessary sections."""
    config_path = Path(__file__).resolve().parents[1] / "simulations" / "config.yaml"
    assert config_path.exists()

    with open(config_path, "r") as f:
        cfg = yaml.safe_load(f)

    assert "api" in cfg
    assert "simulation" in cfg
    assert "drift_thresholds" in cfg
    assert cfg["drift_thresholds"]["psi_critical"] == 0.25


@patch("requests.post")
def test_normal_scenario_run_with_mock(mock_post, generator):
    """Verifies NormalTrafficScenario executes and computes stats correctly."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "risk_decision": "APPROVE",
        "recommended_limit_ntd": 250000.0,
        "default_probability": 0.08,
    }
    mock_post.return_value = mock_resp

    scenario = NormalTrafficScenario(
        api_url="http://mock-api:18020/predict", generator=generator
    )
    res = scenario.run(count=5, delay_sec=0.0)

    assert res["total_sent"] == 5
    assert res["APPROVE"] == 5
    assert res["DECLINE"] == 0
    assert res["errors"] == 0
    assert res["approved_volume_ntd"] == 1250000.0


@patch("requests.post")
def test_genz_scenario_run_with_mock(mock_post, generator):
    """Verifies GenZDriftScenario handles REVIEW and DECLINE decisions."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "risk_decision": "REVIEW",
        "recommended_limit_ntd": 20000.0,
        "default_probability": 0.45,
    }
    mock_post.return_value = mock_resp

    scenario = GenZDriftScenario(
        api_url="http://mock-api:18020/predict", generator=generator
    )
    res = scenario.run(count=4, delay_sec=0.0)

    assert res["total_sent"] == 4
    assert res["REVIEW"] == 4
    assert res["errors"] == 0


@patch("requests.post")
def test_scenario_error_handling(mock_post, generator):
    """Verifies scenarios track connection errors gracefully."""
    mock_post.side_effect = Exception("Connection refused")

    scenario = HolidaySpikeScenario(
        api_url="http://mock-api:18020/predict", generator=generator
    )
    res = scenario.run(count=3, delay_sec=0.0)

    assert res["total_sent"] == 3
    assert res["errors"] == 3


@patch("requests.post")
def test_fraud_attack_scenario(mock_post, generator):
    """Verifies FraudAttackScenario registers blocked exposure."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "risk_decision": "DECLINE",
        "recommended_limit_ntd": 0.0,
        "default_probability": 0.88,
    }
    mock_post.return_value = mock_resp

    scenario = FraudAttackScenario(
        api_url="http://mock-api:18020/predict", generator=generator
    )
    res = scenario.run(count=3, delay_sec=0.0)

    assert res["total_sent"] == 3
    assert res["DECLINE"] == 3
    assert res["blocked_exposure_ntd"] > 0.0


def test_generator_sample_by_scenario_coverage(generator):
    """Verifies all branches of generate_sample_by_scenario produce valid samples."""
    for sc in ["normal", "genz_drift", "holiday_spike", "fraud_attack", "unknown"]:
        sample = generator.generate_sample_by_scenario(sc)
        assert len(sample) == len(ALL_FEATURES)


@patch("requests.post")
def test_holiday_spike_scenario_success(mock_post, generator):
    """Verifies HolidaySpikeScenario with HTTP 200."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "risk_decision": "APPROVE",
        "recommended_limit_ntd": 150000.0,
        "default_probability": 0.15,
    }
    mock_post.return_value = mock_resp

    scenario = HolidaySpikeScenario(
        api_url="http://mock-api:18020/predict", generator=generator
    )
    res = scenario.run(count=2, delay_sec=0.0)
    assert res["APPROVE"] == 2
    assert res["approved_volume_ntd"] == 300000.0


@patch("requests.get")
def test_check_api_health_branches(mock_get):
    """Verifies check_api_health success, error code, and exception branches."""
    from simulations.run_simulation import check_api_health

    # Success
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"model_name": "credit-risk", "model_source": "mlflow"}
    mock_get.return_value = mock_resp
    assert check_api_health("http://mock:18020") is True

    # Error status
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"
    assert check_api_health("http://mock:18020") is False

    # Exception
    mock_get.side_effect = Exception("Network timeout")
    assert check_api_health("http://mock:18020") is False


@patch("requests.post")
def test_run_full_lifecycle_simulation(mock_post):
    """Verifies 2-phase lifecycle runner executes without error."""
    from simulations.run_simulation import run_full_lifecycle_simulation

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "risk_decision": "APPROVE",
        "recommended_limit_ntd": 50000.0,
        "default_probability": 0.12,
    }
    mock_post.return_value = mock_resp

    # Run with count=2, delay=0.0 for speed
    run_full_lifecycle_simulation(base_url="http://mock:18020", count=2, delay=0.0)

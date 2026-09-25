"""
Script: persona_simulator.py
Production-Grade Multi-Persona & Behavioral Evolution Traffic Simulator.

Simulates real-world macroeconomic and customer behavioral shifts across 5 distinct archetypes:
1. Traditional Prime Worker (Stable salary, age 35-52, prompt repayment, low utilization)
2. Holiday Shopping Spurt (Prime borrower under holiday/inflation spending surge, high utilization)
3. Gen-Z Gig Freelancer (Age 19-25, lumpy gig cashflows, PAY_0=1 delay, lower credit limit)
4. Over-leveraged Speculator / Syndicate (Debt maxed out >95%, multi-month delinquency PAY_0>=2)
5. Rebuilding Borrower (Past delinquency 6 months ago, but disciplined recent repayments)

Simulation Modes:
- 'normal': Baseline operations (80% Prime, 10% Shoppers, 10% Gen-Z) -> PSI < 0.05
- 'holiday_spike': Seasonal festival surge (60% Shoppers, 30% Prime, 10% Gen-Z)
- 'campaign_drift': Viral Gen-Z acquisition campaign (75% Gen-Z, 15% Prime, 10% Speculator) -> PSI >= 0.25
- 'fraud_attack': Coordinated high-risk debt maxing (70% Speculators, 20% Gen-Z, 10% Prime)
- 'staged_progression': Executes all 4 market regimes sequentially to produce dynamic Grafana charts.
"""

import argparse
import random
import time
from typing import Dict, Any, Tuple
import requests

API_URL = "http://localhost:18020/predict"


def generate_traditional_worker() -> Tuple[str, Dict[str, Any]]:
    """Persona 1: Khách hàng truyền thống (35-52 tuổi, tài chính ổn định, chi trả chuẩn mực)"""
    age = random.randint(35, 52)
    limit_bal = float(random.choice([150000, 200000, 250000, 300000, 400000]))
    bill_base = limit_bal * random.uniform(0.08, 0.25)

    return "Traditional Prime Worker", {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([1, 2]),
        "MARRIAGE": random.choice([1, 2]),
        "AGE": age,
        "PAY_0": 0,
        "PAY_2": 0,
        "PAY_3": 0,
        "PAY_4": 0,
        "PAY_5": 0,
        "PAY_6": 0,
        "BILL_AMT1": round(bill_base * random.uniform(0.9, 1.1), 2),
        "BILL_AMT2": round(bill_base * random.uniform(0.85, 1.05), 2),
        "BILL_AMT3": round(bill_base * random.uniform(0.8, 1.0), 2),
        "BILL_AMT4": round(bill_base * random.uniform(0.75, 0.95), 2),
        "BILL_AMT5": round(bill_base * random.uniform(0.7, 0.9), 2),
        "BILL_AMT6": round(bill_base * random.uniform(0.65, 0.85), 2),
        "PAY_AMT1": round(bill_base * random.uniform(0.8, 1.2), 2),
        "PAY_AMT2": round(bill_base * random.uniform(0.8, 1.2), 2),
        "PAY_AMT3": round(bill_base * random.uniform(0.8, 1.2), 2),
        "PAY_AMT4": round(bill_base * random.uniform(0.8, 1.2), 2),
        "PAY_AMT5": round(bill_base * random.uniform(0.8, 1.2), 2),
        "PAY_AMT6": round(bill_base * random.uniform(0.8, 1.2), 2),
    }


def generate_holiday_shopper() -> Tuple[str, Dict[str, Any]]:
    """Persona 2: Khách hàng chi tiêu mùa lễ hội (Hạn mức cao, chi tiêu kịch trần 80-92% nhưng trả đều)"""
    age = random.randint(30, 48)
    limit_bal = float(random.choice([100000, 150000, 200000, 250000]))
    bill_base = limit_bal * random.uniform(0.80, 0.92)  # Seasonal shopping surge

    return "Holiday Shopping Spurt", {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([1, 2]),
        "MARRIAGE": random.choice([1, 2]),
        "AGE": age,
        "PAY_0": random.choice([0, -1, 0]),
        "PAY_2": 0,
        "PAY_3": 0,
        "PAY_4": 0,
        "PAY_5": 0,
        "PAY_6": 0,
        "BILL_AMT1": round(bill_base, 2),
        "BILL_AMT2": round(bill_base * 0.92, 2),
        "BILL_AMT3": round(bill_base * 0.75, 2),
        "BILL_AMT4": round(bill_base * 0.50, 2),
        "BILL_AMT5": round(bill_base * 0.40, 2),
        "BILL_AMT6": round(bill_base * 0.35, 2),
        "PAY_AMT1": round(bill_base * 0.35, 2),  # Substantial payment
        "PAY_AMT2": round(bill_base * 0.30, 2),
        "PAY_AMT3": round(bill_base * 0.30, 2),
        "PAY_AMT4": round(bill_base * 0.25, 2),
        "PAY_AMT5": round(bill_base * 0.25, 2),
        "PAY_AMT6": round(bill_base * 0.25, 2),
    }


def generate_genz_freelancer() -> Tuple[str, Dict[str, Any]]:
    """Persona 3: Gen-Z Freelancer / Gig Worker (19-25 tuổi, trễ hạn nhẹ PAY_0=1 do chu kỳ nhận thù lao)"""
    age = random.randint(19, 25)
    limit_bal = float(random.choice([20000, 30000, 40000, 50000]))
    bill_base = limit_bal * random.uniform(0.35, 0.65)
    pay_0 = random.choice([1, 1, 0, 1])

    return "Gen-Z Gig Freelancer", {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([2, 3]),
        "MARRIAGE": 2,  # Single
        "AGE": age,
        "PAY_0": pay_0,
        "PAY_2": random.choice([0, 1, -1]),
        "PAY_3": 0,
        "PAY_4": 0,
        "PAY_5": 0,
        "PAY_6": 0,
        "BILL_AMT1": round(bill_base * random.uniform(0.95, 1.15), 2),
        "BILL_AMT2": round(bill_base * random.uniform(0.9, 1.1), 2),
        "BILL_AMT3": round(bill_base * random.uniform(0.8, 1.0), 2),
        "BILL_AMT4": round(bill_base * random.uniform(0.7, 0.9), 2),
        "BILL_AMT5": round(bill_base * random.uniform(0.6, 0.8), 2),
        "BILL_AMT6": round(bill_base * random.uniform(0.5, 0.7), 2),
        "PAY_AMT1": round(bill_base * random.uniform(0.3, 0.7), 2),
        "PAY_AMT2": round(bill_base * random.uniform(0.4, 0.8), 2),
        "PAY_AMT3": round(bill_base * random.uniform(0.5, 0.9), 2),
        "PAY_AMT4": round(bill_base * random.uniform(0.5, 0.9), 2),
        "PAY_AMT5": round(bill_base * random.uniform(0.5, 0.9), 2),
        "PAY_AMT6": round(bill_base * random.uniform(0.5, 0.9), 2),
    }


def generate_speculator() -> Tuple[str, Dict[str, Any]]:
    """Persona 4: Khách hàng đầu cơ / Nợ quá hạn nguy hiểm (Đòn bẩy > 95%, PAY_0 >= 2)"""
    age = random.randint(28, 48)
    limit_bal = float(random.choice([50000, 80000, 100000]))
    bill_base = limit_bal * random.uniform(0.95, 0.99)

    return "Over-leveraged Speculator", {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([1, 2, 3]),
        "MARRIAGE": random.choice([1, 2]),
        "AGE": age,
        "PAY_0": random.choice([2, 3, 2]),
        "PAY_2": random.choice([2, 2, 1]),
        "PAY_3": 2,
        "PAY_4": 1,
        "PAY_5": 0,
        "PAY_6": 0,
        "BILL_AMT1": round(bill_base, 2),
        "BILL_AMT2": round(bill_base * 0.98, 2),
        "BILL_AMT3": round(bill_base * 0.96, 2),
        "BILL_AMT4": round(bill_base * 0.92, 2),
        "BILL_AMT5": round(bill_base * 0.88, 2),
        "BILL_AMT6": round(bill_base * 0.85, 2),
        "PAY_AMT1": round(bill_base * 0.04, 2),  # Token minimum payment
        "PAY_AMT2": round(bill_base * 0.04, 2),
        "PAY_AMT3": round(bill_base * 0.04, 2),
        "PAY_AMT4": round(bill_base * 0.04, 2),
        "PAY_AMT5": round(bill_base * 0.04, 2),
        "PAY_AMT6": round(bill_base * 0.04, 2),
    }


def generate_recovering_borrower() -> Tuple[str, Dict[str, Any]]:
    """Persona 5: Khách hàng đang phục hồi tín nhiệm (Trễ hạn quá khứ 6 tháng trước, nhưng gần đây chuẩn mực)"""
    age = random.randint(32, 46)
    limit_bal = float(random.choice([60000, 80000, 120000]))
    bill_base = limit_bal * random.uniform(0.3, 0.45)

    return "Rebuilding Disciplined Borrower", {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([1, 2]),
        "MARRIAGE": 1,
        "AGE": age,
        "PAY_0": 0,
        "PAY_2": 0,
        "PAY_3": 0,
        "PAY_4": -1,
        "PAY_5": 1,
        "PAY_6": 2,  # Past late payment
        "BILL_AMT1": round(bill_base * 0.7, 2),
        "BILL_AMT2": round(bill_base * 0.8, 2),
        "BILL_AMT3": round(bill_base * 0.9, 2),
        "BILL_AMT4": round(bill_base * 1.0, 2),
        "BILL_AMT5": round(bill_base * 1.1, 2),
        "BILL_AMT6": round(bill_base * 1.2, 2),
        "PAY_AMT1": round(bill_base * 0.4, 2),
        "PAY_AMT2": round(bill_base * 0.4, 2),
        "PAY_AMT3": round(bill_base * 0.35, 2),
        "PAY_AMT4": round(bill_base * 0.3, 2),
        "PAY_AMT5": round(bill_base * 0.2, 2),
        "PAY_AMT6": round(bill_base * 0.2, 2),
    }


def sample_persona_by_mode(mode: str) -> Tuple[str, Dict[str, Any]]:
    r = random.random()
    if mode == "normal":
        if r < 0.75:
            return generate_traditional_worker()
        elif r < 0.85:
            return generate_holiday_shopper()
        elif r < 0.95:
            return generate_genz_freelancer()
        else:
            return generate_speculator()

    elif mode == "holiday_spike":
        if r < 0.60:
            return generate_holiday_shopper()
        elif r < 0.85:
            return generate_traditional_worker()
        else:
            return generate_genz_freelancer()

    elif mode == "campaign_drift":
        if r < 0.75:
            return generate_genz_freelancer()
        elif r < 0.90:
            return generate_traditional_worker()
        else:
            return generate_speculator()

    elif mode == "fraud_attack":
        if r < 0.70:
            return generate_speculator()
        elif r < 0.85:
            return generate_genz_freelancer()
        else:
            return generate_traditional_worker()

    else:
        return generate_traditional_worker()


def execute_simulation_batch(mode: str, count: int, delay: float) -> Dict[str, Any]:
    print("\n" + "=" * 70)
    print(f"🚀 INITIATING AGENT PERSONA STREAM | REGIME: {mode.upper()}")
    print(f"Target: {API_URL} | Total Inferences: {count} | Latency Delay: {delay}s")
    print("=" * 70)

    stats = {
        "APPROVE": 0, "REVIEW": 0, "DECLINE": 0, "ERRORS": 0,
        "APPROVED_VOL": 0.0, "DECLINED_VOL": 0.0,
    }
    latencies = []

    for i in range(1, count + 1):
        persona_name, payload = sample_persona_by_mode(mode)

        try:
            resp = requests.post(API_URL, json=payload, timeout=5.0)
            if resp.status_code == 200:
                res = resp.json()
                decision = res["risk_decision"]
                prob = res["default_probability"]
                score = res.get("credit_score", 0)
                tier = res.get("credit_tier", "N/A")
                rec_limit = res.get("recommended_limit_ntd", 0.0)
                factors = res.get("top_risk_factors", [])
                primary_factor = factors[0] if factors else "Standard profile"
                lat = res["latency_ms"]

                latencies.append(lat)
                stats[decision] += 1
                if decision == "APPROVE":
                    stats["APPROVED_VOL"] += rec_limit
                elif decision == "DECLINE":
                    stats["DECLINED_VOL"] += payload["LIMIT_BAL"]

                icon = (
                    "🟢" if decision == "APPROVE"
                    else ("🟡" if decision == "REVIEW" else "🔴")
                )
                print(
                    f"[{i:03d}/{count:03d}] {icon} [{decision:7s}] "
                    f"FICO: {score} ({tier:9s}) | Prob: {prob:0.2f} | "
                    f"{persona_name:24s} | Driver: {primary_factor}"
                )
            else:
                stats["ERRORS"] += 1
                print(f"[{i:03d}/{count:03d}] ❌ HTTP {resp.status_code}: {resp.text}")
        except Exception as exc:
            stats["ERRORS"] += 1
            print(f"[{i:03d}/{count:03d}] ❌ Error: {exc}")

        if delay > 0:
            time.sleep(delay)

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    print("\n--- BATCH TELEMETRY SUMMARY ---")
    print(f"  Regime:             {mode}")
    print(f"  Approved:           {stats['APPROVE']} ({stats['APPROVE'] / count * 100:.1f}%)")
    print(f"  Review:             {stats['REVIEW']} ({stats['REVIEW'] / count * 100:.1f}%)")
    print(f"  Declined:           {stats['DECLINE']} ({stats['DECLINE'] / count * 100:.1f}%)")
    print(f"  Approved Credit:    ${stats['APPROVED_VOL']:,.0f} NTD")
    print(f"  Blocked Exposure:   ${stats['DECLINED_VOL']:,.0f} NTD")
    print(f"  Avg Latency:        {avg_lat:.2f} ms")
    return stats


def run_staged_progression(requests_per_stage: int = 30, delay: float = 0.02):
    print("=" * 70)
    print("🎬 STARTING 4-STAGE CONTINUOUS PRODUCTION DRIFT SIMULATION")
    print("=" * 70)

    stages = [
        ("normal", "Stage 1: Traditional Prime Borrowers (Steady State)"),
        ("holiday_spike", "Stage 2: Holiday Shopping Spurt (High Utilization Shock)"),
        ("campaign_drift", "Stage 3: Gen-Z Acquisition Campaign (Demographic & Payment Drift)"),
        ("fraud_attack", "Stage 4: Coordinated Delinquency Attack (Default Rate Spike)"),
    ]

    for mode, label in stages:
        print(f"\n>>> Transitioning to {label} <<<")
        execute_simulation_batch(mode=mode, count=requests_per_stage, delay=delay)
        time.sleep(1.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Advanced Multi-Persona & Behavioral Evolution Traffic Simulator"
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "holiday_spike", "campaign_drift", "fraud_attack", "staged_progression"],
        default="normal",
        help="Market regime or staged progression",
    )
    parser.add_argument(
        "--count", type=int, default=40, help="Number of simulated applications per batch"
    )
    parser.add_argument(
        "--delay", type=float, default=0.02, help="Delay between applications in seconds"
    )
    args = parser.parse_args()

    if args.mode == "staged_progression":
        run_staged_progression(requests_per_stage=args.count, delay=args.delay)
    else:
        execute_simulation_batch(mode=args.mode, count=args.count, delay=args.delay)

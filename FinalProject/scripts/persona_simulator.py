"""
Script: persona_simulator.py
Agent-Based Traffic & Persona Simulator for Credit Default Risk Scoring API.

Simulates realistic, persona-driven production traffic across 3 archetypes:
1. Persona 1: The Traditional Corporate Worker (Stable salary, age 35-50, high limit, pays on time)
2. Persona 2: The Gen-Z Freelancer (Gig worker, age 18-25, weekly pay, delay PAY_0=1 but recovers)
3. Persona 3: The Over-leveraged Speculator (High debt-to-limit ratio, maxed utilization, high default rate)

Modes:
- 'normal': Business-as-usual stream (85% Persona 1, 10% Persona 2, 5% Persona 3) -> PSI < 0.10 (Green)
- 'campaign_drift': Viral Gen-Z Campaign (75% Persona 2, 20% Persona 1, 5% Persona 3) -> PSI >= 0.25 (Red Alert!)
"""

import argparse
import random
import time
import requests
from typing import Dict, Any

API_URL = "http://localhost:18020/predict"


def generate_traditional_worker() -> Dict[str, Any]:
    """Persona 1: Dân công sở truyền thống (35-50 tuổi, tài chính ổn định)"""
    age = random.randint(35, 52)
    limit_bal = float(random.choice([150000, 200000, 250000, 300000, 400000]))
    bill_base = limit_bal * random.uniform(0.05, 0.25)

    return {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([1, 2]),  # Graduate or University
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


def generate_genz_freelancer() -> Dict[str, Any]:
    """Persona 2: Giới trẻ Gen-Z / Freelancer (18-25 tuổi, thu nhập theo dự án/tuần)"""
    age = random.randint(19, 25)
    limit_bal = float(random.choice([20000, 30000, 40000, 50000]))
    bill_base = limit_bal * random.uniform(0.3, 0.6)

    # Gen-Z often has payment delay PAY_0=1 due to weekly pay cycles, but later pays
    pay_0 = random.choice([1, 1, 0, 2])

    return {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([2, 3]),  # University student or High School
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
        "PAY_AMT1": round(bill_base * random.uniform(0.3, 0.8), 2),
        "PAY_AMT2": round(bill_base * random.uniform(0.4, 0.9), 2),
        "PAY_AMT3": round(bill_base * random.uniform(0.5, 1.0), 2),
        "PAY_AMT4": round(bill_base * random.uniform(0.5, 1.0), 2),
        "PAY_AMT5": round(bill_base * random.uniform(0.5, 1.0), 2),
        "PAY_AMT6": round(bill_base * random.uniform(0.5, 1.0), 2),
    }


def generate_speculator() -> Dict[str, Any]:
    """Persona 3: Khách hàng chi tiêu mạo hiểm / Đòn bẩy nợ cao (Over-leveraged)"""
    age = random.randint(28, 48)
    limit_bal = float(random.choice([50000, 80000, 100000]))
    bill_base = limit_bal * random.uniform(0.90, 0.99)  # Maxed out limit

    return {
        "LIMIT_BAL": limit_bal,
        "SEX": random.choice([1, 2]),
        "EDUCATION": random.choice([1, 2, 3]),
        "MARRIAGE": random.choice([1, 2]),
        "AGE": age,
        "PAY_0": random.choice([2, 3, 2, 1]),
        "PAY_2": random.choice([2, 2, 1]),
        "PAY_3": 2,
        "PAY_4": 1,
        "PAY_5": 0,
        "PAY_6": 0,
        "BILL_AMT1": round(bill_base, 2),
        "BILL_AMT2": round(bill_base * random.uniform(0.95, 1.02), 2),
        "BILL_AMT3": round(bill_base * random.uniform(0.9, 0.98), 2),
        "BILL_AMT4": round(bill_base * random.uniform(0.85, 0.95), 2),
        "BILL_AMT5": round(bill_base * random.uniform(0.8, 0.9), 2),
        "BILL_AMT6": round(bill_base * random.uniform(0.75, 0.85), 2),
        "PAY_AMT1": round(bill_base * 0.05, 2),  # Only paying minimum interest
        "PAY_AMT2": round(bill_base * 0.05, 2),
        "PAY_AMT3": round(bill_base * 0.05, 2),
        "PAY_AMT4": round(bill_base * 0.05, 2),
        "PAY_AMT5": round(bill_base * 0.05, 2),
        "PAY_AMT6": round(bill_base * 0.05, 2),
    }


def simulate_traffic(mode: str = "normal", count: int = 50, delay: float = 0.05):
    print("=" * 65)
    print("🚀 INITIATING AGENT PERSONA TRAFFIC SIMULATION")
    print(f"Target: {API_URL}")
    print(f"Mode: {mode.upper()} | Total Requests: {count} | Delay: {delay}s")
    print("=" * 65)

    stats = {"APPROVE": 0, "REVIEW": 0, "DECLINE": 0, "ERRORS": 0}
    latencies = []

    for i in range(1, count + 1):
        # Pick persona based on simulation mode
        if mode == "normal":
            # 85% Traditional, 10% Gen-Z, 5% Speculator
            r = random.random()
            if r < 0.85:
                persona_name = "Traditional Worker (35-50yo)"
                payload = generate_traditional_worker()
            elif r < 0.95:
                persona_name = "Gen-Z Freelancer (18-25yo)"
                payload = generate_genz_freelancer()
            else:
                persona_name = "Over-leveraged Speculator"
                payload = generate_speculator()
        else:
            # Campaign Shock: 75% Gen-Z, 20% Traditional, 5% Speculator
            r = random.random()
            if r < 0.75:
                persona_name = "Gen-Z Freelancer (18-25yo)"
                payload = generate_genz_freelancer()
            elif r < 0.95:
                persona_name = "Traditional Worker (35-50yo)"
                payload = generate_traditional_worker()
            else:
                persona_name = "Over-leveraged Speculator"
                payload = generate_speculator()

        try:
            resp = requests.post(API_URL, json=payload, timeout=5.0)
            if resp.status_code == 200:
                res = resp.json()
                decision = res["risk_decision"]
                prob = res["default_probability"]
                lat = res["latency_ms"]
                latencies.append(lat)
                stats[decision] += 1

                # Visual output
                icon = (
                    "🟢"
                    if decision == "APPROVE"
                    else ("🟡" if decision == "REVIEW" else "🔴")
                )
                age_val = payload["AGE"]
                lim_val = payload["LIMIT_BAL"]
                print(
                    f"[{i:03d}/{count}] {icon} [{decision:7s}] Prob: {prob:0.2f} | "
                    f"Latency: {lat:4.1f}ms | Persona: {persona_name} (Age: {age_val}, Limit: {lim_val:,.0f})"
                )
            else:
                stats["ERRORS"] += 1
                print(f"[{i:03d}/{count}] ❌ HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            stats["ERRORS"] += 1
            print(f"[{i:03d}/{count}] ❌ Request failed: {e}")

        if delay > 0:
            time.sleep(delay)

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    print("\n" + "=" * 65)
    print("📊 SIMULATION SUMMARY")
    print(f"  Mode: {mode}")
    print(f"  Approved: {stats['APPROVE']} ({stats['APPROVE']/count*100:.1f}%)")
    print(f"  Review:   {stats['REVIEW']} ({stats['REVIEW']/count*100:.1f}%)")
    print(f"  Declined: {stats['DECLINE']} ({stats['DECLINE']/count*100:.1f}%)")
    print(f"  Errors:   {stats['ERRORS']}")
    print(f"  Avg Inference Latency: {avg_lat:.2f} ms")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Persona-driven Traffic Simulator for MLOps"
    )
    parser.add_argument(
        "--mode",
        choices=["normal", "campaign_drift"],
        default="normal",
        help="Simulation mode",
    )
    parser.add_argument(
        "--count", type=int, default=30, help="Number of simulated requests"
    )
    parser.add_argument(
        "--delay", type=float, default=0.05, help="Delay between requests in seconds"
    )
    args = parser.parse_args()

    simulate_traffic(mode=args.mode, count=args.count, delay=args.delay)

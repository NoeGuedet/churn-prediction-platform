#!/usr/bin/env python3
"""
load_test.py  -  Load test script for the churn prediction platform.

Sends random customer profiles from data/churn.csv to the inference
endpoint at a fixed rate and reports success rate and latency metrics.

Usage:
  python scripts/load_test.py --level nominal --url http://HOST:PORT/predict
  python scripts/load_test.py --level charge  --url http://HOST:PORT/predict
  python scripts/load_test.py --level stress  --url http://localhost:8002/predict
  python scripts/load_test.py --level extreme --rate 400 --url http://HOST:PORT/predict

Get the URL with:
  minikube service inference-svc -n projet-TRIGRAMME --url
"""

import argparse
import concurrent.futures
import csv
import random
import sys
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Predefined load levels
# ---------------------------------------------------------------------------
LEVELS = {
    "nominal": {"rate": 10,  "duration": 300},
    "charge":  {"rate": 50,  "duration": 300},
    "stress":  {"rate": 150, "duration": 300},
    "extreme": {"rate": None, "duration": 300},  # rate provided by --rate
}

DATA_PATH = Path(__file__).parent.parent / "data" / "churn.csv"

# Columns excluded from the payload (target + identifier)
EXCLUDE = {"Churn", "customerID"}


# ---------------------------------------------------------------------------
# Request sender
# ---------------------------------------------------------------------------

def send_churn(url: str, row: dict) -> tuple[int, float]:
    """
    Sends a customer profile as JSON.
    Expected endpoint: POST /predict
    Payload: dict with the Telco dataset feature columns
             (all columns except the 'Churn' target).
    Expected response: JSON {"churn_probability": float, "recommended_offer": str}
    """
    t0 = time.monotonic()
    resp = requests.post(url, json=row, timeout=10)
    return resp.status_code, time.monotonic() - t0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> list:
    """Loads the customer profile pool from churn.csv."""
    if not DATA_PATH.exists():
        sys.exit(f"[ERROR] CSV file not found: {DATA_PATH}")
    with open(DATA_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [{k: v for k, v in row.items() if k not in EXCLUDE}
                for row in reader]
    if not rows:
        sys.exit("[ERROR] No rows found in churn.csv")
    print(f"[INFO] {len(rows)} customer profiles loaded from {DATA_PATH}")
    return rows


# ---------------------------------------------------------------------------
# Test loop
# ---------------------------------------------------------------------------

def run_test(rate: int, duration: int, url: str) -> dict:
    """
    Runs the load test and returns the metrics.
    rate    : requests per minute
    duration: duration in seconds
    """
    data = load_data()

    def task():
        return send_churn(url, random.choice(data))

    interval = 60.0 / rate
    end_time = time.monotonic() + duration

    futures = []
    statuses = []
    latencies = []

    print(f"[TEST] case=churn  rate={rate} req/min  duration={duration}s")
    print(f"[TEST] URL: {url}")
    print(f"[TEST] Start: {time.strftime('%H:%M:%S')}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        while time.monotonic() < end_time:
            futures.append(executor.submit(task))
            time.sleep(interval)

        for f in concurrent.futures.as_completed(futures):
            try:
                status, latency = f.result()
            except requests.exceptions.Timeout:
                status, latency = 408, 30.0
            except Exception:
                status, latency = 0, 30.0
            statuses.append(status)
            latencies.append(latency)

    n = len(latencies)
    n200 = statuses.count(200)
    sorted_lat = sorted(latencies)

    results = {
        "case":            "churn",
        "level":           f"extreme (rate={rate})" if rate not in (10, 50, 150) else {
                               10: "nominal", 50: "charge", 150: "stress"
                           }[rate],
        "rate_configured": rate,
        "duration_s":      duration,
        "total_requests":  n,
        "success_200":     n200,
        "failure":         n - n200,
        "success_rate_pct": round(n200 / n * 100, 1) if n else 0,
        "latency_avg_s":   round(sum(latencies) / n, 3) if n else 0,
        "latency_p95_s":   round(sorted_lat[max(0, int(0.95 * n) - 1)], 3) if n else 0,
        "latency_max_s":   round(sorted_lat[-1], 3) if n else 0,
    }
    return results


def print_results(r: dict) -> None:
    print("\n" + "=" * 55)
    print(f"  RESULTS  -  {r['case'].upper()} / {r['level'].upper()}")
    print("=" * 55)
    print(f"  Configured rate   : {r['rate_configured']} req/min")
    print(f"  Duration          : {r['duration_s']}s")
    print(f"  Requests sent     : {r['total_requests']}")
    print(f"  Success (HTTP 200): {r['success_200']}")
    print(f"  Failures          : {r['failure']}")
    print(f"  Success rate      : {r['success_rate_pct']}%")
    print(f"  Avg latency       : {r['latency_avg_s']}s")
    print(f"  P95 latency       : {r['latency_p95_s']}s")
    print(f"  Max latency       : {r['latency_max_s']}s")
    print("=" * 55)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Load test script for the churn prediction platform."
    )
    parser.add_argument(
        "--level",
        choices=["nominal", "charge", "stress", "extreme"],
        required=True,
        help="Load level"
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=None,
        help="Requests per minute (required for --level extreme)"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Full URL of the inference service /predict endpoint"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="Test duration in seconds (default: 300)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    level_config = LEVELS[args.level]
    rate = args.rate if args.level == "extreme" else level_config["rate"]

    if args.level == "extreme" and rate is None:
        sys.exit("[ERROR] --level extreme requires --rate N (e.g. --rate 400)")

    results = run_test(
        rate=rate,
        duration=args.duration,
        url=args.url,
    )
    print_results(results)


if __name__ == "__main__":
    main()

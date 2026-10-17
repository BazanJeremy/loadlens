"""Hand measurement of the SUT: fire N requests at a fixed concurrency and print latency
percentiles. A stopwatch to check that each regression slows the API down, not a load tool.

    python sut/tools/measure.py --scenario statement --requests 300 --concurrency 1
"""

import argparse
import json
import math
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

SCENARIOS = ("statement", "payment-read", "payment-write")
# Matches the default seed: accounts 1..999 hold funds (1000 is the empty one), 100 000 payments.
FUNDED_ACCOUNTS = 999
MERCHANTS = 5_000
SEEDED_PAYMENTS = 100_000


def nearest_rank(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value with at least q% of samples at or below it."""
    rank = max(1, math.ceil(q / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def build_request(scenario: str, rng: random.Random) -> tuple[str, str, dict | None]:
    if scenario == "statement":
        return "GET", f"/accounts/{rng.randint(1, FUNDED_ACCOUNTS)}/statement", None
    if scenario == "payment-read":
        return "GET", f"/payments/{rng.randint(1, SEEDED_PAYMENTS)}", None
    body = {
        "account_id": rng.randint(1, FUNDED_ACCOUNTS),
        "merchant_id": rng.randint(1, MERCHANTS),
        "amount_cents": 100,
    }
    return "POST", "/payments", body


def run(base_url: str, scenario: str, requests: int, concurrency: int, seed: int) -> dict:
    rng = random.Random(seed)
    plan = [build_request(scenario, rng) for _ in range(requests)]
    local = threading.local()

    def client() -> httpx.Client:
        if not hasattr(local, "client"):
            local.client = httpx.Client(base_url=base_url, timeout=60)
        return local.client

    def fire(request: tuple[str, str, dict | None]) -> tuple[float, bool]:
        method, path, body = request
        started = time.perf_counter()
        try:
            ok = client().request(method, path, json=body).is_success
        except httpx.HTTPError:
            ok = False
        return (time.perf_counter() - started) * 1000, ok

    wall_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(fire, plan))
    wall = time.perf_counter() - wall_started

    latencies = sorted(ms for ms, _ in results)
    return {
        "scenario": scenario,
        "requests": requests,
        "concurrency": concurrency,
        "errors": sum(1 for _, ok in results if not ok),
        "p50_ms": round(nearest_rank(latencies, 50), 1),
        "p95_ms": round(nearest_rank(latencies, 95), 1),
        "p99_ms": round(nearest_rank(latencies, 99), 1),
        "max_ms": round(latencies[-1], 1),
        "throughput_rps": round(requests / wall, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=50, help="requests fired and discarded first")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    if args.warmup:
        run(args.base_url, args.scenario, args.warmup, args.concurrency, args.seed + 1)
    result = run(args.base_url, args.scenario, args.requests, args.concurrency, args.seed)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

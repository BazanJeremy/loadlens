"""Functional tests of the payments API, run over HTTP against the docker compose stack.

    docker compose up -d --wait
    python -m pytest sut/tests

An unreachable API is a test failure, never a skip.
"""

import os
import sys
from pathlib import Path

import httpx
import pytest

# The seed generators and the config parser are standard-library modules of the SUT.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payments_api.seed_data import SeedConfig  # noqa: E402

BASE_URL = os.environ.get("SUT_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def seed_config() -> SeedConfig:
    return SeedConfig.from_env(os.environ)


@pytest.fixture(scope="session")
def api() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        try:
            client.get("/health").raise_for_status()
        except httpx.HTTPError as exc:
            pytest.fail(
                f"SUT not reachable at {BASE_URL} ({exc}). "
                "Start it with: docker compose up -d --wait",
                pytrace=False,
            )
        yield client

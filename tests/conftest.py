"""Shared pytest fixtures.

Everything is deterministic and offline. No test touches the network.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cce.config import load_policy, load_scenarios, load_universe
from tests.fixtures import synthetic

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _deterministic() -> None:
    """Seed the global RNG so an unseeded call cannot make a test flaky."""
    np.random.seed(42)


@pytest.fixture(scope="session")
def universe():
    return load_universe(PROJECT_ROOT / "config" / "universe.yaml")


@pytest.fixture(scope="session")
def policy():
    return load_policy(PROJECT_ROOT / "config" / "policy.yaml")


@pytest.fixture(scope="session")
def scenarios():
    return load_scenarios(PROJECT_ROOT / "config" / "scenarios.yaml")


@pytest.fixture
def demo_universe():
    return synthetic.demo_universe()


@pytest.fixture
def demo_portfolio():
    return synthetic.demo_portfolio()


@pytest.fixture
def healthy_weights():
    return synthetic.healthy_weights()


@pytest.fixture
def concentrated_weights():
    return synthetic.concentrated_weights()

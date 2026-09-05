"""Stress scenario loading.

Spec: docs/07-RISK-POLICY.md section 7, docs/08-FINANCIAL-METHODS.md section 13.

The :class:`~cce.contracts.control.Scenario` contract itself lives in
``cce/contracts/`` alongside :class:`~cce.contracts.control.StressResult`,
because the config loader and the stress engine both need it. This module is
the loader only.

There used to be a second, identical definition (``ScenarioDefinition``) with
its own loader in ``cce/config.py``, reading the same YAML file. Two
definitions of one thing is how they drift apart; ``cce.config.load_scenarios``
is now the single loader and this module re-exports it.
"""

from __future__ import annotations

from ..config import load_scenarios
from ..contracts import LIQUIDITY_KEY, Scenario

__all__ = ["LIQUIDITY_KEY", "Scenario", "load_scenarios"]

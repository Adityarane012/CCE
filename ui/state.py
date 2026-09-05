"""Service wiring and session state.

Spec: docs/02-ARCHITECTURE.md section 2.

The UI touches ``cce.services`` and ``cce.contracts`` and nothing else. No
engine imports, no data providers, no repository. Every number rendered was
computed behind this boundary (INV-12).

The ServiceContext is cached for the session: rebuilding it per interaction
would reload the price panel on every click, and — worse — a proposal made
against one panel could be approved against another.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from cce.contracts import Candidate, CandidateRole, PortfolioState, RiskSnapshot
from cce.services import (
    ApprovalService,
    OptimizationService,
    PolicyService,
    PortfolioService,
    ReplayService,
    RiskService,
    ServiceContext,
    StressService,
)

__all__ = ["Services", "clear_cycle", "get_services", "session"]


@dataclass(frozen=True)
class Services:
    """Every service, sharing one context."""

    ctx: ServiceContext
    portfolio: PortfolioService
    risk: RiskService
    optimization: OptimizationService
    approval: ApprovalService
    stress: StressService
    replay: ReplayService
    policy: PolicyService

    def state(self) -> PortfolioState:
        return self.portfolio.get_current_state()

    def snapshot(self, state: PortfolioState) -> RiskSnapshot:
        return self.risk.get_snapshot(state)


@st.cache_resource(show_spinner="Loading market data and policy…")
def get_services() -> Services:
    """Build the services once per session.

    Cached as a RESOURCE, not data: it holds a database connection, and
    Streamlit must not attempt to copy or pickle it between reruns.
    """
    ctx = ServiceContext.build()
    return Services(
        ctx=ctx,
        portfolio=PortfolioService(ctx),
        risk=RiskService(ctx),
        optimization=OptimizationService(ctx),
        approval=ApprovalService(ctx),
        stress=StressService(ctx),
        replay=ReplayService(ctx),
        policy=PolicyService(ctx),
    )


def session() -> dict:
    """The current decision cycle, if one has been run.

    Held in session state so navigating between pages does not silently
    re-run the optimizer and hand the user a different proposal than the one
    they were looking at.
    """
    if "cce" not in st.session_state:
        st.session_state["cce"] = {
            "cycle": None,
            "last_snapshot": None,
            "approved": None,
            "error": None,
        }
    return st.session_state["cce"]


def clear_cycle() -> None:
    """Drop the current proposal. Used after a decision is closed."""
    s = session()
    s["cycle"] = None
    s["error"] = None


def candidate_of(role: CandidateRole) -> Candidate | None:
    cycle = session()["cycle"]
    return cycle.candidate(role) if cycle else None

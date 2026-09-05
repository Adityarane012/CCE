"""CCE dashboard entry point.

Run with::

    ./.venv/Scripts/streamlit.exe run app.py

Navigation is a sidebar radio dispatching to ``render(svc)`` per page rather
than Streamlit's ``pages/`` directory convention. That keeps every page a
plain importable function, which is what lets the architecture tests check
the layer rules over ``ui/`` at all.

The current risk-state chip is visible in the sidebar on EVERY page: a risk
manager should never have to navigate to discover the portfolio is RED
(docs/09-UI-SPEC.md section 3).
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="CCE — Capital Control Engine",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from ui.components.indicators import state_chip
from ui.pages import (
    backtest,
    optimizer,
    overview,
    portfolio,
    replay,
    risk,
    settings,
    stress,
)
from ui.state import get_services

PAGES = {
    "Executive Overview": overview.render,
    "Optimizer — Safe vs Optimal": optimizer.render,
    "Risk Control Center": risk.render,
    "Portfolio & Exposure": portfolio.render,
    "Stress Lab": stress.render,
    "Backtesting": backtest.render,
    "Decision Replay": replay.render,
    "Policy & Settings": settings.render,
}


def _sidebar_state(svc) -> None:
    """The state chip, on every page."""
    try:
        snapshot = svc.snapshot(svc.state())
    except Exception:  # noqa: BLE001 - the chip must never break navigation
        st.sidebar.caption("Risk state unavailable")
        return
    st.sidebar.markdown(
        f"**Portfolio state**<br>{state_chip(snapshot.risk_state)}",
        unsafe_allow_html=True,
    )
    st.sidebar.caption(
        f"Data as of {svc.ctx.market_data.as_of_date} · "
        f"{svc.ctx.market_data.provider.value}"
    )
    st.sidebar.divider()


def main() -> None:
    st.sidebar.title("CCE")
    st.sidebar.caption("Optimal ≠ Safe")

    try:
        svc = get_services()
    except Exception as exc:  # noqa: BLE001
        st.error(
            "The application could not start. This usually means market data "
            "or the policy could not be loaded.",
            icon="⛔",
        )
        st.exception(exc)
        st.stop()   # NoReturn; nothing below runs

    _sidebar_state(svc)
    choice = st.sidebar.radio("Page", list(PAGES), label_visibility="collapsed")
    st.sidebar.divider()
    st.sidebar.caption(
        "Decision-support prototype. Simulated execution only — no broker "
        "connection, no real orders."
    )

    PAGES[choice](svc)


main()

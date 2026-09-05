"""Plotly figures.

Spec: docs/09-UI-SPEC.md sections 5 and 2.1.

These render values the services computed. Nothing here derives a metric —
the UI has no arithmetic beyond turning a fraction into a percentage for an
axis label (INV-12).
"""

from __future__ import annotations

import plotly.graph_objects as go

__all__ = [
    "STRATEGY_LABELS",
    "allocation_donut",
    "drawdown_curves",
    "equity_curves",
    "sector_vs_cap",
    "weight_vs_risk_contribution",
]

_WEIGHT_COLOUR = "#2B6CB0"
_RC_COLOUR = "#C53030"
_CAP_COLOUR = "#6B7280"
_GRID = "#E5E7EB"


def _layout(fig: go.Figure, height: int, title: str = "") -> go.Figure:
    fig.update_layout(
        title=title or None,
        height=height,
        margin={"l": 10, "r": 10, "t": 40 if title else 10, "b": 10},
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        font={"size": 13},
    )
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_GRID)
    return fig


def weight_vs_risk_contribution(
    weights: dict[str, float],
    risk_contribution: dict[str, float],
) -> go.Figure:
    """The product's central visual.

    Two bars per asset: how much of the CAPITAL it holds, and how much of the
    RISK it carries. They should track each other. Where they visibly do not
    is the entire argument for having a control engine — a 24% position
    carrying 41% of portfolio risk is invisible to any weight-based limit.

    Assets are ordered by risk contribution, so the offender is at the top
    rather than wherever the alphabet put it.
    """
    assets = sorted(
        weights, key=lambda a: risk_contribution.get(a, 0.0), reverse=True
    )
    fig = go.Figure()
    fig.add_bar(
        y=assets, x=[weights.get(a, 0.0) * 100 for a in assets],
        name="Weight (capital)", orientation="h",
        marker_color=_WEIGHT_COLOUR,
        hovertemplate="%{y}: %{x:.1f}% of capital<extra></extra>",
    )
    fig.add_bar(
        y=assets, x=[risk_contribution.get(a, 0.0) * 100 for a in assets],
        name="Risk contribution", orientation="h",
        marker_color=_RC_COLOUR,
        hovertemplate="%{y}: %{x:.1f}% of risk<extra></extra>",
    )
    fig.update_layout(barmode="group", yaxis={"autorange": "reversed"})
    fig.update_xaxes(title="% of portfolio", ticksuffix="%")
    return _layout(fig, height=max(320, 42 * len(assets)))


def allocation_donut(weights: dict[str, float]) -> go.Figure:
    """Where the capital sits. Zero-weight assets are omitted, not drawn flat."""
    held = {a: w for a, w in weights.items() if w > 0}
    fig = go.Figure(
        go.Pie(
            labels=list(held),
            values=[w * 100 for w in held.values()],
            hole=0.55,
            sort=False,
            hovertemplate="%{label}: %{value:.1f}%<extra></extra>",
            textinfo="label+percent",
        )
    )
    return _layout(fig, height=340)


def sector_vs_cap(
    exposure: dict[str, float], caps: dict[str, float]
) -> go.Figure:
    """Sector weight against its configured cap.

    The cap is drawn as a marker on the same row rather than as a single
    vertical line: each sector has its own limit, and one line across the
    chart would imply they share one.
    """
    sectors = sorted(exposure, key=lambda s: exposure[s], reverse=True)
    fig = go.Figure()
    fig.add_bar(
        y=sectors, x=[exposure[s] * 100 for s in sectors],
        name="Exposure", orientation="h", marker_color=_WEIGHT_COLOUR,
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    )
    capped = [(s, caps[s]) for s in sectors if s in caps]
    if capped:
        fig.add_scatter(
            y=[s for s, _ in capped], x=[c * 100 for _, c in capped],
            mode="markers", name="Policy cap",
            marker={"symbol": "line-ns-open", "size": 18, "line": {"width": 3},
                    "color": _CAP_COLOUR},
            hovertemplate="%{y} cap: %{x:.1f}%<extra></extra>",
        )
    fig.update_layout(yaxis={"autorange": "reversed"})
    fig.update_xaxes(title="% of portfolio", ticksuffix="%")
    return _layout(fig, height=max(300, 40 * len(sectors)))


#: One colour per strategy, fixed across BOTH charts. A reader comparing the
#: equity and drawdown panels must not have to re-learn the legend.
STRATEGY_COLOURS = {
    "BUY_AND_HOLD": "#6B7280",
    "UNCONTROLLED_OPTIMIZER": "#C53030",
    "CCE_CONTROLLED": "#2B6CB0",
}

STRATEGY_LABELS = {
    "BUY_AND_HOLD": "Buy and hold",
    "UNCONTROLLED_OPTIMIZER": "Uncontrolled optimizer",
    "CCE_CONTROLLED": "CCE-controlled",
}


def equity_curves(curves: dict) -> go.Figure:
    """Three strategies overlaid, indexed to 100 at the start.

    Indexed rather than shown in rupees because the comparison is between
    SHAPES, not levels — and a rupee axis invites reading a backtest as a
    forecast of a real book.
    """
    fig = go.Figure()
    for name, series in curves.items():
        if series is None or len(series) < 2:
            continue
        fig.add_trace(go.Scatter(
            x=list(series.index),
            y=[float(v / series.iloc[0] * 100.0) for v in series],
            name=STRATEGY_LABELS.get(name, name),
            mode="lines",
            line={"width": 2, "color": STRATEGY_COLOURS.get(name)},
        ))
    fig.update_yaxes(title="Indexed to 100", ticksuffix="")
    return _layout(fig, 380)


def drawdown_curves(drawdowns: dict) -> go.Figure:
    """Peak-to-trough decline over time, three strategies overlaid.

    The series arrive already negative from the backtest module, so the area
    fills downward without this function doing arithmetic on them (INV-12).
    """
    fig = go.Figure()
    for name, series in drawdowns.items():
        if series is None or len(series) < 2:
            continue
        fig.add_trace(go.Scatter(
            x=list(series.index),
            y=[float(v) * 100.0 for v in series],
            name=STRATEGY_LABELS.get(name, name),
            mode="lines",
            fill="tozeroy",
            line={"width": 1.5, "color": STRATEGY_COLOURS.get(name)},
        ))
    fig.update_yaxes(title="Drawdown (%)", ticksuffix="%")
    return _layout(fig, 300)

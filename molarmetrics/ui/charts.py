"""Build Plotly figures from an AnalysisResult's declarative ChartSpec.

Beginner note
-------------
Charts are drawn by this fixed, trusted code from STRUCTURED tool results
(paise integers, counts, rates). The language model never writes chart code
and its prose is never parsed for numbers.

Style follows a small set of rules: one y-axis per chart (never two), thin
bars with rounded data ends, 2px lines, hairline gridlines, a legend whenever
there are two or more series, and hover tooltips with exact values.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go

from molarmetrics.analytics.results import AnalysisResult, format_value
from molarmetrics.ui import theme as T


def _compact_inr(rupees: float) -> str:
    if rupees >= 1e7:
        return f"₹{rupees / 1e7:g} Cr"
    if rupees >= 1e5:
        return f"₹{rupees / 1e5:g}L"
    if rupees >= 1e3:
        return f"₹{rupees / 1e3:g}K"
    return f"₹{rupees:g}"


def inr_ticks(max_rupees: float) -> tuple[list[float], list[str]]:
    """Clean axis ticks in Indian units (K = thousand, L = lakh, Cr = crore)."""
    if not max_rupees or max_rupees <= 0:
        return [0], ["₹0"]
    steps = [100, 200, 250, 500, 1_000, 2_000, 2_500, 5_000, 10_000, 20_000, 25_000, 50_000,
             100_000, 200_000, 250_000, 500_000, 1_000_000, 2_000_000, 2_500_000, 5_000_000,
             10_000_000, 20_000_000, 50_000_000]
    step = next((s for s in steps if max_rupees / s <= 5), steps[-1])
    values = [i * step for i in range(math.ceil(max_rupees / step) + 1)]
    return values, [_compact_inr(v) for v in values]


def build_figure(result: AnalysisResult, height: int | None = None) -> go.Figure | None:
    spec = result.chart
    if spec is None or not result.rows:
        return None
    kinds = {c.key: c.kind for c in result.columns}
    labels = [str(row.get(spec.x, "")) for row in result.rows]
    horizontal = spec.orientation == "h"
    fig = go.Figure()
    axis_kind = kinds.get(spec.y[0], "count")
    max_value = 0.0

    for key in spec.y:
        kind = kinds.get(key, "count")
        raw = [row.get(key) for row in result.rows]
        values = [None if v is None else (v / 100 if kind == "inr" else v) for v in raw]
        max_value = max([max_value] + [v for v in values if v is not None])
        hover = [format_value(v, kind) for v in raw]
        name = T.SERIES_LABELS.get(key, key)
        color = T.SERIES_COLORS.get(key, T.TEAL)
        if spec.type == "line":
            fig.add_trace(go.Scatter(
                x=labels, y=values, name=name, mode="lines+markers", connectgaps=False,
                line=dict(color=color, width=2, shape="linear"),
                marker=dict(size=8, color=color, line=dict(color=T.SURFACE, width=2)),
                customdata=hover, hovertemplate=f"%{{x}}<br>{name}: %{{customdata}}<extra></extra>",
            ))
        else:
            common = dict(name=name, marker=dict(color=color, line=dict(color=T.SURFACE, width=2)),
                          customdata=hover)
            if horizontal:
                fig.add_trace(go.Bar(
                    y=labels, x=values, orientation="h", **common,
                    text=[format_value(v, kind) for v in raw], textposition="outside", cliponaxis=False,
                    textfont=dict(color=T.TEXT_SECONDARY, size=12),
                    hovertemplate=f"%{{y}}<br>{name}: %{{customdata}}<extra></extra>",
                ))
            else:
                fig.add_trace(go.Bar(
                    x=labels, y=values, **common,
                    hovertemplate=f"%{{x}}<br>{name}: %{{customdata}}<extra></extra>",
                ))

    value_axis = dict(gridcolor=T.GRID, gridwidth=1, zeroline=True, zerolinecolor=T.BASELINE, zerolinewidth=1,
                      tickfont=dict(color=T.TEXT_MUTED, size=11), title=dict(text=""), automargin=True,
                      rangemode="tozero")
    if axis_kind == "inr":
        tickvals, ticktext = inr_ticks(max_value * (1.18 if horizontal else 1.0))
        value_axis.update(tickvals=tickvals, ticktext=ticktext)
    elif axis_kind == "percent":
        value_axis.update(ticksuffix="%")
    else:
        value_axis.update(tickformat=",d")
    category_axis = dict(showgrid=False, tickfont=dict(color=T.TEXT_SECONDARY, size=11), automargin=True,
                         linecolor=T.BASELINE, title=dict(text=""))

    if horizontal:
        category_axis.update(autorange="reversed")  # highest value at the top
        if axis_kind != "inr" and max_value:
            value_axis.update(range=[0, max_value * 1.18])  # room for tip labels
        fig.update_layout(xaxis=value_axis, yaxis=category_axis)
    else:
        if len(labels) > 12:  # e.g. 24 months: label every 3rd month so ticks stay readable
            category_axis.update(tickmode="array", tickvals=labels[::3], ticktext=labels[::3])
        fig.update_layout(xaxis=category_axis, yaxis=value_axis)

    multi = len(spec.y) >= 2
    n_bars = len(labels)
    fig.update_layout(
        # The heading is rendered by Streamlit above the chart, so no in-plot title.
        barmode="stack" if spec.type == "stacked_bar" else "group",
        bargap=0.45 if not multi else 0.3,
        bargroupgap=0.12,
        barcornerradius=4,
        showlegend=multi,
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", traceorder="normal",
                    font=dict(color=T.TEXT_SECONDARY, size=12)),
        hovermode="x unified" if (multi and not horizontal) else "closest",
        hoverlabel=dict(bgcolor=T.SURFACE, font=dict(color=T.NAVY_TEXT, family=T.FONT_FAMILY)),
        font=dict(family=T.FONT_FAMILY, color=T.TEXT_SECONDARY),
        paper_bgcolor=T.SURFACE,
        plot_bgcolor=T.SURFACE,
        margin=dict(l=8, r=24, t=36 if multi else 12, b=8),
        height=height or (max(220, 34 * n_bars + 90) if horizontal else 360),
    )
    return fig


PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}

"""
Reusable Dashboard UI Components
=================================
Streamlit rendering blocks extracted for clarity.
Each function renders a self-contained UI section.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import streamlit as st

from panopticon.core.events import EventSeed
from panopticon.core.graph import TemporalGraph
from panopticon.core.threading import FutureThread
from panopticon.dashboard.live_feed import LiveFeedState, get_status_text
from panopticon.oracle.insight import OracleReport


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------

def render_status_bar(feed_state: Optional[LiveFeedState], feed_mode: str) -> None:
    """Live feed status indicator. Shows polling state, hotspot count, errors."""
    if feed_mode != "live" or feed_state is None:
        return

    status_text = get_status_text(feed_state)

    color_map = {
        "LIVE": "#44ff44",
        "ERROR": "#ff4444",
        "POLLING": "#ffaa00",
        "IDLE": "#888888",
    }
    color = color_map.get(feed_state.status, "#888888")
    dot = f'<span style="color:{color};font-size:18px">&#9679;</span>'

    st.markdown(
        f'<div style="background:#0d1a0d;border:1px solid {color};'
        f'color:{color};padding:8px 15px;border-radius:4px;'
        f'font-family:Courier New,monospace;font-size:0.85em">'
        f'{dot} <b>{status_text}</b></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Alert banner
# ---------------------------------------------------------------------------

def render_alert_banner(report: Optional[OracleReport]) -> None:
    """Pinned anomaly alerts at the top of the page."""
    if not report or not report.anomalies:
        return

    for anomaly in report.anomalies:
        st.markdown(
            f'<div style="background:#1a0000;border:1px solid #660000;'
            f'color:#ff6666;padding:10px;border-radius:4px;'
            f'font-family:Courier New,monospace;font-size:0.85em;'
            f'margin-bottom:6px">'
            f'&#9889; {anomaly}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Insight cards (compact)
# ---------------------------------------------------------------------------

def render_insight_cards(report: Optional[OracleReport], max_cards: int = 8) -> None:
    """Render oracle insights as styled cards."""
    if not report or not report.insights:
        st.markdown(
            '<p style="color:#666;font-family:Courier New">No insights generated yet.</p>',
            unsafe_allow_html=True,
        )
        return

    for insight in report.insights[:max_cards]:
        border_colors = {
            "pessimistic": "#ff4444",
            "optimistic": "#44ff44",
            "wildcard": "#ffaa00",
        }
        border = border_colors.get(insight.branch_type, "#1a3a5c")
        icon = {"optimistic": "&#128994;", "pessimistic": "&#128308;", "wildcard": "&#128993;"}.get(
            insight.branch_type, "&#9898;"
        )

        chain_str = " &rarr; ".join(insight.chain[:4])
        if len(insight.chain) > 4:
            chain_str += f" &rarr; (+{len(insight.chain) - 4})"
        risks_str = ", ".join(insight.key_risks[:3]) if insight.key_risks else "&mdash;"

        st.markdown(f"""
        <div style="background:#111;border:1px solid #1a3a5c;border-left:4px solid {border};
                     border-radius:6px;padding:12px;margin:8px 0;
                     font-family:Courier New,monospace;font-size:0.82em;color:#e0e0e0">
            <b>{icon} #{insight.rank}</b> &mdash; {insight.summary}<br>
            <span style="color:#4da6ff">
                Chain: {chain_str}<br>
                Risks: {risks_str}<br>
                Timeline: {insight.timeline_hours}h | {insight.branch_type}
            </span>
            {"<br><em style='color:#888'>" + insight.divergence_note + "</em>" if insight.divergence_note else ""}
        </div>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Feed log
# ---------------------------------------------------------------------------

def render_feed_log(feed_state: Optional[LiveFeedState], max_entries: int = 15) -> None:
    """Scrollable log of polling activity."""
    if not feed_state or not feed_state.feed_log:
        st.markdown(
            '<p style="color:#666;font-family:Courier New">No feed activity yet.</p>',
            unsafe_allow_html=True,
        )
        return

    entries = feed_state.feed_log[-max_entries:]
    entries.reverse()  # newest first
    log_html = "<br>".join(
        f'<span style="color:#4da6ff">{e}</span>' for e in entries
    )

    st.markdown(
        f'<div style="background:#0a0a0a;border:1px solid #1a3a5c;'
        f'border-radius:4px;padding:10px;max-height:300px;overflow-y:auto;'
        f'font-family:Courier New,monospace;font-size:0.78em;line-height:1.6">'
        f'{log_html}</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------

def render_metrics_row(
    seeds: List[EventSeed],
    graph: Optional[TemporalGraph],
    threads: List[FutureThread],
    report: Optional[OracleReport],
    feed_state: Optional[LiveFeedState],
) -> None:
    """Top-line metrics bar."""
    cols = st.columns(6)

    with cols[0]:
        obs_count = len(feed_state.all_observables) if feed_state else 0
        st.metric("Observables", obs_count)

    with cols[1]:
        st.metric("Event Seeds", len(seeds))

    with cols[2]:
        st.metric("Graph Nodes", graph.node_count if graph else 0)

    with cols[3]:
        st.metric("Causal Links", graph.edge_count if graph else 0)

    with cols[4]:
        st.metric("Futures", len(threads))

    with cols[5]:
        top_prop = 0
        if report and report.insights:
            top_prop = report.insights[0].propensity_pct
        st.metric("Top Propensity", f"{top_prop:.0f}%")

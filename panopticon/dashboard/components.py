"""
Kevlar UI Components
====================
Reusable Streamlit rendering blocks — minimal, monospaced, tight.
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

_HEALTH_DOT = {
    "healthy":  "#00ff88",
    "degraded": "#ffaa00",
    "failed":   "#ff3355",
    "disabled": "#2a3545",
    "pending":  "#00d4ff",
}


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------

def render_status_bar(feed_state: Optional[LiveFeedState], feed_mode: str) -> None:
    if feed_mode != "live" or feed_state is None:
        return

    status_text = get_status_text(feed_state)
    color = {
        "LIVE": "#00ff88", "ERROR": "#ff3355",
        "POLLING": "#ffaa00", "IDLE": "#5a6a7a",
    }.get(feed_state.status, "#5a6a7a")

    st.markdown(
        f'<div class="kevlar-bar">'
        f'<span style="color:{color}">&#9679;</span> '
        f'<span style="color:{color}">{status_text}</span></div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Alert banner
# ---------------------------------------------------------------------------

def render_alert_banner(report: Optional[OracleReport]) -> None:
    if not report or not report.anomalies:
        return

    for anomaly in report.anomalies[:3]:
        st.markdown(
            f'<div class="kevlar-bar" style="border-color:#ff3355">'
            f'<span class="kevlar-danger">&#9889; {anomaly}</span></div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Insight cards
# ---------------------------------------------------------------------------

def render_insight_cards(report: Optional[OracleReport], max_cards: int = 8) -> None:
    if not report or not report.insights:
        st.markdown(
            '<div class="kevlar-card kevlar-dim">No insights yet.</div>',
            unsafe_allow_html=True,
        )
        return

    for insight in report.insights[:max_cards]:
        border = {
            "pessimistic": "#ff3355",
            "optimistic": "#00ff88",
            "wildcard": "#ffaa00",
        }.get(insight.branch_type, "#1a2535")

        tag_class = {
            "pessimistic": "kevlar-danger",
            "optimistic": "kevlar-success",
            "wildcard": "kevlar-warn",
        }.get(insight.branch_type, "kevlar-dim")

        chain_str = " &rarr; ".join(insight.chain[:3])
        if len(insight.chain) > 3:
            chain_str += f" +{len(insight.chain) - 3}"

        st.markdown(
            f'<div class="kevlar-card" style="border-left:3px solid {border}">'
            f'<span class="kevlar-tag">{insight.branch_type}</span>'
            f'<span class="kevlar-tag">#{insight.rank}</span>'
            f'<span class="kevlar-tag">{insight.timeline_hours}h</span><br>'
            f'<span style="color:#c8d6e5;font-size:0.78rem">{insight.summary}</span><br>'
            f'<span class="kevlar-dim" style="font-size:0.7rem">{chain_str}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Feed log
# ---------------------------------------------------------------------------

def render_feed_log(feed_state: Optional[LiveFeedState], max_entries: int = 20) -> None:
    if not feed_state or not feed_state.feed_log:
        st.markdown(
            '<div class="kevlar-card kevlar-dim">No feed activity.</div>',
            unsafe_allow_html=True,
        )
        return

    entries = feed_state.feed_log[-max_entries:]
    entries.reverse()
    log_html = "<br>".join(
        f'<span class="kevlar-dim">{e}</span>' for e in entries
    )

    st.markdown(
        f'<div class="kevlar-card" style="max-height:350px;overflow-y:auto;'
        f'line-height:1.7;font-size:0.72rem">{log_html}</div>',
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
    cols = st.columns(6)

    with cols[0]:
        obs_count = len(feed_state.all_observables) if feed_state else 0
        st.metric("OBS", obs_count)

    with cols[1]:
        st.metric("SEEDS", len(seeds))

    with cols[2]:
        st.metric("NODES", graph.node_count if graph else 0)

    with cols[3]:
        st.metric("LINKS", graph.edge_count if graph else 0)

    with cols[4]:
        st.metric("FUTURES", len(threads))

    with cols[5]:
        # Sources
        source_count = 0
        if feed_state and feed_state.scheduler and hasattr(feed_state.scheduler, 'get_health_summary'):
            summary = feed_state.scheduler.get_health_summary()
            source_count = summary.get("healthy", 0) + summary.get("degraded", 0)
        st.metric("SOURCES", source_count)


# ---------------------------------------------------------------------------
# Source health panel
# ---------------------------------------------------------------------------

def render_source_health_panel(feed_state: Optional[LiveFeedState]) -> None:
    if not feed_state or not feed_state.scheduler:
        st.markdown(
            '<div class="kevlar-card kevlar-dim">Scheduler not active.</div>',
            unsafe_allow_html=True,
        )
        return

    scheduler = feed_state.scheduler
    if not hasattr(scheduler, 'get_all_health'):
        return

    all_health = scheduler.get_all_health()
    if not all_health:
        return

    summary = scheduler.get_health_summary()
    total = summary.get("total_sources", 0)
    healthy = summary.get("healthy", 0)
    degraded = summary.get("degraded", 0)
    failed = summary.get("failed", 0)

    st.markdown(
        f'<div class="kevlar-bar">'
        f'<span class="kevlar-success">&#9679; {healthy}</span> &middot; '
        f'<span class="kevlar-warn">&#9679; {degraded}</span> &middot; '
        f'<span class="kevlar-danger">&#9679; {failed}</span> &middot; '
        f'<span class="kevlar-dim">{total} total</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    by_category: Dict[str, list] = {}
    for h in all_health.values():
        cat = h.category if hasattr(h, 'category') else "unknown"
        by_category.setdefault(cat, []).append(h)

    for category in sorted(by_category.keys()):
        sources = by_category[category]
        with st.expander(f"{category.upper()} ({len(sources)})", expanded=False):
            rows_html = ""
            for h in sources:
                color = _HEALTH_DOT.get(h.status, "#5a6a7a")
                err = f' <span class="kevlar-danger">{h.last_error[:35]}</span>' if h.last_error else ""
                rows_html += (
                    f'<div style="padding:3px 0;border-bottom:1px solid #111820;font-size:0.72rem">'
                    f'<span style="color:{color}">&#9679;</span> '
                    f'<b>{h.source_name}</b> '
                    f'<span class="kevlar-dim">{h.total_polls}p {h.total_records}r</span>'
                    f'{err}</div>'
                )
            st.markdown(
                f'<div style="font-family:var(--mono);color:var(--text)">{rows_html}</div>',
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Category toggles
# ---------------------------------------------------------------------------

def render_category_toggles(feed_state: Optional[LiveFeedState]) -> Dict[str, bool]:
    active: Dict[str, bool] = {}
    if not feed_state or not feed_state.scheduler:
        return active

    scheduler = feed_state.scheduler
    if not hasattr(scheduler, 'get_all_health'):
        return active

    all_health = scheduler.get_all_health()
    categories = sorted({
        h.category for h in all_health.values()
        if hasattr(h, 'category')
    })

    if not categories:
        return active

    cols = st.columns(min(4, len(categories)))
    for i, cat in enumerate(categories):
        col = cols[i % len(cols)]
        with col:
            active[cat] = st.checkbox(
                cat.replace("_", " ").upper(),
                value=True,
                key=f"cat_toggle_{cat}",
            )

    return active

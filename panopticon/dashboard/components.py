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

# Status color/icon for source health
_HEALTH_STYLE = {
    "healthy":  ("&#9679;", "#44ff44"),
    "degraded": ("&#9679;", "#ffaa00"),
    "failed":   ("&#9679;", "#ff4444"),
    "disabled": ("&#9679;", "#666666"),
    "pending":  ("&#9679;", "#4da6ff"),
}


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
    cols = st.columns(8)

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

    with cols[6]:
        # Active sources count
        source_count = 0
        if feed_state and feed_state.scheduler and hasattr(feed_state.scheduler, 'get_health_summary'):
            summary = feed_state.scheduler.get_health_summary()
            source_count = summary.get("healthy", 0) + summary.get("degraded", 0)
        st.metric("Active Sources", source_count)

    with cols[7]:
        # Categories
        cat_count = 0
        if feed_state and feed_state.scheduler and hasattr(feed_state.scheduler, 'get_health_summary'):
            summary = feed_state.scheduler.get_health_summary()
            cat_count = summary.get("categories", 0)
        st.metric("Categories", cat_count)


# ---------------------------------------------------------------------------
# Source health panel
# ---------------------------------------------------------------------------

def render_source_health_panel(feed_state: Optional[LiveFeedState]) -> None:
    """Table of all sources with status, last poll, record count, errors."""
    if not feed_state or not feed_state.scheduler:
        st.info("Multi-source scheduler not initialized. Using FIRMS-only mode.")
        return

    scheduler = feed_state.scheduler
    if not hasattr(scheduler, 'get_all_health'):
        st.info("Scheduler does not expose health data.")
        return

    all_health = scheduler.get_all_health()
    if not all_health:
        st.info("No source health data available.")
        return

    # Summary bar
    summary = scheduler.get_health_summary()
    total = summary.get("total_sources", 0)
    healthy = summary.get("healthy", 0)
    degraded = summary.get("degraded", 0)
    failed = summary.get("failed", 0)

    st.markdown(
        f'<div style="background:#0d0d0d;border:1px solid #1a3a5c;padding:10px;'
        f'border-radius:4px;font-family:Courier New;font-size:0.85em;margin-bottom:10px">'
        f'<span style="color:#44ff44">&#9679; {healthy} healthy</span> &nbsp;|&nbsp; '
        f'<span style="color:#ffaa00">&#9679; {degraded} degraded</span> &nbsp;|&nbsp; '
        f'<span style="color:#ff4444">&#9679; {failed} failed</span> &nbsp;|&nbsp; '
        f'<span style="color:#888">{total} total sources</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Group by category
    by_category: Dict[str, list] = {}
    for h in all_health.values():
        cat = h.category if hasattr(h, 'category') else "unknown"
        by_category.setdefault(cat, []).append(h)

    for category in sorted(by_category.keys()):
        sources = by_category[category]
        with st.expander(f"{category.upper()} ({len(sources)} sources)", expanded=False):
            rows_html = ""
            for h in sources:
                icon, color = _HEALTH_STYLE.get(h.status, ("&#9679;", "#888"))
                err_text = f' <span style="color:#ff4444">ERR: {h.last_error[:40]}...</span>' if h.last_error else ""
                rows_html += (
                    f'<div style="padding:4px 0;border-bottom:1px solid #1a1a1a;font-size:0.82em">'
                    f'<span style="color:{color}">{icon}</span> '
                    f'<b>{h.source_name}</b> '
                    f'<span style="color:#888">| {h.total_polls} polls | {h.total_records} records</span>'
                    f'{err_text}'
                    f'</div>'
                )
            st.markdown(
                f'<div style="font-family:Courier New;color:#e0e0e0">{rows_html}</div>',
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Category toggles for map layers
# ---------------------------------------------------------------------------

def render_category_toggles(feed_state: Optional[LiveFeedState]) -> Dict[str, bool]:
    """Checkbox grid for toggling source categories on/off. Returns active categories."""
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
            active[cat] = st.checkbox(cat.replace("_", " ").title(), value=True, key=f"cat_toggle_{cat}")

    return active

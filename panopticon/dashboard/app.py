"""
Panopticon Dark Knight — Intelligence-Grade Dashboard
=====================================================
Map-first, live-by-default. Navigable satellite imagery with
real-time FIRMS hotspot feed and full propagation pipeline.

Run: streamlit run panopticon/dashboard/app.py

"The sonar gives you a picture of the whole city. But it's wrong."
"I know. I just needed it for tonight."
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_folium import st_folium

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from panopticon.config import (
    CRITICAL_NODES,
    DEFAULT_WATCH_ZONES,
    EthicsConfig,
    LiveFeedConfig,
    PropagationWeights,
    SluiceConfig,
    ThreadingConfig,
)
from panopticon.core.events import EventSeed, EventType, observables_to_seeds
from panopticon.core.graph import TemporalGraph
from panopticon.core.propagator import BicycleChainPropagator
from panopticon.core.threading import DivergentThreader, FutureThread
from panopticon.dashboard.components import (
    render_alert_banner,
    render_category_toggles,
    render_feed_log,
    render_insight_cards,
    render_metrics_row,
    render_source_health_panel,
    render_status_bar,
)
from panopticon.dashboard.live_feed import (
    LiveFeedState,
    init_scheduler,
    merge_synthetic,
    poll_all_zones,
    poll_next_zone,
    run_full_pipeline,
    should_poll_now,
)
from panopticon.dashboard.map_view import build_panopticon_map
from panopticon.ethics.protocol import EthicalProtocol
from panopticon.ingest.simulator import dubai_strike_scenario, taiwan_strait_scenario
from panopticon.oracle.insight import InsightOracle, OracleReport, format_report_text


# ---------------------------------------------------------------------------
# Page config — Dark Knight aesthetic
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="PANOPTICON DARK KNIGHT",
    page_icon="🦇",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Dark sonar CSS
st.markdown("""
<style>
    .stApp { background-color: #0a0a0a; color: #e0e0e0; }
    .stSidebar { background-color: #0d0d0d; }
    .stSidebar .stMarkdown { color: #a0a0a0; }
    h1, h2, h3 { color: #4da6ff !important; font-family: 'Courier New', monospace !important; }
    .stMetric label { color: #4da6ff !important; }
    .stMetric [data-testid="stMetricValue"] { color: #ffffff !important; }
    .warning-banner {
        background: #1a1a00; border: 1px solid #665500; color: #ffcc00;
        padding: 12px; border-radius: 4px; font-family: 'Courier New', monospace;
        white-space: pre-line; font-size: 0.85em; margin-bottom: 8px;
    }
    /* Make folium map container full-width */
    iframe { border: 1px solid #1a3a5c !important; border-radius: 6px !important; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def init_session_state():
    defaults = {
        "protocol": EthicalProtocol(),
        "activated": False,
        "graph": None,
        "threads": [],
        "report": None,
        "seeds": [],
        # Live feed
        "live_feed": None,
        "feed_mode": "live",  # "live" or "synthetic"
        "refresh_interval": 60,
        "first_run_done": False,
        # Synthetic
        "synthetic_scenario": "Dubai Strike",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session_state()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

def render_sidebar() -> bool:
    with st.sidebar:
        st.markdown("## PANOPTICON")
        st.markdown("##### DARK KNIGHT INTELLIGENCE SYSTEM")
        st.markdown("---")

        # Activation gate
        if not st.session_state.activated:
            st.markdown("### SYSTEM LOCKED")
            phrase = st.text_input(
                "Activation phrase:", type="password", key="activation_phrase",
            )
            if st.button("ACTIVATE", type="primary"):
                protocol: EthicalProtocol = st.session_state.protocol
                if protocol.activate(phrase):
                    st.session_state.activated = True
                    # Initialize live feed state + multi-source scheduler
                    lf = LiveFeedState()
                    init_scheduler(lf)
                    st.session_state.live_feed = lf
                    st.session_state.first_run_done = False
                    st.rerun()
                else:
                    st.error("Activation denied. Incorrect phrase.")
            st.markdown("---")
            st.markdown(
                '<p style="color:#4da6ff;font-family:Courier New;font-size:0.85em">'
                'Hint: "activate contingency"</p>',
                unsafe_allow_html=True,
            )
            return False

        # Session info
        protocol: EthicalProtocol = st.session_state.protocol
        remaining = protocol.session_remaining_minutes()
        st.markdown(f"**Session:** {remaining:.0f} min remaining")
        st.markdown("---")

        # --- Data Source ---
        st.markdown("### DATA SOURCE")
        feed_mode = st.radio(
            "Mode:",
            ["Live Multi-Source", "Synthetic Scenario"],
            index=0 if st.session_state.feed_mode == "live" else 1,
            horizontal=True,
            key="feed_mode_radio",
        )
        st.session_state.feed_mode = "live" if feed_mode == "Live Multi-Source" else "synthetic"

        if st.session_state.feed_mode == "live":
            refresh = st.slider(
                "Refresh interval (s)", 30, 300, 60, step=30,
                key="refresh_interval_slider",
            )
            st.session_state.refresh_interval = refresh

            # Show scheduler status
            lf_check = st.session_state.live_feed
            if lf_check and lf_check.scheduler and hasattr(lf_check.scheduler, 'get_health_summary'):
                summary = lf_check.scheduler.get_health_summary()
                st.markdown(
                    f'<p style="color:#44ff44;font-family:Courier New;font-size:0.8em">'
                    f'Multi-source polling active. '
                    f'{summary.get("healthy", 0)}/{summary.get("total_sources", 0)} sources healthy. '
                    f'Round-robin across {len(DEFAULT_WATCH_ZONES)} watch zones.</p>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<p style="color:#ffaa00;font-family:Courier New;font-size:0.8em">'
                    'FIRMS-only fallback mode. Install pyyaml to enable multi-source.</p>',
                    unsafe_allow_html=True,
                )

            api_key = st.text_input(
                "FIRMS API Key:",
                value=st.session_state.live_feed.firms_api_key if st.session_state.live_feed else "DEMO_KEY",
                key="firms_key_input",
                help="Get free key: firms.modaps.eosdis.nasa.gov/api/map_key",
            )
            if st.session_state.live_feed:
                st.session_state.live_feed.firms_api_key = api_key
                st.session_state.live_feed.refresh_interval_s = refresh

            if st.button("FORCE POLL NOW", type="secondary"):
                _force_live_poll()

            # Synthetic overlay toggle
            if st.checkbox("Overlay synthetic scenario", value=False, key="overlay_synthetic"):
                merge_synthetic(st.session_state.live_feed, "dubai")
                run_full_pipeline(
                    st.session_state.live_feed,
                    weights=_get_weights(),
                    sluice=_get_sluice(),
                    threading=_get_threading(),
                )
                _sync_to_session()

            # Source management expander
            with st.expander("Source Management", expanded=False):
                render_source_health_panel(st.session_state.live_feed)

        else:
            scenario = st.selectbox(
                "Scenario:",
                ["Dubai Strike", "Taiwan Strait"],
                key="scenario_select",
            )
            st.session_state.synthetic_scenario = scenario

            if st.button("RUN ANALYSIS", type="primary"):
                _run_synthetic_analysis(scenario)

        st.markdown("---")

        # --- Propagation Controls ---
        st.markdown("### PROPAGATION")
        st.slider("Weight: Intensity", 0.0, 1.0, 0.35, key="w_intensity")
        st.slider("Weight: Proximity", 0.0, 1.0, 0.30, key="w_proximity")
        st.slider("Weight: Persistence", 0.0, 1.0, 0.25, key="w_persistence")
        st.slider("Sluice: Base Gate", 0.0, 1.0, 0.45, key="base_gate")
        st.slider("Beam Width (top-K)", 5, 50, 20, key="top_k")
        st.slider("Max Depth", 2, 12, 8, key="max_depth")

        st.markdown("---")

        # --- Controls ---
        col1, col2 = st.columns(2)
        with col1:
            if st.button("SELF-DESTRUCT", type="secondary"):
                protocol.self_destruct("destroy")
                for key in ["activated", "graph", "threads", "report", "seeds",
                             "live_feed", "first_run_done"]:
                    st.session_state[key] = None if key in ("graph", "live_feed", "report") else (
                        False if key in ("activated", "first_run_done") else []
                    )
                st.session_state.feed_mode = "live"
                st.rerun()
        with col2:
            if st.button("Deactivate"):
                protocol.deactivate()
                st.session_state.activated = False
                st.rerun()

        return True


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _get_weights() -> PropagationWeights:
    return PropagationWeights(
        w_intensity=st.session_state.get("w_intensity", 0.35),
        w_proximity=st.session_state.get("w_proximity", 0.30),
        w_persistence=st.session_state.get("w_persistence", 0.25),
    )


def _get_sluice() -> SluiceConfig:
    return SluiceConfig(base_gate=st.session_state.get("base_gate", 0.45))


def _get_threading() -> ThreadingConfig:
    return ThreadingConfig(
        top_k=st.session_state.get("top_k", 20),
        max_depth=st.session_state.get("max_depth", 8),
    )


def _sync_to_session() -> None:
    """Sync live feed pipeline outputs to main session state."""
    lf = st.session_state.live_feed
    if lf:
        st.session_state.seeds = lf.seeds
        st.session_state.graph = lf.graph
        st.session_state.threads = lf.threads
        st.session_state.report = lf.report


def _force_live_poll() -> None:
    """Force an immediate full poll of all sources."""
    lf: LiveFeedState = st.session_state.live_feed
    if not lf:
        return

    lf.last_poll_monotonic = None  # force poll
    spinner_msg = (
        "Polling all intelligence sources..."
        if lf.scheduler
        else "Polling FIRMS satellites across all watch zones..."
    )
    with st.spinner(spinner_msg):
        new_count = poll_all_zones(lf)

    if new_count == 0 and not lf.all_observables:
        st.warning(
            "FIRMS returned no data (DEMO_KEY is rate-limited). "
            "Falling back to synthetic Dubai scenario."
        )
        merge_synthetic(lf, "dubai")

    with st.spinner("Running analysis pipeline..."):
        run_full_pipeline(lf, _get_weights(), _get_sluice(), _get_threading())

    _sync_to_session()
    st.session_state.first_run_done = True


def _run_synthetic_analysis(scenario: str) -> None:
    """Run one-shot analysis on a synthetic scenario."""
    with st.spinner("Ingesting synthetic observables..."):
        if "Taiwan" in scenario:
            sim = taiwan_strait_scenario()
        else:
            sim = dubai_strike_scenario()
        observables = sim.sorted_by_time()

    with st.spinner("Classifying event seeds..."):
        seeds = observables_to_seeds(observables)
        st.session_state.seeds = seeds

    with st.spinner("Propagating bicycle chain..."):
        propagator = BicycleChainPropagator(
            weights=_get_weights(), sluice=_get_sluice(), threading=_get_threading()
        )
        flagged = [(25.01, 55.08, 20.0)] if "Dubai" in scenario else []
        graph = propagator.propagate_seeds(seeds, flagged_zones=flagged)

        roots = graph.get_roots()
        if roots:
            propagator.inject_wildcard(
                roots[0].event_id, EventType.STRIKE_BARRAGE,
                "Secondary explosion — fuel depot", 0.15,
            )
        st.session_state.graph = graph

    with st.spinner("Threading divergent futures..."):
        threader = DivergentThreader(config=_get_threading())
        threads = threader.generate_threads(graph)
        if roots:
            wc = threader.inject_user_wildcard(
                graph, roots[0].event_id,
                "Cyber false-flag disrupts port comms", EventType.MILITARY_ACTIVITY,
            )
            if wc:
                threads.append(wc)
        st.session_state.threads = threads

    with st.spinner("Consulting the Oracle..."):
        oracle = InsightOracle(max_insights=10)
        report = oracle.generate_report(graph, threads, scenario_name=sim.name)
        st.session_state.report = report

    # Also store observables in a temporary live feed state for the map
    lf = LiveFeedState()
    lf.all_observables = observables
    lf.seeds = seeds
    lf.graph = graph
    lf.threads = threads
    lf.report = report
    lf.status = "LIVE"
    st.session_state.live_feed = lf


def _handle_live_tick() -> None:
    """Called on each autorefresh tick in live mode. Polls if due."""
    lf: LiveFeedState = st.session_state.live_feed
    if not lf or not should_poll_now(lf):
        return

    new_count = poll_next_zone(lf)
    if new_count > 0 or (lf.poll_count <= 1):
        run_full_pipeline(lf, _get_weights(), _get_sluice(), _get_threading())
    _sync_to_session()


# ---------------------------------------------------------------------------
# Sonar view (preserved from v1)
# ---------------------------------------------------------------------------

def render_sonar_view(graph: Optional[TemporalGraph], threads: List[FutureThread]):
    if not graph or graph.node_count == 0:
        st.info("No propagation data. Run analysis first.")
        return

    fig = go.Figure()

    max_depth = max(
        (graph.get_seed(n).depth for n in graph.G.nodes() if graph.get_seed(n)),
        default=0,
    )
    for d in range(max_depth + 1):
        theta = np.linspace(0, 2 * np.pi, 100)
        r = (d + 1) * 1.0
        fig.add_trace(go.Scatter(
            x=(r * np.cos(theta)).tolist(), y=(r * np.sin(theta)).tolist(),
            mode="lines", line=dict(color="rgba(77,166,255,0.15)", width=1),
            showlegend=False, hoverinfo="skip",
        ))

    type_angles: Dict[str, float] = {}
    angle_step = 2 * np.pi / max(len(EventType), 1)
    for i, et in enumerate(EventType):
        type_angles[et.value] = i * angle_step

    node_x, node_y, node_text, node_color, node_size = [], [], [], [], []
    edge_x, edge_y = [], []
    jitter_counters: Dict[str, int] = {}

    for node_id in graph.G.nodes():
        seed = graph.get_seed(node_id)
        if not seed:
            continue
        base_angle = type_angles.get(seed.event_type.value, 0)
        jkey = f"{seed.event_type.value}_{seed.depth}"
        jitter_counters[jkey] = jitter_counters.get(jkey, 0) + 1
        angle = base_angle + (jitter_counters[jkey] - 1) * 0.15
        r = (seed.depth + 0.5) * 1.0
        node_x.append(r * math.cos(angle))
        node_y.append(r * math.sin(angle))
        momentum = graph.get_chain_momentum(node_id)
        node_text.append(f"{seed.label}<br>p={momentum:.2f} d={seed.depth}")
        from panopticon.dashboard.map_view import EVENT_TYPE_COLORS as _ETC
        node_color.append(_ETC.get(seed.event_type.value, "#4da6ff"))
        node_size.append(8 + momentum * 20)

    for u, v, data in graph.G.edges(data=True):
        idx_u = list(graph.G.nodes()).index(u)
        idx_v = list(graph.G.nodes()).index(v)
        if idx_u < len(node_x) and idx_v < len(node_x):
            edge_x.extend([node_x[idx_u], node_x[idx_v], None])
            edge_y.extend([node_y[idx_u], node_y[idx_v], None])

    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(color="rgba(77,166,255,0.3)", width=1),
        showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers",
        marker=dict(size=node_size, color=node_color,
                     line=dict(color="rgba(255,255,255,0.5)", width=1)),
        text=node_text, hoverinfo="text", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=[0], y=[0], mode="markers+text",
        marker=dict(size=16, color="#4da6ff", symbol="diamond"),
        text=["NOW"], textposition="top center",
        textfont=dict(color="#4da6ff", size=12), showlegend=False,
    ))

    fig.update_layout(
        plot_bgcolor="#0a0a0a", paper_bgcolor="#0a0a0a",
        font=dict(color="#e0e0e0", family="Courier New"),
        title=dict(text="SONAR — CAUSAL PROPAGATION FIELD",
                    font=dict(color="#4da6ff", size=16)),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                    scaleanchor="y", scaleratio=1),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=450, margin=dict(l=20, r=20, t=50, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Momentum timeline (preserved from v1)
# ---------------------------------------------------------------------------

def render_momentum_timeline(graph: Optional[TemporalGraph]):
    if not graph or graph.node_count == 0:
        st.info("No propagation data.")
        return

    times, momenta, labels, colors = [], [], [], []
    for node_id in graph.G.nodes():
        seed = graph.get_seed(node_id)
        if not seed:
            continue
        momentum = graph.get_chain_momentum(node_id)
        times.append(seed.timestamp)
        momenta.append(momentum)
        labels.append(seed.label)
        intensity = min(1.0, momentum * 2)
        r = int(77 + intensity * 178)
        g = int(166 - intensity * 166)
        b = int(255 - intensity * 200)
        colors.append(f"rgb({r},{g},{b})")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times, y=momenta, mode="markers+lines",
        marker=dict(size=8, color=colors, line=dict(width=1, color="white")),
        line=dict(color="rgba(77,166,255,0.3)", width=1),
        text=labels, hoverinfo="text+y",
    ))
    fig.update_layout(
        plot_bgcolor="#0a0a0a", paper_bgcolor="#0a0a0a",
        font=dict(color="#e0e0e0", family="Courier New"),
        title=dict(text="CHAIN MOMENTUM TIMELINE",
                    font=dict(color="#4da6ff", size=16)),
        xaxis=dict(title="Time (UTC)", gridcolor="#1a1a1a", showgrid=True),
        yaxis=dict(title="Momentum", gridcolor="#1a1a1a", showgrid=True, range=[0, 1]),
        height=300, margin=dict(l=50, r=20, t=50, b=50),
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

def main():
    # Auto-refresh MUST be called before any other st.* element
    if (st.session_state.get("activated")
            and st.session_state.get("feed_mode") == "live"):
        st_autorefresh(
            interval=st.session_state.get("refresh_interval", 60) * 1000,
            key="panopticon_live_refresh",
        )

    active = render_sidebar()

    if not active:
        # Locked screen
        st.markdown("# PANOPTICON DARK KNIGHT")
        st.markdown("### System locked. Enter activation phrase in sidebar.")
        st.markdown(
            '<div class="warning-banner">'
            "This is a contingency tool.\nPower like this demands restraint."
            "\n\n— Lucius Fox</div>",
            unsafe_allow_html=True,
        )
        return

    # --- First run: immediate value ---
    if (st.session_state.feed_mode == "live"
            and not st.session_state.first_run_done
            and st.session_state.live_feed):
        st.session_state.first_run_done = True
        _force_live_poll()
        st.rerun()

    # --- Live tick ---
    if st.session_state.feed_mode == "live":
        _handle_live_tick()

    # --- Warning banner ---
    st.markdown(
        '<div class="warning-banner">'
        "CONTINGENCY MODE ACTIVE — Session is ephemeral. "
        "No individuals tracked. Only aggregate observables.</div>",
        unsafe_allow_html=True,
    )

    # --- Status bar ---
    render_status_bar(st.session_state.live_feed, st.session_state.feed_mode)

    # --- Alerts ---
    render_alert_banner(st.session_state.report)

    # --- Title + Metrics ---
    st.markdown("# PANOPTICON DARK KNIGHT")

    graph = st.session_state.graph
    threads = st.session_state.threads
    report = st.session_state.report
    seeds = st.session_state.seeds
    lf = st.session_state.live_feed

    render_metrics_row(seeds, graph, threads, report, lf)

    # --- Interactive Satellite Map ---
    observables = lf.all_observables if lf else []

    if seeds or observables:
        fmap = build_panopticon_map(
            seeds=seeds,
            graph=graph,
            observables=observables,
        )
        st_folium(
            fmap,
            width=None,  # full width
            height=550,
            key="panopticon_map",
            returned_objects=[],
        )
    else:
        st.markdown(
            '<div style="background:#111;border:1px solid #1a3a5c;'
            'border-radius:6px;padding:40px;text-align:center;'
            'font-family:Courier New;color:#4da6ff;font-size:1.1em">'
            'Satellite map will appear here after first data ingestion.<br>'
            '<span style="color:#666">Select Live FIRMS or run a synthetic scenario.</span>'
            '</div>',
            unsafe_allow_html=True,
        )

    # --- Bottom split: Insights + Feed Log ---
    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("### INTELLIGENCE INSIGHTS")
        render_insight_cards(report)

    with col_right:
        st.markdown("### FEED LOG")
        render_feed_log(lf)

    # --- Tabs: Sonar, Timeline, Source Health, Raw Data ---
    st.markdown("---")
    tab_sonar, tab_timeline, tab_health, tab_raw = st.tabs([
        "SONAR VIEW", "TIMELINE", "SOURCE HEALTH", "RAW DATA",
    ])

    with tab_sonar:
        render_sonar_view(graph, threads)

    with tab_timeline:
        render_momentum_timeline(graph)

    with tab_health:
        st.markdown("### MULTI-SOURCE INTELLIGENCE FEED HEALTH")
        render_source_health_panel(lf)

    with tab_raw:
        st.markdown("### Graph Summary")
        if graph:
            st.json(graph.summary())
        else:
            st.info("No graph data.")

        if report:
            st.markdown("### Oracle Report (Raw)")
            st.code(format_report_text(report), language="text")

        st.markdown("### Event Seeds")
        if seeds:
            for seed in seeds:
                with st.expander(f"{seed.label} (conf={seed.confidence:.2f})"):
                    st.write({
                        "event_id": seed.event_id,
                        "type": seed.event_type.value,
                        "lat": seed.lat,
                        "lon": seed.lon,
                        "timestamp": seed.timestamp.isoformat(),
                        "intensity": round(seed.intensity, 3),
                        "confidence": round(seed.confidence, 3),
                        "nearest_critical": seed.nearest_critical[2] if seed.nearest_critical else None,
                        "proximity": round(seed.proximity_to_critical, 3),
                        "cluster_size": seed.metadata.get("cluster_size", 0),
                    })
        else:
            st.info("No event seeds.")


if __name__ == "__main__":
    main()

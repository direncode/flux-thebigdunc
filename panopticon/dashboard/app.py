"""
PANOPTICON DARK KNIGHT — Multi-Source Intelligence Dashboard
=============================================================
107-source real-time intelligence platform. GDELT OSINT backbone.
Zero API keys. Zero signup. Map-first. Live-by-default.

Run: streamlit run panopticon/dashboard/app.py

"The sonar gives you a picture of the whole city."
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
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="PANOPTICON",
    page_icon="🦇",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Kevlar CSS — minimal, tight, professional
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');

    :root {
        --bg: #06080c;
        --bg2: #0c1018;
        --bg3: #111820;
        --accent: #00d4ff;
        --accent2: #0088cc;
        --danger: #ff3355;
        --warning: #ffaa00;
        --success: #00ff88;
        --text: #c8d6e5;
        --text-dim: #5a6a7a;
        --border: #1a2535;
        --mono: 'JetBrains Mono', 'Courier New', monospace;
    }

    .stApp {
        background: var(--bg);
        color: var(--text);
        font-family: var(--mono);
    }
    .stSidebar {
        background: var(--bg2) !important;
        border-right: 1px solid var(--border);
    }
    .stSidebar .stMarkdown { color: var(--text-dim); }

    h1, h2, h3 {
        color: var(--accent) !important;
        font-family: var(--mono) !important;
        font-weight: 600 !important;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    h1 { font-size: 1.4rem !important; }
    h2 { font-size: 1.1rem !important; }
    h3 { font-size: 0.95rem !important; }

    /* Metrics — compact monospace */
    .stMetric label {
        color: var(--text-dim) !important;
        font-size: 0.7rem !important;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .stMetric [data-testid="stMetricValue"] {
        color: var(--accent) !important;
        font-family: var(--mono) !important;
        font-size: 1.3rem !important;
        font-weight: 700;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        background: var(--bg2);
        border-radius: 4px;
        padding: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        font-family: var(--mono) !important;
        font-size: 0.75rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: var(--text-dim);
        border-radius: 3px;
        padding: 6px 14px;
    }
    .stTabs [aria-selected="true"] {
        background: var(--bg3) !important;
        color: var(--accent) !important;
    }

    /* Map iframe */
    iframe {
        border: 1px solid var(--border) !important;
        border-radius: 4px !important;
    }

    /* Buttons */
    .stButton button {
        font-family: var(--mono) !important;
        font-size: 0.75rem;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        border: 1px solid var(--border);
        background: var(--bg3);
        color: var(--accent);
    }
    .stButton button:hover {
        border-color: var(--accent);
        background: var(--bg2);
    }
    .stButton button[kind="primary"] {
        background: var(--accent2) !important;
        color: #ffffff !important;
        border-color: var(--accent) !important;
    }

    /* Expanders */
    .streamlit-expanderHeader {
        font-family: var(--mono) !important;
        font-size: 0.78rem;
        color: var(--text-dim);
        background: var(--bg2);
    }

    /* Hide default Streamlit branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header { visibility: hidden; }

    /* Status bar custom classes */
    .kevlar-bar {
        background: var(--bg2);
        border: 1px solid var(--border);
        border-radius: 4px;
        padding: 8px 16px;
        font-family: var(--mono);
        font-size: 0.78rem;
        color: var(--text);
        margin-bottom: 8px;
    }
    .kevlar-accent { color: var(--accent); }
    .kevlar-danger { color: var(--danger); }
    .kevlar-warn { color: var(--warning); }
    .kevlar-success { color: var(--success); }
    .kevlar-dim { color: var(--text-dim); }
    .kevlar-card {
        background: var(--bg2);
        border: 1px solid var(--border);
        border-radius: 4px;
        padding: 12px;
        font-family: var(--mono);
        font-size: 0.78rem;
        color: var(--text);
        margin-bottom: 6px;
    }
    .kevlar-tag {
        display: inline-block;
        background: var(--bg3);
        border: 1px solid var(--border);
        border-radius: 2px;
        padding: 2px 6px;
        font-size: 0.68rem;
        color: var(--accent);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-right: 4px;
    }
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
        st.markdown(
            '<div style="text-align:center;padding:8px 0">'
            '<span style="color:var(--accent);font-size:1.1rem;font-weight:700;'
            'letter-spacing:0.15em">PANOPTICON</span><br>'
            '<span style="color:var(--text-dim);font-size:0.65rem;letter-spacing:0.1em">'
            'DARK KNIGHT INTELLIGENCE</span></div>',
            unsafe_allow_html=True,
        )

        # Activation gate
        if not st.session_state.activated:
            st.markdown("---")
            phrase = st.text_input(
                "Activation phrase", type="password", key="activation_phrase",
                placeholder="enter phrase",
            )
            if st.button("ACTIVATE", type="primary", use_container_width=True):
                protocol: EthicalProtocol = st.session_state.protocol
                if protocol.activate(phrase):
                    st.session_state.activated = True
                    lf = LiveFeedState()
                    init_scheduler(lf)
                    st.session_state.live_feed = lf
                    st.session_state.first_run_done = False
                    st.rerun()
                else:
                    st.error("Denied.")
            st.markdown(
                '<p style="color:var(--text-dim);font-size:0.7rem;text-align:center;'
                'margin-top:12px">hint: activate contingency</p>',
                unsafe_allow_html=True,
            )
            return False

        # --- Source status chip ---
        protocol: EthicalProtocol = st.session_state.protocol
        remaining = protocol.session_remaining_minutes()
        lf_check = st.session_state.live_feed

        source_count = 0
        if lf_check and lf_check.scheduler and hasattr(lf_check.scheduler, 'get_health_summary'):
            summary = lf_check.scheduler.get_health_summary()
            source_count = summary.get("total_sources", 0)
            healthy = summary.get("healthy", 0)

        st.markdown(
            f'<div class="kevlar-bar" style="text-align:center">'
            f'<span class="kevlar-success">&#9679;</span> '
            f'<span class="kevlar-accent">{source_count}</span> sources &middot; '
            f'<span class="kevlar-dim">{remaining:.0f}m left</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # --- Mode selector ---
        feed_mode = st.radio(
            "mode",
            ["LIVE", "SIM"],
            index=0 if st.session_state.feed_mode == "live" else 1,
            horizontal=True,
            key="feed_mode_radio",
            label_visibility="collapsed",
        )
        st.session_state.feed_mode = "live" if feed_mode == "LIVE" else "synthetic"

        if st.session_state.feed_mode == "live":
            refresh = st.slider(
                "refresh (s)", 30, 300, 60, step=30,
                key="refresh_interval_slider",
                label_visibility="collapsed",
            )
            st.session_state.refresh_interval = refresh
            if st.session_state.live_feed:
                st.session_state.live_feed.refresh_interval_s = refresh

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("POLL NOW", use_container_width=True):
                    _force_live_poll()
            with col_b:
                if st.button("+ SYNTH", use_container_width=True):
                    merge_synthetic(st.session_state.live_feed, "dubai")
                    run_full_pipeline(
                        st.session_state.live_feed,
                        weights=_get_weights(),
                        sluice=_get_sluice(),
                        threading=_get_threading(),
                    )
                    _sync_to_session()

        else:
            scenario = st.selectbox(
                "scenario",
                ["Dubai Strike", "Taiwan Strait"],
                key="scenario_select",
                label_visibility="collapsed",
            )
            st.session_state.synthetic_scenario = scenario
            if st.button("RUN", type="primary", use_container_width=True):
                _run_synthetic_analysis(scenario)

        # --- Propagation tuning (collapsed) ---
        with st.expander("Propagation", expanded=False):
            st.slider("Intensity", 0.0, 1.0, 0.35, key="w_intensity")
            st.slider("Proximity", 0.0, 1.0, 0.30, key="w_proximity")
            st.slider("Persistence", 0.0, 1.0, 0.25, key="w_persistence")
            st.slider("Gate", 0.0, 1.0, 0.45, key="base_gate")
            st.slider("Beam K", 5, 50, 20, key="top_k")
            st.slider("Depth", 2, 12, 8, key="max_depth")

        # --- Session controls ---
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("WIPE", use_container_width=True):
                protocol.self_destruct("destroy")
                for key in ["activated", "graph", "threads", "report", "seeds",
                             "live_feed", "first_run_done"]:
                    st.session_state[key] = None if key in ("graph", "live_feed", "report") else (
                        False if key in ("activated", "first_run_done") else []
                    )
                st.session_state.feed_mode = "live"
                st.rerun()
        with col2:
            if st.button("EXIT", use_container_width=True):
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
        st.markdown('<div class="kevlar-card kevlar-dim">No propagation data.</div>', unsafe_allow_html=True)
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
            mode="lines", line=dict(color="rgba(0,212,255,0.1)", width=1),
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
        node_color.append(_ETC.get(seed.event_type.value, "#00d4ff"))
        node_size.append(8 + momentum * 20)

    for u, v, data in graph.G.edges(data=True):
        idx_u = list(graph.G.nodes()).index(u)
        idx_v = list(graph.G.nodes()).index(v)
        if idx_u < len(node_x) and idx_v < len(node_x):
            edge_x.extend([node_x[idx_u], node_x[idx_v], None])
            edge_y.extend([node_y[idx_u], node_y[idx_v], None])

    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(color="rgba(0,212,255,0.2)", width=1),
        showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers",
        marker=dict(size=node_size, color=node_color,
                     line=dict(color="rgba(200,214,229,0.3)", width=0.5)),
        text=node_text, hoverinfo="text", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=[0], y=[0], mode="markers+text",
        marker=dict(size=14, color="#00d4ff", symbol="diamond"),
        text=["NOW"], textposition="top center",
        textfont=dict(color="#00d4ff", size=11, family="JetBrains Mono"),
        showlegend=False,
    ))

    fig.update_layout(
        plot_bgcolor="#06080c", paper_bgcolor="#06080c",
        font=dict(color="#c8d6e5", family="JetBrains Mono, Courier New"),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False,
                    scaleanchor="y", scaleratio=1),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=420, margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Momentum timeline (preserved from v1)
# ---------------------------------------------------------------------------

def render_momentum_timeline(graph: Optional[TemporalGraph]):
    if not graph or graph.node_count == 0:
        st.markdown('<div class="kevlar-card kevlar-dim">No propagation data.</div>', unsafe_allow_html=True)
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
        r = int(0 + intensity * 255)
        g = int(212 - intensity * 160)
        b = int(255 - intensity * 200)
        colors.append(f"rgb({r},{g},{b})")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times, y=momenta, mode="markers+lines",
        marker=dict(size=6, color=colors, line=dict(width=0.5, color="rgba(200,214,229,0.3)")),
        line=dict(color="rgba(0,212,255,0.2)", width=1),
        text=labels, hoverinfo="text+y",
    ))
    fig.update_layout(
        plot_bgcolor="#06080c", paper_bgcolor="#06080c",
        font=dict(color="#5a6a7a", family="JetBrains Mono, Courier New", size=10),
        xaxis=dict(gridcolor="#111820", showgrid=True, linecolor="#1a2535"),
        yaxis=dict(gridcolor="#111820", showgrid=True, range=[0, 1], linecolor="#1a2535"),
        height=280, margin=dict(l=40, r=10, t=10, b=40),
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
        # Locked screen — minimal, clean
        st.markdown("")  # spacer
        st.markdown(
            '<div style="text-align:center;padding:80px 20px">'
            '<div style="font-size:2rem;font-weight:700;color:var(--accent);'
            'letter-spacing:0.2em;font-family:var(--mono)">PANOPTICON</div>'
            '<div style="font-size:0.75rem;color:var(--text-dim);letter-spacing:0.15em;'
            'margin-top:4px">DARK KNIGHT INTELLIGENCE SYSTEM</div>'
            '<div style="margin-top:40px;color:var(--text-dim);font-size:0.8rem;'
            'font-family:var(--mono)">'
            'Open sidebar to activate &middot; 107 sources &middot; zero keys'
            '</div>'
            '<div style="margin-top:30px;padding:16px;color:var(--text-dim);'
            'font-size:0.72rem;font-style:italic;font-family:var(--mono)">'
            '"Power like this demands restraint." &mdash; Lucius Fox'
            '</div></div>',
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

    # --- Top bar: status + alerts ---
    render_status_bar(st.session_state.live_feed, st.session_state.feed_mode)
    render_alert_banner(st.session_state.report)

    graph = st.session_state.graph
    threads = st.session_state.threads
    report = st.session_state.report
    seeds = st.session_state.seeds
    lf = st.session_state.live_feed

    # --- Metrics row ---
    render_metrics_row(seeds, graph, threads, report, lf)

    # --- Hero map ---
    observables = lf.all_observables if lf else []

    if seeds or observables:
        fmap = build_panopticon_map(
            seeds=seeds,
            graph=graph,
            observables=observables,
        )
        st_folium(
            fmap,
            width=None,
            height=620,
            key="panopticon_map",
            returned_objects=[],
        )
    else:
        st.markdown(
            '<div style="background:var(--bg2);border:1px solid var(--border);'
            'border-radius:4px;padding:60px;text-align:center;'
            'font-family:var(--mono);color:var(--text-dim);font-size:0.85rem">'
            'Awaiting first data ingestion &mdash; map renders here.'
            '</div>',
            unsafe_allow_html=True,
        )

    # --- Tabbed panels ---
    tab_intel, tab_sonar, tab_timeline, tab_sources, tab_raw = st.tabs([
        "INTEL", "SONAR", "TIMELINE", "SOURCES", "RAW",
    ])

    with tab_intel:
        col_left, col_right = st.columns([3, 2])
        with col_left:
            render_insight_cards(report)
        with col_right:
            render_feed_log(lf)

    with tab_sonar:
        render_sonar_view(graph, threads)

    with tab_timeline:
        render_momentum_timeline(graph)

    with tab_sources:
        render_source_health_panel(lf)

    with tab_raw:
        if graph:
            st.json(graph.summary())
        if report:
            st.code(format_report_text(report), language="text")
        if seeds:
            for seed in seeds[:20]:
                with st.expander(f"{seed.label} (conf={seed.confidence:.2f})"):
                    st.write({
                        "type": seed.event_type.value,
                        "lat": seed.lat, "lon": seed.lon,
                        "intensity": round(seed.intensity, 3),
                        "confidence": round(seed.confidence, 3),
                        "cluster_size": seed.metadata.get("cluster_size", 0),
                    })


if __name__ == "__main__":
    main()

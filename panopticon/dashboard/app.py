"""
Panopticon God-View Dashboard
=============================
Streamlit-based radial sonar interface.

Aesthetic: The Dark Knight sonar lenses.
- Black background, white/blue high-contrast
- Radial rings: concentric time/propensity depth from central "now"
- Pulsing chains: momentum as glow intensity
- Branching trees: divergent futures
- Heatmap overlays: hotspot density

Run: streamlit run panopticon/dashboard/app.py
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

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from panopticon.config import (
    CRITICAL_NODES,
    DEFAULT_WATCH_ZONES,
    EthicsConfig,
    PropagationWeights,
    SluiceConfig,
    ThreadingConfig,
)
from panopticon.core.events import EventSeed, EventType, observables_to_seeds
from panopticon.core.graph import TemporalGraph
from panopticon.core.propagator import BicycleChainPropagator
from panopticon.core.threading import DivergentThreader, FutureThread
from panopticon.ethics.protocol import ACTIVATION_BANNER, EthicalProtocol
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
    /* Dark Knight sonar aesthetic */
    .stApp {
        background-color: #0a0a0a;
        color: #e0e0e0;
    }
    .stSidebar {
        background-color: #0d0d0d;
    }
    .stSidebar .stMarkdown {
        color: #a0a0a0;
    }
    h1, h2, h3 {
        color: #4da6ff !important;
        font-family: 'Courier New', monospace !important;
    }
    .stMetric label {
        color: #4da6ff !important;
    }
    .stMetric [data-testid="stMetricValue"] {
        color: #ffffff !important;
    }
    .insight-card {
        background: #111111;
        border: 1px solid #1a3a5c;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
    }
    .insight-pessimistic { border-left: 4px solid #ff4444; }
    .insight-optimistic { border-left: 4px solid #44ff44; }
    .insight-wildcard { border-left: 4px solid #ffaa00; }
    .sonar-pulse {
        color: #4da6ff;
        font-family: 'Courier New', monospace;
        font-size: 0.9em;
    }
    .warning-banner {
        background: #1a1a00;
        border: 1px solid #665500;
        color: #ffcc00;
        padding: 15px;
        border-radius: 4px;
        font-family: 'Courier New', monospace;
        white-space: pre-line;
    }
    .anomaly-alert {
        background: #1a0000;
        border: 1px solid #660000;
        color: #ff6666;
        padding: 10px;
        border-radius: 4px;
        font-family: 'Courier New', monospace;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

def init_session_state():
    if "protocol" not in st.session_state:
        st.session_state.protocol = EthicalProtocol()
    if "activated" not in st.session_state:
        st.session_state.activated = False
    if "graph" not in st.session_state:
        st.session_state.graph = None
    if "threads" not in st.session_state:
        st.session_state.threads = []
    if "report" not in st.session_state:
        st.session_state.report = None
    if "seeds" not in st.session_state:
        st.session_state.seeds = []

init_session_state()


# ---------------------------------------------------------------------------
# Sidebar: activation + configuration
# ---------------------------------------------------------------------------

def render_sidebar():
    with st.sidebar:
        st.markdown("## PANOPTICON")
        st.markdown("##### DARK KNIGHT CONTINGENCY SYSTEM")
        st.markdown("---")

        # Activation gate
        if not st.session_state.activated:
            st.markdown("### SYSTEM LOCKED")
            phrase = st.text_input(
                "Activation phrase:",
                type="password",
                key="activation_phrase",
            )
            if st.button("ACTIVATE", type="primary"):
                protocol: EthicalProtocol = st.session_state.protocol
                if protocol.activate(phrase):
                    st.session_state.activated = True
                    st.rerun()
                else:
                    st.error("Activation denied. Incorrect phrase.")
            st.markdown("---")
            st.markdown(
                '<p class="sonar-pulse">Hint: "activate contingency"</p>',
                unsafe_allow_html=True,
            )
            return False

        # Active session info
        protocol: EthicalProtocol = st.session_state.protocol
        remaining = protocol.session_remaining_minutes()
        st.markdown(f"**Session:** {remaining:.0f} min remaining")

        st.markdown("---")
        st.markdown("### SCENARIO")

        scenario = st.selectbox(
            "Data source:",
            ["Dubai Strike (Synthetic)", "Taiwan Strait (Synthetic)", "Live FIRMS (Stub)"],
        )

        st.markdown("### PROPAGATION")
        w_intensity = st.slider("Weight: Intensity", 0.0, 1.0, 0.35)
        w_proximity = st.slider("Weight: Proximity", 0.0, 1.0, 0.30)
        w_persistence = st.slider("Weight: Persistence", 0.0, 1.0, 0.25)
        base_gate = st.slider("Sluice: Base Gate", 0.0, 1.0, 0.6)
        top_k = st.slider("Beam Width (top-K)", 5, 50, 20)
        max_depth = st.slider("Max Depth", 2, 12, 8)

        st.markdown("---")

        if st.button("RUN ANALYSIS", type="primary"):
            run_analysis(
                scenario=scenario,
                weights=PropagationWeights(
                    w_intensity=w_intensity,
                    w_proximity=w_proximity,
                    w_persistence=w_persistence,
                ),
                sluice=SluiceConfig(base_gate=base_gate),
                threading=ThreadingConfig(top_k=top_k, max_depth=max_depth),
            )

        st.markdown("---")

        # Self-destruct
        if st.button("SELF-DESTRUCT", type="secondary"):
            protocol.self_destruct("destroy")
            st.session_state.activated = False
            st.session_state.graph = None
            st.session_state.threads = []
            st.session_state.report = None
            st.session_state.seeds = []
            st.rerun()

        # Deactivate
        if st.button("Deactivate Session"):
            protocol.deactivate()
            st.session_state.activated = False
            st.rerun()

        return True


# ---------------------------------------------------------------------------
# Analysis runner
# ---------------------------------------------------------------------------

def run_analysis(
    scenario: str,
    weights: PropagationWeights,
    sluice: SluiceConfig,
    threading: ThreadingConfig,
):
    """Run the full Panopticon analysis pipeline."""
    with st.spinner("Ingesting satellite observables..."):
        if "Dubai" in scenario:
            sim = dubai_strike_scenario()
        elif "Taiwan" in scenario:
            sim = taiwan_strait_scenario()
        else:
            st.warning("Live FIRMS polling is a stub. Using Dubai scenario.")
            sim = dubai_strike_scenario()

        observables = sim.sorted_by_time()

    with st.spinner("Classifying event seeds..."):
        seeds = observables_to_seeds(observables)
        st.session_state.seeds = seeds

    with st.spinner("Propagating bicycle chain..."):
        propagator = BicycleChainPropagator(
            weights=weights, sluice=sluice, threading=threading
        )
        graph = propagator.propagate_seeds(
            seeds,
            flagged_zones=[(25.01, 55.08, 20.0)],  # Jebel Ali flagged
        )

        # Inject a wildcard for demonstration
        roots = graph.get_roots()
        if roots:
            propagator.inject_wildcard(
                roots[0].event_id,
                EventType.STRIKE_BARRAGE,
                "Secondary explosion — fuel depot",
                forced_propensity=0.15,
            )

        st.session_state.graph = graph

    with st.spinner("Threading divergent futures..."):
        threader = DivergentThreader(config=threading)
        threads = threader.generate_threads(graph)

        # Also inject a user wildcard
        if roots:
            wc_thread = threader.inject_user_wildcard(
                graph, roots[0].event_id,
                "Cyber false-flag disrupts port comms",
                EventType.MILITARY_ACTIVITY,
            )
            if wc_thread:
                threads.append(wc_thread)

        st.session_state.threads = threads

    with st.spinner("Consulting the Oracle..."):
        oracle = InsightOracle(max_insights=10)
        report = oracle.generate_report(graph, threads, scenario_name=scenario)
        st.session_state.report = report


# ---------------------------------------------------------------------------
# Visualisation: Sonar radial view
# ---------------------------------------------------------------------------

def render_sonar_view(graph: TemporalGraph, threads: List[FutureThread]):
    """
    Radial sonar display: central "now" seed, concentric rings by depth.
    Dark Knight aesthetic: black bg, blue/white high-contrast.
    """
    if not graph or graph.node_count == 0:
        return

    fig = go.Figure()

    # Draw concentric rings (depth levels)
    max_depth = max(
        (graph.get_seed(n).depth for n in graph.G.nodes() if graph.get_seed(n)),
        default=0,
    )
    for d in range(max_depth + 1):
        theta = np.linspace(0, 2 * np.pi, 100)
        r = (d + 1) * 1.0
        x = r * np.cos(theta)
        y = r * np.sin(theta)
        fig.add_trace(go.Scatter(
            x=x.tolist(), y=y.tolist(),
            mode="lines",
            line=dict(color="rgba(77,166,255,0.15)", width=1),
            showlegend=False,
            hoverinfo="skip",
        ))

    # Place nodes at angular positions by event type, radial by depth
    type_angles: Dict[str, float] = {}
    angle_step = 2 * np.pi / max(len(EventType), 1)
    for i, et in enumerate(EventType):
        type_angles[et.value] = i * angle_step

    node_x, node_y, node_text, node_color, node_size = [], [], [], [], []
    edge_x, edge_y = [], []

    # Angle jitter counter per (type, depth) to spread nodes
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
        x = r * math.cos(angle)
        y = r * math.sin(angle)

        node_x.append(x)
        node_y.append(y)

        momentum = graph.get_chain_momentum(node_id)
        label = seed.label
        node_text.append(f"{label}<br>p={momentum:.2f} d={seed.depth}")

        # Color by event type
        colors = {
            "strike_barrage": "#ff4444",
            "structural_collapse": "#ff8800",
            "industrial_fire": "#ffaa00",
            "wildfire_spread": "#ff6600",
            "smoke_corridor": "#888888",
            "military_activity": "#ff0066",
            "anomalous_thermal": "#cc44ff",
            "unknown_cluster": "#444444",
        }
        node_color.append(colors.get(seed.event_type.value, "#4da6ff"))
        node_size.append(8 + momentum * 20)

    # Edges
    for u, v, data in graph.G.edges(data=True):
        seed_u = graph.get_seed(u)
        seed_v = graph.get_seed(v)
        if not seed_u or not seed_v:
            continue
        # Get positions from node arrays
        idx_u = list(graph.G.nodes()).index(u)
        idx_v = list(graph.G.nodes()).index(v)
        if idx_u < len(node_x) and idx_v < len(node_x):
            edge_x.extend([node_x[idx_u], node_x[idx_v], None])
            edge_y.extend([node_y[idx_u], node_y[idx_v], None])

    # Draw edges
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(color="rgba(77,166,255,0.3)", width=1),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Draw nodes
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y,
        mode="markers",
        marker=dict(
            size=node_size,
            color=node_color,
            line=dict(color="rgba(255,255,255,0.5)", width=1),
        ),
        text=node_text,
        hoverinfo="text",
        showlegend=False,
    ))

    # Central "NOW" marker
    fig.add_trace(go.Scatter(
        x=[0], y=[0],
        mode="markers+text",
        marker=dict(size=16, color="#4da6ff", symbol="diamond"),
        text=["NOW"],
        textposition="top center",
        textfont=dict(color="#4da6ff", size=12),
        showlegend=False,
    ))

    fig.update_layout(
        plot_bgcolor="#0a0a0a",
        paper_bgcolor="#0a0a0a",
        font=dict(color="#e0e0e0", family="Courier New"),
        title=dict(
            text="SONAR — CAUSAL PROPAGATION FIELD",
            font=dict(color="#4da6ff", size=16),
        ),
        xaxis=dict(
            showgrid=False, zeroline=False, showticklabels=False,
            scaleanchor="y", scaleratio=1,
        ),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=600,
        margin=dict(l=20, r=20, t=50, b=20),
    )

    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Visualisation: Geographic heatmap
# ---------------------------------------------------------------------------

def render_geo_heatmap(seeds: List[EventSeed], graph: TemporalGraph):
    """Geographic scatter of events overlaid on a dark map."""
    if not seeds and (not graph or graph.node_count == 0):
        return

    lats, lons, texts, colors, sizes = [], [], [], [], []

    # Plot seed events
    for seed in seeds:
        lats.append(seed.lat)
        lons.append(seed.lon)
        texts.append(seed.label)
        colors.append("#ff4444")
        sizes.append(12)

    # Plot propagated events
    if graph:
        for node_id in graph.G.nodes():
            s = graph.get_seed(node_id)
            if s and s.depth > 0:
                lats.append(s.lat)
                lons.append(s.lon)
                momentum = graph.get_chain_momentum(node_id)
                texts.append(f"{s.label} (p={momentum:.2f})")
                colors.append("#4da6ff" if momentum > 0.3 else "#333333")
                sizes.append(6 + momentum * 12)

    # Critical nodes
    for lat, lon, name, cat in CRITICAL_NODES:
        lats.append(lat)
        lons.append(lon)
        texts.append(f"[{cat}] {name}")
        colors.append("#ffffff")
        sizes.append(5)

    fig = go.Figure()
    fig.add_trace(go.Scattergeo(
        lat=lats,
        lon=lons,
        text=texts,
        mode="markers",
        marker=dict(
            size=sizes,
            color=colors,
            line=dict(color="rgba(255,255,255,0.3)", width=0.5),
        ),
        hoverinfo="text",
    ))

    fig.update_layout(
        geo=dict(
            bgcolor="#0a0a0a",
            landcolor="#1a1a1a",
            oceancolor="#0a0a0a",
            lakecolor="#0a0a0a",
            showlakes=True,
            coastlinecolor="#333333",
            countrycolor="#222222",
            showland=True,
            showcountries=True,
            projection_type="natural earth",
        ),
        plot_bgcolor="#0a0a0a",
        paper_bgcolor="#0a0a0a",
        font=dict(color="#e0e0e0", family="Courier New"),
        title=dict(
            text="GEOGRAPHIC THREAT OVERLAY",
            font=dict(color="#4da6ff", size=16),
        ),
        height=500,
        margin=dict(l=0, r=0, t=50, b=0),
    )

    # Zoom to event area if we have seeds
    if seeds:
        center_lat = sum(s.lat for s in seeds) / len(seeds)
        center_lon = sum(s.lon for s in seeds) / len(seeds)
        fig.update_geos(
            center=dict(lat=center_lat, lon=center_lon),
            projection_scale=8,
        )

    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Visualisation: Chain momentum timeline
# ---------------------------------------------------------------------------

def render_momentum_timeline(graph: TemporalGraph):
    """Timeline of events colored by momentum."""
    if not graph or graph.node_count == 0:
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
        # Color gradient: blue (low) → red (high momentum)
        intensity = min(1.0, momentum * 2)
        r = int(77 + intensity * 178)
        g = int(166 - intensity * 166)
        b = int(255 - intensity * 200)
        colors.append(f"rgb({r},{g},{b})")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times,
        y=momenta,
        mode="markers+lines",
        marker=dict(size=8, color=colors, line=dict(width=1, color="white")),
        line=dict(color="rgba(77,166,255,0.3)", width=1),
        text=labels,
        hoverinfo="text+y",
    ))

    fig.update_layout(
        plot_bgcolor="#0a0a0a",
        paper_bgcolor="#0a0a0a",
        font=dict(color="#e0e0e0", family="Courier New"),
        title=dict(
            text="CHAIN MOMENTUM TIMELINE",
            font=dict(color="#4da6ff", size=16),
        ),
        xaxis=dict(
            title="Time (UTC)",
            gridcolor="#1a1a1a",
            showgrid=True,
        ),
        yaxis=dict(
            title="Chain Momentum",
            gridcolor="#1a1a1a",
            showgrid=True,
            range=[0, 1],
        ),
        height=350,
        margin=dict(l=50, r=20, t=50, b=50),
    )

    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Render insights
# ---------------------------------------------------------------------------

def render_insights(report: OracleReport):
    """Render oracle insights as styled cards."""
    if not report:
        return

    # Anomaly alerts
    if report.anomalies:
        for anomaly in report.anomalies:
            st.markdown(
                f'<div class="anomaly-alert">⚡ {anomaly}</div>',
                unsafe_allow_html=True,
            )
        st.markdown("")

    # Insight cards
    for insight in report.insights:
        css_class = f"insight-{insight.branch_type}"
        icon = {"optimistic": "🟢", "pessimistic": "🔴", "wildcard": "🟡"}.get(
            insight.branch_type, "⚪"
        )

        chain_str = " → ".join(insight.chain[:5])
        risks_str = ", ".join(insight.key_risks[:3]) if insight.key_risks else "—"

        st.markdown(f"""
        <div class="insight-card {css_class}">
            <strong>{icon} #{insight.rank}</strong> — {insight.summary}<br>
            <span class="sonar-pulse">
                Chain: {chain_str}<br>
                Key risks: {risks_str}<br>
                Timeline: {insight.timeline_hours}h | Branch: {insight.branch_type}
            </span>
            {"<br><em>" + insight.divergence_note + "</em>" if insight.divergence_note else ""}
        </div>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

def main():
    active = render_sidebar()

    if not active:
        # Show locked state
        st.markdown("# PANOPTICON DARK KNIGHT")
        st.markdown("### System locked. Enter activation phrase in sidebar.")
        st.markdown(
            '<div class="warning-banner">'
            "This is a contingency tool.\nPower like this demands restraint."
            "\n\n— Lucius Fox"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # Warning banner
    st.markdown(
        '<div class="warning-banner">'
        "CONTINGENCY MODE ACTIVE — Session is ephemeral. "
        "No individuals tracked. Only aggregate observables."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")

    # Header
    st.markdown("# PANOPTICON DARK KNIGHT")

    # Metrics row
    graph = st.session_state.graph
    threads = st.session_state.threads
    report = st.session_state.report
    seeds = st.session_state.seeds

    if graph:
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Event Seeds", len(seeds))
        with col2:
            st.metric("Graph Nodes", graph.node_count)
        with col3:
            st.metric("Causal Links", graph.edge_count)
        with col4:
            st.metric("Future Threads", len(threads))
        with col5:
            if report:
                top_prop = report.insights[0].propensity_pct if report.insights else 0
                st.metric("Top Propensity", f"{top_prop:.0f}%")

    # Main content
    if not graph:
        st.markdown("### Configure scenario in sidebar and press RUN ANALYSIS")
        st.markdown("---")
        st.markdown("#### Available scenarios:")
        st.markdown("- **Dubai Strike (Synthetic):** Multi-phase kinetic event at Jebel Ali port")
        st.markdown("- **Taiwan Strait (Synthetic):** Military buildup near Fujian coast")
        st.markdown("- **Live FIRMS:** Real NASA FIRMS polling (requires API key)")
        return

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "SONAR VIEW",
        "GEO OVERLAY",
        "INSIGHTS",
        "TIMELINE",
        "RAW DATA",
    ])

    with tab1:
        render_sonar_view(graph, threads)

    with tab2:
        render_geo_heatmap(seeds, graph)

    with tab3:
        if report:
            render_insights(report)
        else:
            st.info("Run analysis to generate insights.")

    with tab4:
        render_momentum_timeline(graph)

    with tab5:
        st.markdown("### Graph Summary")
        st.json(graph.summary())

        if report:
            st.markdown("### Oracle Report (Raw)")
            st.code(format_report_text(report), language="text")

        st.markdown("### Event Seeds")
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


if __name__ == "__main__":
    main()

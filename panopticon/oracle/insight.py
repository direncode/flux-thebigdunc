"""
Insight Oracle
==============
Auto-synthesizes the propagation graph and divergent threads into
ranked, human-readable insights.

"72% propensity: fire cluster propagates to Jebel Ali port choke →
 4h supply disruption cascade → 48h Europe inflation whisper."

No LLM. No opinions. Just chain math → structured narrative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from panopticon.core.events import EventSeed, EventType
from panopticon.core.graph import TemporalGraph
from panopticon.core.threading import FutureThread


@dataclass
class Insight:
    """A single ranked future insight."""
    rank: int
    propensity_pct: float       # 0–100
    summary: str                # one-line headline
    chain: List[str]            # event labels along the causal chain
    timeline_hours: float       # estimated time to terminal event
    key_risks: List[str]        # critical risks in this chain
    cascade_effects: List[Dict[str, Any]]  # downstream economic/supply effects
    branch_type: str            # optimistic / pessimistic / wildcard
    thread_id: str
    anomaly_flags: List[str] = field(default_factory=list)
    divergence_note: str = ""


@dataclass
class OracleReport:
    """Full oracle output: ranked insights + summary statistics."""
    generated_at: datetime = field(default_factory=datetime.utcnow)
    scenario_name: str = ""
    total_seeds: int = 0
    total_graph_nodes: int = 0
    total_threads: int = 0
    insights: List[Insight] = field(default_factory=list)
    seed_summary: str = ""
    anomalies: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Narrative templates — deterministic, no LLM
# ---------------------------------------------------------------------------

EVENT_VERBS: Dict[EventType, str] = {
    EventType.STRIKE_BARRAGE: "strike barrage detected",
    EventType.STRUCTURAL_COLLAPSE: "structural collapse confirmed",
    EventType.INDUSTRIAL_FIRE: "industrial fire ignites",
    EventType.WILDFIRE_SPREAD: "fire spreads to adjacent zone",
    EventType.SMOKE_CORRIDOR: "smoke corridor establishes",
    EventType.MILITARY_ACTIVITY: "military mobilisation observed",
    EventType.ANOMALOUS_THERMAL: "anomalous thermal signature",
    EventType.UNKNOWN_CLUSTER: "unclassified thermal cluster",
    # --- Cross-domain event verbs ---
    EventType.SEISMIC_EVENT: "seismic event detected",
    EventType.VOLCANIC_ERUPTION: "volcanic eruption reported",
    EventType.SEVERE_WEATHER: "severe weather alert issued",
    EventType.FLOOD_EVENT: "flood conditions confirmed",
    EventType.ARMED_CONFLICT_EVENT: "armed conflict reported",
    EventType.MASS_PROTEST: "mass protest observed",
    EventType.SANCTIONS_EVENT: "sanctions action imposed",
    EventType.ECONOMIC_SHOCK: "economic shock signal",
    EventType.SUPPLY_CHAIN_DISRUPTION: "supply chain disruption detected",
    EventType.COMMODITY_SPIKE: "commodity price spike",
    EventType.HUMANITARIAN_CRISIS: "humanitarian crisis escalates",
    EventType.DISEASE_OUTBREAK_EVENT: "disease outbreak reported",
    EventType.CYBER_ATTACK: "cyber attack detected",
    EventType.INFRASTRUCTURE_DISRUPTION: "infrastructure failure confirmed",
    EventType.ENVIRONMENTAL_CRISIS: "environmental crisis emerging",
    EventType.MARITIME_DISRUPTION: "maritime route disrupted",
    EventType.AIRSPACE_ANOMALY: "airspace anomaly detected",
    EventType.MULTI_DOMAIN_CLUSTER: "multi-domain signal convergence",
}

TIMELINE_LABELS = [
    (1, "immediate"),
    (4, "near-term"),
    (12, "short-term"),
    (24, "medium-term"),
    (48, "extended"),
    (96, "long-range"),
]


def timeline_label(hours: float) -> str:
    for threshold, label in TIMELINE_LABELS:
        if hours <= threshold:
            return f"{label} ({hours:.0f}h)"
    return f"far-horizon ({hours:.0f}h)"


class InsightOracle:
    """
    Synthesises the propagation graph and divergent threads
    into ranked, actionable insights.
    """

    def __init__(self, max_insights: int = 10):
        self.max_insights = max_insights

    def generate_report(
        self,
        graph: TemporalGraph,
        threads: List[FutureThread],
        scenario_name: str = "",
    ) -> OracleReport:
        """
        Main entry point: graph + threads → OracleReport with ranked insights.
        """
        report = OracleReport(
            scenario_name=scenario_name,
            total_seeds=len(graph.get_roots()),
            total_graph_nodes=graph.node_count,
            total_threads=len(threads),
        )

        # Generate seed summary
        roots = graph.get_roots()
        report.seed_summary = self._summarise_seeds(roots)

        # Generate insights from threads
        raw_insights: List[Insight] = []
        for thread in threads:
            insight = self._thread_to_insight(thread, graph)
            if insight:
                raw_insights.append(insight)

        # Rank by propensity (descending)
        raw_insights.sort(key=lambda i: i.propensity_pct, reverse=True)

        # Deduplicate similar insights (keep highest propensity)
        deduped = self._deduplicate(raw_insights)

        # Assign ranks and cap
        for i, insight in enumerate(deduped[: self.max_insights]):
            insight.rank = i + 1
        report.insights = deduped[: self.max_insights]

        # Detect anomalies
        report.anomalies = self._detect_anomalies(report.insights, graph)

        return report

    def _summarise_seeds(self, roots: List[EventSeed]) -> str:
        """One-line summary of initial event seeds."""
        if not roots:
            return "No event seeds detected."
        parts = []
        for seed in roots:
            loc = seed.nearest_critical[2] if seed.nearest_critical else f"{seed.lat:.2f}°N,{seed.lon:.2f}°E"
            obs_count = seed.metadata.get("cluster_size", len(seed.observables))
            parts.append(
                f"{seed.event_type.value} ({obs_count} obs) near {loc}"
            )
        return " | ".join(parts)

    def _thread_to_insight(
        self, thread: FutureThread, main_graph: TemporalGraph
    ) -> Optional[Insight]:
        """Convert a future thread into a structured insight."""
        if not thread.terminal_events:
            return None

        # Build the causal chain narrative
        chain_labels: List[str] = []
        key_risks: List[str] = []
        all_cascades: List[Dict[str, Any]] = []

        # Trace from root to most-momentum leaf
        best_leaf = max(
            thread.terminal_events,
            key=lambda e: thread.sub_graph.get_chain_momentum(e.event_id),
        )

        # Walk the path from root
        path = self._trace_path(thread.sub_graph, thread.root_seed_id, best_leaf.event_id)

        for node_id in path:
            seed = thread.sub_graph.get_seed(node_id)
            if not seed:
                continue
            verb = EVENT_VERBS.get(seed.event_type, seed.event_type.value)
            loc = seed.nearest_critical[2] if seed.nearest_critical else f"{seed.lat:.2f}°N"
            chain_labels.append(f"{verb} @ {loc}")

            # Collect cascade effects
            cascades = seed.metadata.get("cascade_effects", [])
            for c in cascades:
                all_cascades.append(c)
                if c.get("category") == "supply_chain":
                    key_risks.append(c["effect"])

        if not chain_labels:
            return None

        # Compute propensity as percentage
        propensity = thread.total_momentum * 100

        # Build summary line
        summary = self._build_summary(
            chain_labels, propensity, thread.timeline_hours, all_cascades
        )

        # Divergence note
        divergence = ""
        if thread.branch_type == "wildcard":
            divergence = "LOW-PROBABILITY WILDCARD — treat as contingency scenario only."
        elif thread.branch_type == "optimistic":
            divergence = "Containment pathway — assumes effective emergency response."

        return Insight(
            rank=0,  # assigned later
            propensity_pct=round(propensity, 1),
            summary=summary,
            chain=chain_labels,
            timeline_hours=round(thread.timeline_hours, 1),
            key_risks=key_risks[:5],
            cascade_effects=all_cascades[:10],
            branch_type=thread.branch_type,
            thread_id=thread.thread_id,
            divergence_note=divergence,
        )

    def _build_summary(
        self,
        chain: List[str],
        propensity_pct: float,
        timeline_hours: float,
        cascades: List[Dict],
    ) -> str:
        """Build the headline summary string."""
        tl = timeline_label(timeline_hours)
        chain_short = " → ".join(chain[:4])
        if len(chain) > 4:
            chain_short += f" → (+{len(chain) - 4} more)"

        # Find the most impactful cascade
        supply_cascades = [c for c in cascades if c.get("category") == "supply_chain"]
        cascade_note = ""
        if supply_cascades:
            top = max(supply_cascades, key=lambda c: c.get("propensity", 0))
            cascade_note = f" → {top['effect']} ({top.get('timeline_hours', '?')}h)"

        return (
            f"{propensity_pct:.0f}% propensity: {chain_short}"
            f"{cascade_note} [{tl}]"
        )

    def _trace_path(
        self, graph: TemporalGraph, start_id: str, end_id: str
    ) -> List[str]:
        """Find the path from start to end in the sub-graph."""
        import networkx as nx
        try:
            return nx.shortest_path(graph.G, start_id, end_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return [start_id]

    def _deduplicate(self, insights: List[Insight]) -> List[Insight]:
        """Remove near-duplicate insights (same chain prefix + similar propensity)."""
        seen_prefixes: set = set()
        deduped: List[Insight] = []
        for insight in insights:
            prefix = tuple(insight.chain[:3])
            key = (prefix, insight.branch_type)
            if key not in seen_prefixes:
                seen_prefixes.add(key)
                deduped.append(insight)
        return deduped

    def _detect_anomalies(
        self, insights: List[Insight], graph: TemporalGraph
    ) -> List[str]:
        """Flag anomalous patterns across insights."""
        anomalies: List[str] = []

        # Check for divergent high-propensity pessimistic chains
        pessimistic_high = [
            i for i in insights
            if i.branch_type == "pessimistic" and i.propensity_pct > 50
        ]
        if len(pessimistic_high) >= 3:
            anomalies.append(
                f"ALERT: {len(pessimistic_high)} high-propensity escalation "
                f"pathways detected. Multi-vector threat likely."
            )

        # Check for rapid timeline (events within 2 hours)
        rapid = [i for i in insights if i.timeline_hours < 2 and i.propensity_pct > 30]
        if rapid:
            anomalies.append(
                f"URGENT: {len(rapid)} rapid-cascade futures (< 2h). "
                f"Immediate situational awareness recommended."
            )

        # Check for supply chain clustering
        supply_risks = set()
        for insight in insights:
            for r in insight.key_risks:
                supply_risks.add(r)
        if len(supply_risks) >= 3:
            anomalies.append(
                f"SUPPLY CHAIN: {len(supply_risks)} distinct disruption vectors. "
                f"Compound economic impact probable."
            )

        return anomalies


def format_report_text(report: OracleReport) -> str:
    """Format OracleReport as plain text for console / log output."""
    lines = [
        "=" * 72,
        "  PANOPTICON DARK KNIGHT — INSIGHT ORACLE REPORT",
        "=" * 72,
        f"  Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"  Scenario:  {report.scenario_name}",
        f"  Seeds: {report.total_seeds} | Graph nodes: {report.total_graph_nodes} | Threads: {report.total_threads}",
        "-" * 72,
        f"  SEEDS: {report.seed_summary}",
        "-" * 72,
    ]

    if report.anomalies:
        lines.append("")
        lines.append("  *** ANOMALY ALERTS ***")
        for a in report.anomalies:
            lines.append(f"  ! {a}")
        lines.append("")

    lines.append("  RANKED FUTURES:")
    lines.append("")

    for insight in report.insights:
        marker = {"optimistic": "+", "pessimistic": "-", "wildcard": "?"}
        m = marker.get(insight.branch_type, " ")
        lines.append(f"  #{insight.rank} [{m}] {insight.summary}")
        lines.append(f"       Chain: {' → '.join(insight.chain[:5])}")
        if insight.key_risks:
            lines.append(f"       Risks: {', '.join(insight.key_risks[:3])}")
        if insight.divergence_note:
            lines.append(f"       Note:  {insight.divergence_note}")
        lines.append("")

    lines.append("=" * 72)
    lines.append('  "This is a contingency tool. Power like this demands restraint."')
    lines.append("=" * 72)

    return "\n".join(lines)

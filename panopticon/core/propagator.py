"""
Bicycle-Chain Propagation Engine
================================
The core physics of foresight.

Like a bicycle chain: efficient force transfer with minimal loss.
Each link (event→event) transmits momentum proportional to propensity.
Friction = decay over time and distance. Sluice gates control flow.

Propensity formula:
    p = σ(w1*intensity + w2*proximity_to_critical + w3*persistence + bias + noise)

Chain momentum:
    M(path) = ∏ p_i  (cumulative product along chain)

This preserves high-probability chains while naturally decaying weak ones.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from panopticon.config import (
    CRITICAL_NODES,
    PropagationWeights,
    SluiceConfig,
    ThreadingConfig,
)
from panopticon.core.events import (
    EventSeed,
    EventType,
    find_nearest_critical,
    haversine_km,
)
from panopticon.core.graph import TemporalGraph


def sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


# ---------------------------------------------------------------------------
# Causal transition templates
# "What can this event type cause next?"
# ---------------------------------------------------------------------------

# Maps source event type → list of (target_type, base_weight, description)
CAUSAL_TEMPLATES: Dict[EventType, List[Tuple[EventType, float, str]]] = {
    EventType.STRIKE_BARRAGE: [
        (EventType.STRUCTURAL_COLLAPSE, 0.85, "blast damage to structures"),
        (EventType.INDUSTRIAL_FIRE, 0.70, "secondary fires from impacts"),
        (EventType.SMOKE_CORRIDOR, 0.60, "smoke from burning infrastructure"),
        (EventType.MILITARY_ACTIVITY, 0.40, "retaliatory mobilization"),
    ],
    EventType.STRUCTURAL_COLLAPSE: [
        (EventType.INDUSTRIAL_FIRE, 0.50, "ruptured fuel/gas lines"),
        (EventType.SMOKE_CORRIDOR, 0.45, "dust and debris plumes"),
    ],
    EventType.INDUSTRIAL_FIRE: [
        (EventType.SMOKE_CORRIDOR, 0.80, "sustained smoke generation"),
        (EventType.WILDFIRE_SPREAD, 0.30, "fire spread to adjacent areas"),
        (EventType.STRUCTURAL_COLLAPSE, 0.25, "heat-weakened structures"),
    ],
    EventType.WILDFIRE_SPREAD: [
        (EventType.SMOKE_CORRIDOR, 0.75, "extensive smoke"),
        (EventType.INDUSTRIAL_FIRE, 0.20, "reaches industrial zone"),
    ],
    EventType.SMOKE_CORRIDOR: [
        # Smoke itself doesn't cause much, but signals persistence
    ],
    EventType.MILITARY_ACTIVITY: [
        (EventType.STRIKE_BARRAGE, 0.55, "escalation / follow-up strikes"),
        (EventType.ANOMALOUS_THERMAL, 0.30, "equipment thermal signatures"),
    ],
    EventType.ANOMALOUS_THERMAL: [
        (EventType.INDUSTRIAL_FIRE, 0.35, "thermal source ignition"),
        (EventType.MILITARY_ACTIVITY, 0.20, "military origin suspected"),
    ],
    EventType.UNKNOWN_CLUSTER: [
        (EventType.ANOMALOUS_THERMAL, 0.25, "unclassified thermal event"),
    ],
}

# ---------------------------------------------------------------------------
# Supply-chain / geopolitical cascade templates
# "What downstream effects does proximity to critical infra cause?"
# ---------------------------------------------------------------------------

@dataclass
class CascadeEffect:
    description: str
    propensity_boost: float  # added to base propensity
    timeline_hours: float    # estimated time to manifest
    category: str            # "supply_chain", "economic", "humanitarian"


CRITICAL_CASCADE: Dict[str, List[CascadeEffect]] = {
    "port": [
        CascadeEffect("shipping lane disruption", 0.15, 4.0, "supply_chain"),
        CascadeEffect("commodity price spike", 0.10, 12.0, "economic"),
        CascadeEffect("port evacuation", 0.20, 1.0, "humanitarian"),
    ],
    "airport": [
        CascadeEffect("flight diversions / no-fly zone", 0.20, 1.0, "supply_chain"),
        CascadeEffect("insurance rate surge", 0.08, 24.0, "economic"),
    ],
    "oil": [
        CascadeEffect("oil supply disruption", 0.25, 6.0, "supply_chain"),
        CascadeEffect("energy price spike", 0.20, 8.0, "economic"),
        CascadeEffect("environmental contamination", 0.15, 2.0, "humanitarian"),
    ],
    "chokepoint": [
        CascadeEffect("global shipping bottleneck", 0.30, 8.0, "supply_chain"),
        CascadeEffect("trade route repricing", 0.15, 24.0, "economic"),
    ],
    "military": [
        CascadeEffect("escalation alert", 0.20, 0.5, "supply_chain"),
        CascadeEffect("defense posture change", 0.15, 2.0, "economic"),
    ],
    "urban": [
        CascadeEffect("civilian evacuation", 0.20, 1.0, "humanitarian"),
        CascadeEffect("emergency services overload", 0.15, 0.5, "humanitarian"),
    ],
}


class BicycleChainPropagator:
    """
    The propagation engine. Takes event seeds, builds the causal graph,
    and projects divergent futures.

    Mechanical metaphor: each event is a chain link. Force (momentum)
    transfers through high-propensity connections. Friction (decay)
    bleeds energy from weak links. Sluice gates halt low-momentum paths.
    """

    def __init__(
        self,
        weights: Optional[PropagationWeights] = None,
        sluice: Optional[SluiceConfig] = None,
        threading: Optional[ThreadingConfig] = None,
        rng_seed: int = 42,
    ):
        self.weights = weights or PropagationWeights()
        self.sluice = sluice or SluiceConfig()
        self.threading = threading or ThreadingConfig()
        self.rng = random.Random(rng_seed)
        self.graph = TemporalGraph()
        self._active_branches = 0

    def compute_propensity(
        self,
        source: EventSeed,
        target_type: EventType,
        template_weight: float,
        depth: int,
    ) -> float:
        """
        Core propensity formula:
        p = σ(w1*intensity + w2*proximity + w3*persistence + bias + noise)

        Then modulated by template weight and depth decay.
        """
        w = self.weights
        raw = (
            w.w_intensity * source.intensity
            + w.w_proximity * source.proximity_to_critical
            + w.w_persistence * source.persistence
            + w.bias
            + self.rng.gauss(0, w.noise_scale)
        )
        base_prop = sigmoid(raw)

        # Modulate by causal template weight
        propensity = base_prop * template_weight

        # Depth decay (friction)
        friction = 1.0 - (self.sluice.decay_per_hop * depth)
        propensity *= max(0.1, friction)

        return min(1.0, max(0.0, propensity))

    def get_gate_threshold(self, depth: int, is_flagged_zone: bool = False) -> float:
        """
        Dynamic sluice gate threshold.
        Raises under overload, lowers for flagged high-risk zones.
        """
        if self._active_branches > self.sluice.max_active_branches:
            return self.sluice.overload_gate
        if is_flagged_zone:
            return self.sluice.black_swan_gate
        return self.sluice.base_gate

    def propagate_seeds(
        self,
        seeds: List[EventSeed],
        flagged_zones: Optional[List[Tuple[float, float, float]]] = None,
    ) -> TemporalGraph:
        """
        Main propagation loop.
        Takes initial seeds, builds the full causal graph with
        divergent futures.

        flagged_zones: list of (lat, lon, radius_km) for lowered gates
        """
        flagged = flagged_zones or []

        # Add root seeds to graph
        for seed in seeds:
            self.graph.add_seed(seed)

        # BFS-style propagation with beam pruning
        frontier: List[EventSeed] = list(seeds)
        visited_ids = {s.event_id for s in seeds}

        for depth in range(1, self.threading.max_depth + 1):
            if not frontier:
                break

            next_frontier: List[EventSeed] = []

            for source in frontier:
                # Get causal templates for this event type
                templates = CAUSAL_TEMPLATES.get(source.event_type, [])
                if not templates:
                    continue

                # Check if source is in a flagged zone
                is_flagged = any(
                    haversine_km(source.lat, source.lon, fz[0], fz[1]) < fz[2]
                    for fz in flagged
                )

                gate = self.get_gate_threshold(depth, is_flagged)

                children: List[Tuple[EventSeed, float]] = []

                for target_type, template_weight, description in templates:
                    propensity = self.compute_propensity(
                        source, target_type, template_weight, depth
                    )

                    # Sluice gate check
                    if propensity < gate:
                        continue

                    # Compute chain momentum (cumulative product)
                    parent_momentum = self.graph.get_chain_momentum(source.event_id)
                    chain_momentum = parent_momentum * propensity

                    # Create the child event
                    child = self._spawn_child(source, target_type, depth, description)

                    # Add cascade effects if near critical infrastructure
                    self._add_cascade_metadata(child, propensity)

                    children.append((child, propensity))

                    # Add to graph
                    self.graph.add_seed(child)
                    self.graph.add_causal_link(
                        source.event_id,
                        child.event_id,
                        propensity=propensity,
                        momentum=chain_momentum,
                        link_type="causal",
                        metadata={"description": description, "depth": depth},
                    )

                    self._active_branches += 1

                # Beam pruning: keep top-K children
                children.sort(key=lambda x: x[1], reverse=True)
                top_k = children[: self.threading.top_k]

                for child, _ in top_k:
                    if child.event_id not in visited_ids:
                        next_frontier.append(child)
                        visited_ids.add(child.event_id)

            frontier = next_frontier

        return self.graph

    def _spawn_child(
        self,
        parent: EventSeed,
        target_type: EventType,
        depth: int,
        description: str,
    ) -> EventSeed:
        """Create a child event seed from a parent + causal template."""
        # Spatial jitter: events propagate nearby
        lat_jitter = self.rng.gauss(0, 0.01 * depth)
        lon_jitter = self.rng.gauss(0, 0.01 * depth)

        # Temporal offset: deeper events are further in the future
        time_offset = timedelta(
            minutes=self.rng.uniform(5, 30) * depth
        )

        # Intensity decays with depth
        intensity_decay = max(0.1, 1.0 - 0.1 * depth)
        child_intensity = parent.intensity * intensity_decay * self.rng.uniform(0.7, 1.0)

        nearest, proximity = find_nearest_critical(
            parent.lat + lat_jitter, parent.lon + lon_jitter
        )

        return EventSeed(
            event_type=target_type,
            lat=parent.lat + lat_jitter,
            lon=parent.lon + lon_jitter,
            timestamp=parent.timestamp + time_offset,
            intensity=min(1.0, child_intensity),
            confidence=parent.confidence * 0.9,  # confidence decays
            persistence=min(1.0, parent.persistence + 0.1),
            nearest_critical=nearest,
            proximity_to_critical=proximity,
            depth=depth,
            parent_id=parent.event_id,
            metadata={"cause": description},
        )

    def _add_cascade_metadata(self, seed: EventSeed, propensity: float) -> None:
        """Annotate event with downstream cascade effects based on infra proximity."""
        if not seed.nearest_critical:
            return
        category = seed.nearest_critical[3]
        cascades = CRITICAL_CASCADE.get(category, [])
        if cascades:
            seed.metadata["cascade_effects"] = [
                {
                    "effect": c.description,
                    "propensity": min(1.0, propensity + c.propensity_boost),
                    "timeline_hours": c.timeline_hours,
                    "category": c.category,
                }
                for c in cascades
            ]

    def inject_wildcard(
        self,
        parent_id: str,
        wildcard_type: EventType,
        wildcard_label: str,
        forced_propensity: float = 0.15,
    ) -> Optional[EventSeed]:
        """
        Black swan injector: force a low-probability event into the graph.
        "What if there's a secondary explosion? A cyber false-flag?"

        This is the counterfactual engine.
        """
        parent = self.graph.get_seed(parent_id)
        if not parent:
            return None

        child = self._spawn_child(
            parent, wildcard_type, parent.depth + 1, f"WILDCARD: {wildcard_label}"
        )
        child.confidence = forced_propensity
        child.metadata["wildcard"] = True
        child.metadata["wildcard_label"] = wildcard_label

        parent_momentum = self.graph.get_chain_momentum(parent_id)
        chain_momentum = parent_momentum * forced_propensity

        self.graph.add_seed(child)
        self.graph.add_causal_link(
            parent_id,
            child.event_id,
            propensity=forced_propensity,
            momentum=chain_momentum,
            link_type="wildcard",
            metadata={"wildcard_label": wildcard_label},
        )

        return child

"""
Divergent Threading & Counterfactuals
=====================================
Beam-search style exploration of futures from each seed node.
Branches: optimistic (containment), pessimistic (escalation),
wildcard (black swan injection).

Each thread maintains independent propensity decay.
Think of it as pulling multiple chains simultaneously —
each taking a different path through the gearbox.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from panopticon.config import ThreadingConfig
from panopticon.core.events import EventSeed, EventType, find_nearest_critical
from panopticon.core.graph import TemporalGraph


@dataclass
class FutureThread:
    """
    A single divergent future — one possible chain of events.
    Contains its own sub-graph branching from a root seed.
    """
    thread_id: str
    branch_type: str  # "optimistic", "pessimistic", "wildcard"
    root_seed_id: str
    sub_graph: TemporalGraph = field(default_factory=TemporalGraph)
    terminal_events: List[EventSeed] = field(default_factory=list)
    total_momentum: float = 0.0
    description: str = ""
    timeline_hours: float = 0.0


# ---------------------------------------------------------------------------
# Branch modifiers: how optimistic/pessimistic/wildcard affect propagation
# ---------------------------------------------------------------------------

BRANCH_MODIFIERS: Dict[str, Dict[str, float]] = {
    "optimistic": {
        "intensity_mult": 0.6,      # fires are contained
        "persistence_mult": 0.5,    # things die down faster
        "propensity_decay": 1.3,    # faster decay = shorter chains
        "gate_raise": 0.1,          # tighter gates (less propagation)
    },
    "pessimistic": {
        "intensity_mult": 1.3,      # fires spread
        "persistence_mult": 1.4,    # things persist longer
        "propensity_decay": 0.7,    # slower decay = longer chains
        "gate_raise": -0.15,        # looser gates (more propagation)
    },
    "wildcard": {
        "intensity_mult": 1.0,
        "persistence_mult": 1.0,
        "propensity_decay": 0.9,
        "gate_raise": -0.25,        # much looser — let unlikely events through
    },
}


class DivergentThreader:
    """
    Generates divergent future threads from seed events.
    Uses beam search with branch-type modifiers.
    """

    def __init__(
        self,
        config: Optional[ThreadingConfig] = None,
        rng_seed: int = 42,
    ):
        self.config = config or ThreadingConfig()
        self.rng = random.Random(rng_seed)
        self._thread_counter = 0

    def generate_threads(
        self,
        source_graph: TemporalGraph,
        branch_types: Optional[Tuple[str, ...]] = None,
    ) -> List[FutureThread]:
        """
        From the propagated graph, generate divergent future threads.
        Each high-momentum leaf or branch point spawns threads.
        """
        branch_types = branch_types or self.config.branch_types
        threads: List[FutureThread] = []

        # Find high-momentum nodes to branch from
        branch_points = self._select_branch_points(source_graph)

        for seed in branch_points:
            for btype in branch_types:
                thread = self._create_thread(seed, btype, source_graph)
                if thread.terminal_events:
                    threads.append(thread)

        # Sort by total momentum (most likely futures first)
        threads.sort(key=lambda t: t.total_momentum, reverse=True)

        return threads

    def _select_branch_points(self, graph: TemporalGraph) -> List[EventSeed]:
        """
        Select the most significant nodes to branch from.
        Criteria: high momentum, near critical infra, high intensity.
        """
        candidates: List[Tuple[EventSeed, float]] = []

        for node_id in graph.G.nodes():
            seed = graph.get_seed(node_id)
            if not seed:
                continue
            momentum = graph.get_chain_momentum(node_id)
            # Score = momentum * intensity * proximity
            score = momentum * seed.intensity * (0.5 + seed.proximity_to_critical)
            candidates.append((seed, score))

        candidates.sort(key=lambda x: x[1], reverse=True)

        # Take top-K branch points
        max_points = min(self.config.top_k, len(candidates))
        return [c[0] for c in candidates[:max_points]]

    def _create_thread(
        self,
        branch_seed: EventSeed,
        branch_type: str,
        source_graph: TemporalGraph,
    ) -> FutureThread:
        """Create a single future thread from a branch point."""
        self._thread_counter += 1
        thread_id = f"T{self._thread_counter:04d}_{branch_type[:3]}"

        modifiers = BRANCH_MODIFIERS.get(branch_type, BRANCH_MODIFIERS["pessimistic"])

        thread = FutureThread(
            thread_id=thread_id,
            branch_type=branch_type,
            root_seed_id=branch_seed.event_id,
            description=self._describe_thread(branch_seed, branch_type),
        )

        # Build sub-graph: extrapolate from branch point using modifiers
        thread.sub_graph.add_seed(branch_seed)
        self._extrapolate(
            thread, branch_seed, modifiers, depth=0, max_depth=4
        )

        # Compute thread summary
        leaves = thread.sub_graph.get_leaf_nodes()
        thread.terminal_events = leaves
        if leaves:
            momenta = [
                thread.sub_graph.get_chain_momentum(l.event_id) for l in leaves
            ]
            thread.total_momentum = max(momenta) if momenta else 0.0
            time_deltas = [
                (l.timestamp - branch_seed.timestamp).total_seconds() / 3600
                for l in leaves
            ]
            thread.timeline_hours = max(time_deltas) if time_deltas else 0.0

        return thread

    def _extrapolate(
        self,
        thread: FutureThread,
        parent: EventSeed,
        modifiers: Dict[str, float],
        depth: int,
        max_depth: int,
    ) -> None:
        """Recursive extrapolation with branch-type modifiers."""
        if depth >= max_depth:
            return

        from panopticon.core.propagator import CAUSAL_TEMPLATES, sigmoid

        templates = CAUSAL_TEMPLATES.get(parent.event_type, [])
        if not templates:
            return

        children: List[Tuple[EventSeed, float]] = []

        for target_type, base_weight, description in templates:
            # Apply branch modifiers to intensity/persistence
            modified_intensity = parent.intensity * modifiers["intensity_mult"]
            modified_persistence = parent.persistence * modifiers["persistence_mult"]

            # Simplified propensity with modifiers
            raw = (
                0.35 * min(1.0, modified_intensity)
                + 0.30 * parent.proximity_to_critical
                + 0.25 * min(1.0, modified_persistence)
                - 0.5
                + self.rng.gauss(0, 0.05)
            )
            propensity = sigmoid(raw) * base_weight

            # Apply decay modifier
            propensity *= max(0.1, 1.0 - 0.05 * depth * modifiers["propensity_decay"])

            # Gate check with modifier
            gate = 0.6 + modifiers["gate_raise"]
            if propensity < gate and thread.branch_type != "wildcard":
                continue
            # Wildcards pass at lower threshold
            if propensity < 0.1:
                continue

            # Spawn child
            time_offset = timedelta(
                minutes=self.rng.uniform(10, 60) * (depth + 1)
            )
            lat_jitter = self.rng.gauss(0, 0.005 * (depth + 1))
            lon_jitter = self.rng.gauss(0, 0.005 * (depth + 1))

            nearest, proximity = find_nearest_critical(
                parent.lat + lat_jitter, parent.lon + lon_jitter
            )

            child = EventSeed(
                event_type=target_type,
                lat=parent.lat + lat_jitter,
                lon=parent.lon + lon_jitter,
                timestamp=parent.timestamp + time_offset,
                intensity=min(1.0, modified_intensity * self.rng.uniform(0.6, 1.0)),
                confidence=parent.confidence * 0.85,
                persistence=min(1.0, modified_persistence + 0.1),
                nearest_critical=nearest,
                proximity_to_critical=proximity,
                depth=parent.depth + depth + 1,
                parent_id=parent.event_id,
                metadata={
                    "cause": description,
                    "branch_type": thread.branch_type,
                    "thread_id": thread.thread_id,
                },
            )

            # Add cascade metadata
            if nearest:
                category = nearest[3]
                from panopticon.core.propagator import CRITICAL_CASCADE
                cascades = CRITICAL_CASCADE.get(category, [])
                if cascades:
                    child.metadata["cascade_effects"] = [
                        {
                            "effect": c.description,
                            "propensity": min(1.0, propensity + c.propensity_boost),
                            "timeline_hours": c.timeline_hours,
                            "category": c.category,
                        }
                        for c in cascades
                    ]

            parent_momentum = thread.sub_graph.get_chain_momentum(parent.event_id)
            chain_momentum = parent_momentum * propensity

            thread.sub_graph.add_seed(child)
            thread.sub_graph.add_causal_link(
                parent.event_id,
                child.event_id,
                propensity=propensity,
                momentum=chain_momentum,
                link_type=thread.branch_type,
            )

            children.append((child, propensity))

        # Recurse into top children
        children.sort(key=lambda x: x[1], reverse=True)
        for child, _ in children[:3]:  # limit branching factor
            self._extrapolate(thread, child, modifiers, depth + 1, max_depth)

    def _describe_thread(self, seed: EventSeed, branch_type: str) -> str:
        """Generate a human-readable thread description."""
        loc = seed.nearest_critical[2] if seed.nearest_critical else f"{seed.lat:.2f}°N"
        prefixes = {
            "optimistic": "CONTAINMENT",
            "pessimistic": "ESCALATION",
            "wildcard": "BLACK SWAN",
        }
        prefix = prefixes.get(branch_type, branch_type.upper())
        return f"[{prefix}] {seed.event_type.value} @ {loc}"

    def inject_user_wildcard(
        self,
        source_graph: TemporalGraph,
        parent_id: str,
        wildcard_label: str,
        wildcard_type: EventType = EventType.STRIKE_BARRAGE,
    ) -> Optional[FutureThread]:
        """
        User-forced wildcard injection.
        "What if there's a cyber false-flag? A secondary explosion?"
        """
        parent = source_graph.get_seed(parent_id)
        if not parent:
            return None

        self._thread_counter += 1
        thread_id = f"T{self._thread_counter:04d}_wld"

        thread = FutureThread(
            thread_id=thread_id,
            branch_type="wildcard",
            root_seed_id=parent_id,
            description=f"[USER WILDCARD] {wildcard_label} @ {parent.label}",
        )

        # Create the wildcard event
        wildcard_seed = EventSeed(
            event_type=wildcard_type,
            lat=parent.lat + self.rng.gauss(0, 0.01),
            lon=parent.lon + self.rng.gauss(0, 0.01),
            timestamp=parent.timestamp + timedelta(minutes=self.rng.uniform(5, 60)),
            intensity=self.rng.uniform(0.5, 0.9),
            confidence=0.15,  # low confidence — it's a wildcard
            persistence=0.3,
            nearest_critical=parent.nearest_critical,
            proximity_to_critical=parent.proximity_to_critical,
            depth=parent.depth + 1,
            parent_id=parent_id,
            metadata={
                "wildcard": True,
                "wildcard_label": wildcard_label,
                "branch_type": "wildcard",
                "thread_id": thread_id,
            },
        )

        thread.sub_graph.add_seed(parent)
        thread.sub_graph.add_seed(wildcard_seed)
        thread.sub_graph.add_causal_link(
            parent_id, wildcard_seed.event_id,
            propensity=0.15, momentum=0.15,
            link_type="wildcard",
        )

        # Extrapolate from wildcard
        modifiers = BRANCH_MODIFIERS["wildcard"]
        self._extrapolate(thread, wildcard_seed, modifiers, depth=0, max_depth=3)

        leaves = thread.sub_graph.get_leaf_nodes()
        thread.terminal_events = leaves
        thread.total_momentum = 0.15
        if leaves:
            time_deltas = [
                (l.timestamp - parent.timestamp).total_seconds() / 3600
                for l in leaves
            ]
            thread.timeline_hours = max(time_deltas) if time_deltas else 0.0

        return thread

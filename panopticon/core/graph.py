"""
Temporal Directed Graph
=======================
The world-state representation: nodes are events, edges are causal
momentum links. Built on NetworkX for flexibility.

Think of it as the chain assembly — each link connected with purpose.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from panopticon.core.events import EventSeed


class TemporalGraph:
    """
    Directed temporal graph for event propagation.

    Nodes: EventSeed instances (keyed by event_id)
    Edges: causal links with propensity scores and metadata
    """

    def __init__(self):
        self.G: nx.DiGraph = nx.DiGraph()
        self._seed_index: Dict[str, EventSeed] = {}

    @property
    def node_count(self) -> int:
        return self.G.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.G.number_of_edges()

    def add_seed(self, seed: EventSeed) -> None:
        """Add an event seed as a node."""
        self._seed_index[seed.event_id] = seed
        self.G.add_node(
            seed.event_id,
            seed=seed,
            event_type=seed.event_type.value,
            lat=seed.lat,
            lon=seed.lon,
            timestamp=seed.timestamp.isoformat(),
            intensity=seed.intensity,
            confidence=seed.confidence,
            depth=seed.depth,
            label=seed.label,
        )

    def add_causal_link(
        self,
        source_id: str,
        target_id: str,
        propensity: float,
        momentum: float,
        link_type: str = "causal",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Add a causal momentum link between two events.
        propensity: edge-level probability (0–1)
        momentum: cumulative chain momentum up to this point
        """
        self.G.add_edge(
            source_id,
            target_id,
            propensity=propensity,
            momentum=momentum,
            link_type=link_type,
            **(metadata or {}),
        )

    def get_seed(self, event_id: str) -> Optional[EventSeed]:
        return self._seed_index.get(event_id)

    def get_roots(self) -> List[EventSeed]:
        """Get all root nodes (no incoming edges = original seeds)."""
        return [
            self._seed_index[n]
            for n in self.G.nodes()
            if self.G.in_degree(n) == 0 and n in self._seed_index
        ]

    def get_children(self, event_id: str) -> List[Tuple[EventSeed, float, float]]:
        """Get child events with (seed, propensity, momentum)."""
        children = []
        for _, target, data in self.G.out_edges(event_id, data=True):
            seed = self._seed_index.get(target)
            if seed:
                children.append((seed, data["propensity"], data["momentum"]))
        return children

    def get_ancestors(self, event_id: str) -> List[str]:
        """Get all ancestor node IDs."""
        return list(nx.ancestors(self.G, event_id))

    def get_chain_momentum(self, event_id: str) -> float:
        """
        Get the cumulative chain momentum to reach this node.
        Product of propensities along the highest-momentum path from root.
        """
        if self.G.in_degree(event_id) == 0:
            seed = self._seed_index.get(event_id)
            return seed.confidence if seed else 1.0

        max_momentum = 0.0
        for source, _, data in self.G.in_edges(event_id, data=True):
            max_momentum = max(max_momentum, data.get("momentum", 0.0))
        return max_momentum

    def get_all_paths_from(self, root_id: str, max_depth: int = 10) -> List[List[str]]:
        """Get all paths from a root node, up to max_depth."""
        paths = []
        stack = [(root_id, [root_id])]
        while stack:
            node, path = stack.pop()
            if len(path) > max_depth:
                continue
            successors = list(self.G.successors(node))
            if not successors:
                paths.append(path)
            else:
                for succ in successors:
                    stack.append((succ, path + [succ]))
        return paths

    def get_leaf_nodes(self) -> List[EventSeed]:
        """Get all leaf nodes (no outgoing edges = terminal futures)."""
        return [
            self._seed_index[n]
            for n in self.G.nodes()
            if self.G.out_degree(n) == 0 and n in self._seed_index
        ]

    def subgraph_from(self, root_id: str) -> TemporalGraph:
        """Extract the sub-graph rooted at a given node."""
        descendants = nx.descendants(self.G, root_id) | {root_id}
        sub = TemporalGraph()
        sub.G = self.G.subgraph(descendants).copy()
        sub._seed_index = {
            k: v for k, v in self._seed_index.items() if k in descendants
        }
        return sub

    def summary(self) -> Dict[str, Any]:
        """Quick summary stats."""
        depths = [
            self._seed_index[n].depth
            for n in self.G.nodes()
            if n in self._seed_index
        ]
        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "roots": len(self.get_roots()),
            "leaves": len(self.get_leaf_nodes()),
            "max_depth": max(depths) if depths else 0,
            "avg_depth": sum(depths) / len(depths) if depths else 0,
        }

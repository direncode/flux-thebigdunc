"""
Sluice Gates — Dynamic Flow Control
====================================
Controls propagation flow through the causal graph.
Prevents combinatorial explosion while allowing controlled divergence.

Like water gates on a canal: open wide for urgent flows,
restrict to a trickle when the system is overwhelmed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from panopticon.config import SluiceConfig
from panopticon.core.events import EventSeed, EventType

logger = logging.getLogger(__name__)


@dataclass
class GateState:
    """Runtime state of a sluice gate."""
    threshold: float
    passes: int = 0       # events that passed this gate
    blocks: int = 0       # events blocked
    is_overloaded: bool = False

    @property
    def pass_rate(self) -> float:
        total = self.passes + self.blocks
        return self.passes / total if total > 0 else 0.0


class SluiceGateController:
    """
    Manages dynamic sluice gates across the propagation graph.

    Gate types:
    - Per-depth gates: deeper = tighter (reduce speculation noise)
    - Per-type gates: some event types need higher confidence to propagate
    - Zone-override gates: user-flagged zones get looser gates
    - Overload gates: tighten everything when branch count explodes
    """

    def __init__(self, config: Optional[SluiceConfig] = None):
        self.config = config or SluiceConfig()
        self._gates: Dict[str, GateState] = {}
        self._total_active: int = 0
        self._flagged_zones: List[Tuple[float, float, float]] = []

        # Per-event-type base multipliers (some types need more evidence)
        self._type_multipliers: Dict[EventType, float] = {
            EventType.STRIKE_BARRAGE: 0.9,       # high-impact, keep gate relatively low
            EventType.STRUCTURAL_COLLAPSE: 0.95,
            EventType.INDUSTRIAL_FIRE: 1.0,
            EventType.WILDFIRE_SPREAD: 1.1,       # need more evidence for wildfires
            EventType.SMOKE_CORRIDOR: 1.15,       # smoke is common, raise gate
            EventType.MILITARY_ACTIVITY: 0.85,    # critical — lower gate
            EventType.ANOMALOUS_THERMAL: 1.2,     # very common — high gate
            EventType.UNKNOWN_CLUSTER: 1.3,       # unknown = high bar to propagate
        }

    def flag_zone(self, lat: float, lon: float, radius_km: float) -> None:
        """Flag a zone for lowered gates (heightened sensitivity)."""
        self._flagged_zones.append((lat, lon, radius_km))
        logger.info("Sluice: flagged zone (%.2f, %.2f) r=%.0fkm", lat, lon, radius_km)

    def clear_flags(self) -> None:
        self._flagged_zones.clear()

    def get_gate(
        self,
        event_type: EventType,
        depth: int,
        lat: float = 0.0,
        lon: float = 0.0,
    ) -> float:
        """
        Compute the effective gate threshold for a given context.
        Higher threshold = harder to pass = more pruning.
        """
        from panopticon.core.events import haversine_km

        # Base gate
        gate = self.config.base_gate

        # Depth scaling: +0.03 per depth level
        gate += 0.03 * depth

        # Type multiplier
        type_mult = self._type_multipliers.get(event_type, 1.0)
        gate *= type_mult

        # Zone override: if near a flagged zone, lower the gate
        for fz_lat, fz_lon, fz_radius in self._flagged_zones:
            dist = haversine_km(lat, lon, fz_lat, fz_lon)
            if dist < fz_radius:
                gate = min(gate, self.config.black_swan_gate)
                break

        # Overload protection
        if self._total_active > self.config.max_active_branches:
            gate = max(gate, self.config.overload_gate)
            logger.warning(
                "Sluice OVERLOAD: %d active branches, gate raised to %.2f",
                self._total_active, gate,
            )

        return min(1.0, max(0.0, gate))

    def check_pass(
        self,
        propensity: float,
        event_type: EventType,
        depth: int,
        lat: float = 0.0,
        lon: float = 0.0,
    ) -> bool:
        """
        Should this event pass the sluice gate?
        Returns True if propensity exceeds the gate threshold.
        """
        gate = self.get_gate(event_type, depth, lat, lon)
        key = f"{event_type.value}_d{depth}"

        if key not in self._gates:
            self._gates[key] = GateState(threshold=gate)

        passed = propensity >= gate
        if passed:
            self._gates[key].passes += 1
            self._total_active += 1
        else:
            self._gates[key].blocks += 1

        return passed

    def record_pruned(self, count: int) -> None:
        """Record that branches were pruned (reduces active count)."""
        self._total_active = max(0, self._total_active - count)

    def diagnostics(self) -> Dict[str, Dict]:
        """Gate diagnostics for debugging/dashboard."""
        return {
            key: {
                "threshold": gs.threshold,
                "passes": gs.passes,
                "blocks": gs.blocks,
                "pass_rate": f"{gs.pass_rate:.1%}",
            }
            for key, gs in self._gates.items()
        }

    @property
    def total_active(self) -> int:
        return self._total_active

    @property
    def is_overloaded(self) -> bool:
        return self._total_active > self.config.max_active_branches

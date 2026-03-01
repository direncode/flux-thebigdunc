"""
Event Seed Classifier
=====================
Converts raw Observables into Event nodes for the propagation graph.
Clustering logic: nearby observables in space+time → single event seed.

No interpretation. No guessing. Just physics → pattern → seed.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from panopticon.config import CRITICAL_NODES, CriticalNode
from panopticon.ingest.base import Observable, ObservableType


class EventType(Enum):
    """Classified event types derived from observable clusters."""
    STRIKE_BARRAGE = "strike_barrage"
    STRUCTURAL_COLLAPSE = "structural_collapse"
    INDUSTRIAL_FIRE = "industrial_fire"
    WILDFIRE_SPREAD = "wildfire_spread"
    SMOKE_CORRIDOR = "smoke_corridor"
    ANOMALOUS_THERMAL = "anomalous_thermal"
    MILITARY_ACTIVITY = "military_activity"
    UNKNOWN_CLUSTER = "unknown_cluster"


@dataclass
class EventSeed:
    """
    A classified event node in the propagation graph.
    Born from clustered observables, ready to propagate.
    """
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    event_type: EventType = EventType.UNKNOWN_CLUSTER
    lat: float = 0.0
    lon: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    intensity: float = 0.0       # aggregate 0–1
    confidence: float = 0.0      # aggregate 0–1
    persistence: float = 0.0     # how long it's been active (normalised)
    observables: List[Observable] = field(default_factory=list)
    nearest_critical: Optional[CriticalNode] = None
    proximity_to_critical: float = 0.0  # 0–1 (1 = on top of it)
    depth: int = 0               # propagation depth from root
    parent_id: Optional[str] = None
    metadata: Dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        loc = self.nearest_critical[2] if self.nearest_critical else f"{self.lat:.2f},{self.lon:.2f}"
        return f"{self.event_type.value}@{loc}"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_critical(lat: float, lon: float) -> Tuple[Optional[CriticalNode], float]:
    """
    Find nearest critical infrastructure node.
    Returns (node, proximity_score) where proximity 1.0 = within 1km,
    decays exponentially with distance.
    """
    best_node = None
    best_dist = float("inf")
    for node in CRITICAL_NODES:
        d = haversine_km(lat, lon, node[0], node[1])
        if d < best_dist:
            best_dist = d
            best_node = node

    # Proximity: exponential decay. 1.0 at 0km, ~0.5 at 5km, ~0.1 at 20km
    proximity = math.exp(-best_dist / 7.0) if best_dist < 200 else 0.0
    return best_node, proximity


def cluster_observables(
    observables: List[Observable],
    radius_km: float = 2.0,
    time_window: timedelta = timedelta(minutes=10),
) -> List[List[Observable]]:
    """
    Simple spatial-temporal clustering.
    Groups observables within radius_km and time_window of each other.
    Uses greedy leader-follower approach (fast, good enough for real-time).
    """
    if not observables:
        return []

    sorted_obs = sorted(observables, key=lambda o: o.timestamp)
    clusters: List[List[Observable]] = []
    assigned = set()

    for i, obs in enumerate(sorted_obs):
        if i in assigned:
            continue
        cluster = [obs]
        assigned.add(i)
        for j in range(i + 1, len(sorted_obs)):
            if j in assigned:
                continue
            other = sorted_obs[j]
            # Time window check
            if other.timestamp - obs.timestamp > time_window:
                break  # sorted, so no more matches
            # Spatial check
            if haversine_km(obs.lat, obs.lon, other.lat, other.lon) <= radius_km:
                cluster.append(other)
                assigned.add(j)
        clusters.append(cluster)

    return clusters


def classify_cluster(cluster: List[Observable]) -> EventType:
    """
    Determine event type from a cluster of observables.
    Pure pattern matching on observable types and counts.
    """
    type_counts: Dict[ObservableType, int] = {}
    for obs in cluster:
        type_counts[obs.obs_type] = type_counts.get(obs.obs_type, 0) + 1

    n_thermal = type_counts.get(ObservableType.THERMAL_HOTSPOT, 0)
    n_sar = type_counts.get(ObservableType.SAR_CHANGE, 0)
    n_plume = type_counts.get(ObservableType.SMOKE_PLUME, 0)

    avg_conf = sum(o.confidence for o in cluster) / len(cluster)
    avg_intensity = sum(o.intensity for o in cluster) / len(cluster)

    # 5+ high-conf hotspots in tight radius → strike barrage
    if n_thermal >= 5 and avg_conf > 0.7 and avg_intensity > 0.5:
        return EventType.STRIKE_BARRAGE

    # SAR change + thermal → structural collapse (blast damage)
    if n_sar >= 1 and n_thermal >= 2:
        return EventType.STRUCTURAL_COLLAPSE

    # Plume + thermal → industrial fire
    if n_plume >= 1 and n_thermal >= 1:
        return EventType.INDUSTRIAL_FIRE

    # SAR only → could be construction, earthquake, etc.
    if n_sar >= 2:
        return EventType.STRUCTURAL_COLLAPSE

    # Thermal cluster but lower confidence → possible wildfire
    if n_thermal >= 3 and avg_conf < 0.7:
        return EventType.WILDFIRE_SPREAD

    # Plume only → smoke corridor
    if n_plume >= 1:
        return EventType.SMOKE_CORRIDOR

    # Thermal with military proximity check
    centroid_lat = sum(o.lat for o in cluster) / len(cluster)
    centroid_lon = sum(o.lon for o in cluster) / len(cluster)
    nearest, prox = find_nearest_critical(centroid_lat, centroid_lon)
    if nearest and nearest[3] == "military" and n_thermal >= 2:
        return EventType.MILITARY_ACTIVITY

    if n_thermal >= 1:
        return EventType.ANOMALOUS_THERMAL

    return EventType.UNKNOWN_CLUSTER


def observables_to_seeds(
    observables: List[Observable],
    cluster_radius_km: float = 2.0,
    cluster_time_window: timedelta = timedelta(minutes=10),
) -> List[EventSeed]:
    """
    Master function: raw observables → classified event seeds.
    This is the entry point from ingestion to propagation.
    """
    clusters = cluster_observables(observables, cluster_radius_km, cluster_time_window)
    seeds: List[EventSeed] = []

    for cluster in clusters:
        event_type = classify_cluster(cluster)

        # Compute centroid
        centroid_lat = sum(o.lat for o in cluster) / len(cluster)
        centroid_lon = sum(o.lon for o in cluster) / len(cluster)

        # Aggregate metrics
        avg_intensity = sum(o.intensity for o in cluster) / len(cluster)
        avg_confidence = sum(o.confidence for o in cluster) / len(cluster)
        earliest = min(o.timestamp for o in cluster)
        latest = max(o.timestamp for o in cluster)
        persistence = min(1.0, (latest - earliest).total_seconds() / 3600.0)

        # Find nearest critical node
        nearest, proximity = find_nearest_critical(centroid_lat, centroid_lon)

        seed = EventSeed(
            event_type=event_type,
            lat=centroid_lat,
            lon=centroid_lon,
            timestamp=earliest,
            intensity=avg_intensity,
            confidence=avg_confidence,
            persistence=persistence,
            observables=cluster,
            nearest_critical=nearest,
            proximity_to_critical=proximity,
            depth=0,
            metadata={
                "cluster_size": len(cluster),
                "duration_minutes": (latest - earliest).total_seconds() / 60,
            },
        )
        seeds.append(seed)

    return seeds

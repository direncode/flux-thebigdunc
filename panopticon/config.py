"""
Panopticon Dark Knight — Global Configuration
=============================================
Critical infrastructure nodes, bounding boxes for high-risk zones,
tunable propagation weights, sluice gate thresholds.

Every parameter here is a lever. Tune carefully.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Propagation weight defaults (sigmoid inputs)
# σ(w1*intensity + w2*proximity_to_critical + w3*persistence + bias + noise)
# ---------------------------------------------------------------------------

@dataclass
class PropagationWeights:
    w_intensity: float = 0.35
    w_proximity: float = 0.30
    w_persistence: float = 0.25
    bias: float = -0.2
    noise_scale: float = 0.05  # σ of Gaussian noise for uncertainty


# ---------------------------------------------------------------------------
# Sluice gate defaults
# ---------------------------------------------------------------------------

@dataclass
class SluiceConfig:
    base_gate: float = 0.45       # default propagation threshold (tuned for depth)
    black_swan_gate: float = 0.25  # lowered for user-flagged zones
    overload_gate: float = 0.75   # raised during combinatorial explosion
    max_active_branches: int = 800  # trigger overload pruning above this
    decay_per_hop: float = 0.03   # friction loss per propagation step
    decay_per_hour: float = 0.02  # temporal decay rate


# ---------------------------------------------------------------------------
# Beam search / divergent threading
# ---------------------------------------------------------------------------

@dataclass
class ThreadingConfig:
    top_k: int = 20              # default beam width
    max_depth: int = 8           # max propagation hops
    branch_types: Tuple[str, ...] = ("optimistic", "pessimistic", "wildcard")
    wildcard_prob_floor: float = 0.05  # minimum prob for black-swan injection


# ---------------------------------------------------------------------------
# Critical infrastructure nodes (lat, lon, name, type)
# These are the "teeth" the bicycle chain grips onto.
# ---------------------------------------------------------------------------

CriticalNode = Tuple[float, float, str, str]  # lat, lon, name, category

CRITICAL_NODES: List[CriticalNode] = [
    # --- Persian Gulf / UAE ---
    (25.0118, 55.0803, "Jebel Ali Port", "port"),
    (25.1124, 55.1390, "Palm Jumeirah", "urban"),
    (25.2532, 55.3657, "Dubai Int'l Airport", "airport"),
    (25.0657, 55.1713, "Dubai Marina", "urban"),
    (24.4539, 54.6513, "Abu Dhabi Port", "port"),
    (26.2285, 50.5860, "Ras Tanura Oil Terminal", "oil"),
    (26.6396, 49.9983, "Khafji Oil Field", "oil"),
    (29.0769, 48.0838, "Kuwait City Port", "port"),
    # --- Taiwan Strait ---
    (25.0330, 121.5654, "Taipei", "urban"),
    (22.6273, 120.3014, "Kaohsiung Port", "port"),
    (24.2640, 120.5277, "Taichung Port", "port"),
    (26.0614, 119.3062, "Fuzhou Air Base", "military"),
    (24.4795, 118.0819, "Xiamen Port", "port"),
    # --- Ukraine / Black Sea ---
    (46.4825, 30.7233, "Odesa Port", "port"),
    (44.6167, 33.5254, "Sevastopol Naval Base", "military"),
    (50.4501, 30.5234, "Kyiv", "urban"),
    (48.0159, 37.8029, "Mariupol", "urban"),
    (47.1015, 37.5432, "Berdiansk Port", "port"),
    # --- Global chokepoints ---
    (30.0444, 31.2357, "Suez Canal (Port Said)", "chokepoint"),
    (12.8628, 45.0377, "Bab el-Mandeb Strait", "chokepoint"),
    (1.2655, 103.8222, "Singapore Strait", "chokepoint"),
    (36.1408, -5.3536, "Strait of Gibraltar", "chokepoint"),
    (51.4934, 0.0098, "London", "urban"),
    (40.7128, -74.0060, "New York", "urban"),
    (35.6762, 139.6503, "Tokyo", "urban"),
    (31.2304, 121.4737, "Shanghai Port", "port"),
]

# Build a lookup dict: (rounded lat, lon) -> node info
CRITICAL_NODE_INDEX: Dict[str, CriticalNode] = {
    f"{lat:.2f},{lon:.2f}": (lat, lon, name, cat)
    for lat, lon, name, cat in CRITICAL_NODES
}


# ---------------------------------------------------------------------------
# High-risk bounding boxes: (min_lat, min_lon, max_lat, max_lon, label)
# Default watch zones.
# ---------------------------------------------------------------------------

BoundingBox = Tuple[float, float, float, float, str]

DEFAULT_WATCH_ZONES: List[BoundingBox] = [
    (24.0, 50.0, 27.0, 56.5, "Persian Gulf / UAE"),
    (22.0, 118.0, 26.5, 122.0, "Taiwan Strait"),
    (44.0, 30.0, 52.0, 40.0, "Ukraine / Black Sea"),
    (10.0, 40.0, 15.0, 50.0, "Bab el-Mandeb / Horn"),
    (28.0, 30.0, 32.0, 35.0, "Suez Canal Zone"),
]


# ---------------------------------------------------------------------------
# Data source endpoints
# ---------------------------------------------------------------------------

FIRMS_CSV_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_MAP_KEY = "DEMO_KEY"  # Replace with real NASA FIRMS API key
SENTINEL_STAC_URL = "https://earth-search.aws.element84.com/v1"
GOES_GCS_BUCKET = "gcp-public-data-goes-16"


# ---------------------------------------------------------------------------
# Session / ethical protocol
# ---------------------------------------------------------------------------

@dataclass
class EthicsConfig:
    session_timeout_minutes: int = 120   # auto-wipe after 2 hours
    require_activation_phrase: bool = True
    activation_phrase: str = "activate contingency"
    auto_log_wipe: bool = True
    warning_message: str = (
        "⚠  PANOPTICON DARK KNIGHT — CONTINGENCY MODE\n"
        "This is a contingency tool. Power like this demands restraint.\n"
        "No individuals are tracked. Only aggregate observables.\n"
        "Session auto-wipes in {timeout} minutes."
    )

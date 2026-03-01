"""
Live Feed Orchestrator
======================
Manages multi-source polling state and drives the full Panopticon pipeline
on each tick.

Design:
- All state in LiveFeedState dataclass (stored in st.session_state)
- poll_next_source() delegates to PollScheduler for multi-source round-robin
- Falls back to FIRMS-only polling if scheduler unavailable
- Dedup by (lat_2dp, lon_2dp, hour_bucket, obs_type, source) hash set
- Graceful fallback: API failures never crash, just set status

"The trick is not to use it unless you absolutely have to."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from panopticon.config import (
    DEFAULT_WATCH_ZONES,
    FIRMS_MAP_KEY,
    BoundingBox,
    LiveFeedConfig,
    PropagationWeights,
    SluiceConfig,
    ThreadingConfig,
)
from panopticon.core.events import EventSeed, EventType, observables_to_seeds
from panopticon.core.graph import TemporalGraph
from panopticon.core.propagator import BicycleChainPropagator
from panopticon.core.threading import DivergentThreader, FutureThread
from panopticon.ingest.base import Observable
from panopticon.ingest.firms import FIRMSIngestor
from panopticon.ingest.simulator import dubai_strike_scenario, taiwan_strait_scenario
from panopticon.oracle.insight import InsightOracle, OracleReport

logger = logging.getLogger(__name__)

# Lazy imports for scheduler (avoid import errors if pyyaml missing)
_scheduler_available = False
try:
    from panopticon.ingest.registry import SourceRegistry
    from panopticon.ingest.scheduler import PollScheduler
    _scheduler_available = True
except ImportError:
    pass


@dataclass
class LiveFeedState:
    """All live feed state. Stored in st.session_state.live_feed."""

    # Multi-source scheduler (None = FIRMS-only fallback)
    scheduler: object = None  # PollScheduler or None

    # Polling metadata
    last_poll_monotonic: Optional[float] = None
    last_poll_utc: Optional[datetime] = None
    poll_count: int = 0
    new_obs_last_poll: int = 0
    zone_index: int = 0
    status: str = "IDLE"
    last_error: Optional[str] = None

    # Accumulated data (deduped)
    all_observables: List[Observable] = field(default_factory=list)
    seen_keys: set = field(default_factory=set)

    # Pipeline outputs
    seeds: List[EventSeed] = field(default_factory=list)
    graph: Optional[TemporalGraph] = None
    threads: List[FutureThread] = field(default_factory=list)
    report: Optional[OracleReport] = None

    # Configuration
    refresh_interval_s: int = 60
    firms_api_key: str = FIRMS_MAP_KEY
    sensor: str = "VIIRS_SNPP_NRT"

    # Feed log (timestamped entries for UI display)
    feed_log: List[str] = field(default_factory=list)


def init_scheduler(state: LiveFeedState) -> None:
    """Initialize the multi-source scheduler if available."""
    if not _scheduler_available:
        logger.info("Scheduler not available — FIRMS-only mode")
        return

    if state.scheduler is not None:
        return  # already initialized

    try:
        registry = SourceRegistry()
        state.scheduler = PollScheduler(registry)
        _log(state, f"Multi-source scheduler initialized: {state.scheduler.get_source_count()} sources")
    except Exception as exc:
        logger.warning("Failed to initialize scheduler: %s — falling back to FIRMS-only", exc)
        state.scheduler = None


def _make_obs_key(obs: Observable) -> str:
    """
    Deduplication fingerprint.
    Key: lat rounded to 0.01°, lon same, hour bucket, obs type, source.
    """
    lat_r = round(obs.lat, 2)
    lon_r = round(obs.lon, 2)
    hour_bucket = obs.timestamp.strftime("%Y%m%d%H")
    return f"{lat_r},{lon_r},{hour_bucket},{obs.obs_type.value},{obs.source}"


def _log(state: LiveFeedState, msg: str) -> None:
    """Add timestamped entry to feed log (capped at 50 entries)."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    state.feed_log.append(entry)
    if len(state.feed_log) > 50:
        state.feed_log = state.feed_log[-50:]
    logger.info("FEED: %s", msg)


def should_poll_now(state: LiveFeedState) -> bool:
    """Check if enough time has elapsed since last poll."""
    if state.last_poll_monotonic is None:
        return True
    elapsed = time.monotonic() - state.last_poll_monotonic
    return elapsed >= state.refresh_interval_s


def poll_next_source(state: LiveFeedState) -> int:
    """
    Poll the next due source (multi-source scheduler or FIRMS fallback).
    Returns count of NEW (deduplicated) observables added.
    """
    if state.scheduler and hasattr(state.scheduler, 'tick'):
        return _poll_via_scheduler(state)
    return _poll_firms_zone(state)


def _poll_via_scheduler(state: LiveFeedState) -> int:
    """Poll next due source via the multi-source scheduler."""
    zones = DEFAULT_WATCH_ZONES
    zone = zones[state.zone_index % len(zones)]
    min_lat, min_lon, max_lat, max_lon, label = zone
    bbox = (min_lat, min_lon, max_lat, max_lon)
    since = datetime.now(timezone.utc) - timedelta(days=1)

    state.status = "POLLING"

    source_id, raw_obs = state.scheduler.tick(bbox, since)

    if source_id == "none":
        _log(state, "No sources due for polling")
        state.last_poll_monotonic = time.monotonic()
        return 0

    # Deduplicate
    new_count = 0
    for obs in raw_obs:
        key = _make_obs_key(obs)
        if key not in state.seen_keys:
            state.seen_keys.add(key)
            state.all_observables.append(obs)
            new_count += 1

    state.new_obs_last_poll = new_count
    state.last_poll_monotonic = time.monotonic()
    state.last_poll_utc = datetime.now(timezone.utc)
    state.poll_count += 1
    state.zone_index = (state.zone_index + 1) % len(zones)

    if new_count > 0:
        state.status = "LIVE"
        _log(state, f"+{new_count} from {source_id} ({len(state.all_observables)} total)")
    else:
        if state.status != "ERROR":
            state.status = "LIVE"
        _log(state, f"0 new from {source_id}")

    state.last_error = None
    return new_count


def _poll_firms_zone(state: LiveFeedState) -> int:
    """Legacy FIRMS-only polling (fallback when scheduler unavailable)."""
    zones = DEFAULT_WATCH_ZONES
    if not zones:
        return 0

    zone = zones[state.zone_index % len(zones)]
    min_lat, min_lon, max_lat, max_lon, label = zone
    bbox = (min_lat, min_lon, max_lat, max_lon)

    state.status = "POLLING"
    _log(state, f"Polling FIRMS: {label}...")

    ingestor = FIRMSIngestor(api_key=state.firms_api_key, sensor=state.sensor)

    try:
        since = datetime.now(timezone.utc) - timedelta(days=1)
        raw_obs = ingestor.poll(bbox, since=since)
    except Exception as exc:
        state.status = "ERROR"
        state.last_error = f"FIRMS poll failed for {label}: {exc}"
        _log(state, f"ERROR: {state.last_error}")
        state.zone_index = (state.zone_index + 1) % len(zones)
        state.last_poll_monotonic = time.monotonic()
        state.last_poll_utc = datetime.now(timezone.utc)
        state.poll_count += 1
        return 0

    new_count = 0
    for obs in raw_obs:
        key = _make_obs_key(obs)
        if key not in state.seen_keys:
            state.seen_keys.add(key)
            state.all_observables.append(obs)
            new_count += 1

    state.new_obs_last_poll = new_count
    state.last_poll_monotonic = time.monotonic()
    state.last_poll_utc = datetime.now(timezone.utc)
    state.poll_count += 1
    state.zone_index = (state.zone_index + 1) % len(zones)

    if new_count > 0:
        state.status = "LIVE"
        _log(state, f"+{new_count} hotspots from {label} ({len(state.all_observables)} total)")
    else:
        if state.status != "ERROR":
            state.status = "LIVE"
        _log(state, f"No new hotspots in {label}")

    state.last_error = None
    return new_count


# Keep legacy name for backward compat
poll_next_zone = poll_next_source


def poll_all_sources(state: LiveFeedState) -> int:
    """Poll multiple sources at once (for initial burst or force-poll)."""
    if state.scheduler and hasattr(state.scheduler, 'tick_burst'):
        zones = DEFAULT_WATCH_ZONES
        zone = zones[state.zone_index % len(zones)]
        min_lat, min_lon, max_lat, max_lon, label = zone
        bbox = (min_lat, min_lon, max_lat, max_lon)
        since = datetime.now(timezone.utc) - timedelta(days=1)

        results = state.scheduler.tick_burst(bbox, since, max_sources=5)
        total_new = 0
        for source_id, raw_obs in results:
            for obs in raw_obs:
                key = _make_obs_key(obs)
                if key not in state.seen_keys:
                    state.seen_keys.add(key)
                    state.all_observables.append(obs)
                    total_new += 1
            if raw_obs:
                _log(state, f"+{len(raw_obs)} from {source_id}")

        state.last_poll_monotonic = time.monotonic()
        state.last_poll_utc = datetime.now(timezone.utc)
        state.poll_count += 1
        state.new_obs_last_poll = total_new
        if total_new > 0:
            state.status = "LIVE"
        return total_new

    # Fallback: poll all FIRMS zones
    total_new = 0
    zones = DEFAULT_WATCH_ZONES
    for i in range(len(zones)):
        state.zone_index = i
        total_new += _poll_firms_zone(state)
    return total_new


# Keep legacy name
poll_all_zones = poll_all_sources


def trim_old_observables(state: LiveFeedState, max_age_hours: int = 6) -> None:
    """Remove observables older than max_age_hours to bound memory."""
    if not state.all_observables:
        return

    reference = max(obs.timestamp for obs in state.all_observables)
    cutoff = reference - timedelta(hours=max_age_hours)
    before = len(state.all_observables)
    state.all_observables = [
        obs for obs in state.all_observables if obs.timestamp >= cutoff
    ]
    trimmed = before - len(state.all_observables)
    if trimmed > 0:
        _log(state, f"Trimmed {trimmed} stale observables (>{max_age_hours}h old)")


def run_full_pipeline(
    state: LiveFeedState,
    weights: Optional[PropagationWeights] = None,
    sluice: Optional[SluiceConfig] = None,
    threading: Optional[ThreadingConfig] = None,
) -> None:
    """
    Run the complete pipeline on state.all_observables.
    Mutates state.seeds, state.graph, state.threads, state.report.
    """
    weights = weights or PropagationWeights()
    sluice = sluice or SluiceConfig()
    threading = threading or ThreadingConfig()

    if not state.all_observables:
        state.seeds = []
        state.graph = None
        state.threads = []
        state.report = None
        return

    trim_old_observables(state)

    seeds = observables_to_seeds(state.all_observables)
    state.seeds = seeds

    if not seeds:
        state.graph = None
        state.threads = []
        state.report = None
        return

    propagator = BicycleChainPropagator(
        weights=weights, sluice=sluice, threading=threading
    )

    flagged_zones = []
    for seed in seeds:
        if seed.proximity_to_critical > 0.5:
            flagged_zones.append((seed.lat, seed.lon, 20.0))

    graph = propagator.propagate_seeds(seeds, flagged_zones=flagged_zones)
    state.graph = graph

    threader = DivergentThreader(config=threading)
    threads = threader.generate_threads(graph)
    state.threads = threads

    oracle = InsightOracle(max_insights=10)

    # Determine scenario name from source diversity
    source_types = {obs.source for obs in state.all_observables}
    if len(source_types) > 1:
        scenario_name = f"Multi-Source Feed ({len(source_types)} sources)"
    else:
        scenario_name = f"Live {next(iter(source_types), 'unknown')} Feed"

    report = oracle.generate_report(graph, threads, scenario_name=scenario_name)
    state.report = report

    _log(state, (
        f"Pipeline: {len(seeds)} seeds -> {graph.node_count} nodes -> "
        f"{len(threads)} threads -> {len(report.insights)} insights"
    ))


def merge_synthetic(state: LiveFeedState, scenario_name: str = "dubai") -> None:
    """Overlay synthetic scenario data for demo/testing."""
    if scenario_name == "taiwan":
        sim = taiwan_strait_scenario()
    else:
        sim = dubai_strike_scenario()

    new_count = 0
    for obs in sim.sorted_by_time():
        key = _make_obs_key(obs)
        if key not in state.seen_keys:
            state.seen_keys.add(key)
            state.all_observables.append(obs)
            new_count += 1

    _log(state, f"Merged {new_count} synthetic observables ({sim.name})")


def get_status_text(state: LiveFeedState) -> str:
    """Formatted status string for display."""
    if state.status == "IDLE":
        return "IDLE — Waiting for activation"

    parts = [state.status]

    if state.last_poll_utc:
        elapsed = (datetime.now(timezone.utc) - state.last_poll_utc).total_seconds()
        parts.append(f"Last poll: {int(elapsed)}s ago")

    parts.append(f"{len(state.all_observables)} observables")

    if state.new_obs_last_poll > 0:
        parts.append(f"+{state.new_obs_last_poll} new")

    # Show scheduler stats if available
    if state.scheduler and hasattr(state.scheduler, 'get_health_summary'):
        summary = state.scheduler.get_health_summary()
        parts.append(f"{summary['healthy']}/{summary['total_sources']} sources")
    else:
        next_zone = DEFAULT_WATCH_ZONES[state.zone_index % len(DEFAULT_WATCH_ZONES)]
        parts.append(f"Next: {next_zone[4]}")

    if state.last_error:
        parts.append(f"ERR: {state.last_error[:60]}")

    return " | ".join(parts)

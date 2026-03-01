"""
Synthetic Observable Generator
==============================
Generates realistic satellite observables for offline testing.
Primary scenario: Dubai/Jebel Ali strike barrage, March 1, 2026.

This is how we test the bicycle chain without waiting for the world to burn.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from panopticon.ingest.base import Observable, ObservableType


class SyntheticScenario:
    """A named collection of synthetic observables with metadata."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.observables: List[Observable] = []

    def add(self, obs: Observable) -> None:
        self.observables.append(obs)

    def sorted_by_time(self) -> List[Observable]:
        return sorted(self.observables, key=lambda o: o.timestamp)


def dubai_strike_scenario(
    base_time: Optional[datetime] = None,
    seed: int = 42,
) -> SyntheticScenario:
    """
    Simulate a multi-phase strike barrage on Jebel Ali / Palm Dumeirah area.

    Timeline:
      T+0:    Initial thermal cluster — 8 high-confidence hotspots near
              Jebel Ali port (25.01°N, 55.08°E). Strike barrage seed.
      T+5m:   Secondary hotspots at Palm Jumeirah (25.11°N, 55.14°E).
      T+15m:  SAR coherence loss detected over Jebel Ali port structures.
      T+20m:  Smoke plumes originating from port, wind bearing 310° (NW).
      T+30m:  Fire spread — new hotspots along coastline.
      T+45m:  Secondary SAR change at Dubai Marina (25.07°N, 55.17°E).
      T+60m:  Plume extends 15km, additional hotspots inland.
      T+90m:  Persistent thermal signature — sustained fire.
    """
    rng = random.Random(seed)
    if base_time is None:
        base_time = datetime(2026, 3, 1, 2, 30, 0, tzinfo=timezone.utc)

    scenario = SyntheticScenario(
        name="Dubai Strike Barrage — March 1, 2026",
        description=(
            "Simulated multi-phase kinetic event at Jebel Ali port complex. "
            "8+ initial thermal hotspots escalating to structural damage, "
            "smoke plumes, and fire spread toward Dubai Marina."
        ),
    )

    def jitter(val: float, scale: float = 0.003) -> float:
        return val + rng.gauss(0, scale)

    # --- T+0: Initial strike cluster at Jebel Ali ---
    for i in range(8):
        scenario.add(Observable(
            obs_type=ObservableType.THERMAL_HOTSPOT,
            lat=jitter(25.0118, 0.005),
            lon=jitter(55.0803, 0.005),
            timestamp=base_time + timedelta(seconds=rng.randint(0, 60)),
            confidence=rng.uniform(0.85, 0.98),
            brightness_temp_k=rng.uniform(420, 510),
            frp_mw=rng.uniform(50, 300),
            source="SIM_FIRMS",
            satellite="SIM_VIIRS",
        ))

    # --- T+5m: Secondary cluster at Palm Jumeirah ---
    t5 = base_time + timedelta(minutes=5)
    for i in range(4):
        scenario.add(Observable(
            obs_type=ObservableType.THERMAL_HOTSPOT,
            lat=jitter(25.1124, 0.004),
            lon=jitter(55.1390, 0.004),
            timestamp=t5 + timedelta(seconds=rng.randint(0, 90)),
            confidence=rng.uniform(0.75, 0.92),
            brightness_temp_k=rng.uniform(380, 460),
            frp_mw=rng.uniform(30, 150),
            source="SIM_FIRMS",
            satellite="SIM_VIIRS",
        ))

    # --- T+15m: SAR coherence loss at Jebel Ali ---
    t15 = base_time + timedelta(minutes=15)
    for i in range(3):
        scenario.add(Observable(
            obs_type=ObservableType.SAR_CHANGE,
            lat=jitter(25.0118, 0.003),
            lon=jitter(55.0803, 0.003),
            timestamp=t15 + timedelta(seconds=rng.randint(0, 30)),
            confidence=0.85,
            sar_coherence_loss=rng.uniform(0.7, 0.95),
            change_mask_pct=rng.uniform(15, 45),
            source="SIM_SAR",
            satellite="SIM_Sentinel-1",
        ))

    # --- T+20m: Smoke plumes from port ---
    t20 = base_time + timedelta(minutes=20)
    for i in range(2):
        scenario.add(Observable(
            obs_type=ObservableType.SMOKE_PLUME,
            lat=jitter(25.0118, 0.002),
            lon=jitter(55.0803, 0.002),
            timestamp=t20 + timedelta(seconds=rng.randint(0, 60)),
            confidence=rng.uniform(0.7, 0.88),
            plume_vector_deg=rng.uniform(300, 320),  # NW wind
            plume_length_km=rng.uniform(3, 8),
            source="SIM_GOES",
            satellite="SIM_GOES-16",
        ))

    # --- T+30m: Fire spread along coast ---
    t30 = base_time + timedelta(minutes=30)
    spread_points = [
        (25.035, 55.095),
        (25.050, 55.100),
        (25.065, 55.115),
    ]
    for lat, lon in spread_points:
        scenario.add(Observable(
            obs_type=ObservableType.THERMAL_HOTSPOT,
            lat=jitter(lat),
            lon=jitter(lon),
            timestamp=t30 + timedelta(seconds=rng.randint(0, 120)),
            confidence=rng.uniform(0.65, 0.85),
            brightness_temp_k=rng.uniform(350, 420),
            frp_mw=rng.uniform(20, 100),
            source="SIM_FIRMS",
            satellite="SIM_VIIRS",
        ))

    # --- T+45m: SAR change at Dubai Marina ---
    t45 = base_time + timedelta(minutes=45)
    for i in range(2):
        scenario.add(Observable(
            obs_type=ObservableType.SAR_CHANGE,
            lat=jitter(25.0657, 0.002),
            lon=jitter(55.1713, 0.002),
            timestamp=t45 + timedelta(seconds=rng.randint(0, 30)),
            confidence=0.75,
            sar_coherence_loss=rng.uniform(0.5, 0.75),
            change_mask_pct=rng.uniform(8, 25),
            source="SIM_SAR",
            satellite="SIM_Sentinel-1",
        ))

    # --- T+60m: Extended plumes + inland hotspots ---
    t60 = base_time + timedelta(minutes=60)
    scenario.add(Observable(
        obs_type=ObservableType.SMOKE_PLUME,
        lat=25.025,
        lon=55.070,
        timestamp=t60,
        confidence=0.82,
        plume_vector_deg=315,
        plume_length_km=15.0,
        source="SIM_GOES",
        satellite="SIM_GOES-16",
    ))
    for lat, lon in [(25.08, 55.12), (25.09, 55.14)]:
        scenario.add(Observable(
            obs_type=ObservableType.THERMAL_HOTSPOT,
            lat=jitter(lat),
            lon=jitter(lon),
            timestamp=t60 + timedelta(seconds=rng.randint(0, 60)),
            confidence=rng.uniform(0.55, 0.75),
            brightness_temp_k=rng.uniform(340, 390),
            frp_mw=rng.uniform(10, 60),
            source="SIM_FIRMS",
            satellite="SIM_VIIRS",
        ))

    # --- T+90m: Persistent fire signature ---
    t90 = base_time + timedelta(minutes=90)
    for i in range(5):
        scenario.add(Observable(
            obs_type=ObservableType.THERMAL_HOTSPOT,
            lat=jitter(25.0118, 0.008),
            lon=jitter(55.0803, 0.008),
            timestamp=t90 + timedelta(seconds=rng.randint(0, 120)),
            confidence=rng.uniform(0.7, 0.9),
            brightness_temp_k=rng.uniform(370, 450),
            frp_mw=rng.uniform(30, 200),
            source="SIM_FIRMS",
            satellite="SIM_VIIRS",
        ))

    return scenario


def taiwan_strait_scenario(
    base_time: Optional[datetime] = None,
    seed: int = 99,
) -> SyntheticScenario:
    """
    Simulated military buildup / kinetic event in Taiwan Strait.
    (Secondary scenario for testing multi-zone awareness.)
    """
    rng = random.Random(seed)
    if base_time is None:
        base_time = datetime(2026, 3, 1, 6, 0, 0, tzinfo=timezone.utc)

    scenario = SyntheticScenario(
        name="Taiwan Strait Escalation — March 1, 2026",
        description="Simulated thermal/SAR anomalies near Fujian coast.",
    )

    # Thermal anomalies near Fuzhou Air Base
    for i in range(6):
        scenario.add(Observable(
            obs_type=ObservableType.THERMAL_HOTSPOT,
            lat=26.0614 + rng.gauss(0, 0.01),
            lon=119.3062 + rng.gauss(0, 0.01),
            timestamp=base_time + timedelta(minutes=rng.randint(0, 30)),
            confidence=rng.uniform(0.6, 0.85),
            brightness_temp_k=rng.uniform(350, 420),
            frp_mw=rng.uniform(10, 80),
            source="SIM_FIRMS",
            satellite="SIM_VIIRS",
        ))

    # SAR change at Xiamen port (potential staging)
    for i in range(2):
        scenario.add(Observable(
            obs_type=ObservableType.SAR_CHANGE,
            lat=24.4795 + rng.gauss(0, 0.005),
            lon=118.0819 + rng.gauss(0, 0.005),
            timestamp=base_time + timedelta(minutes=45),
            confidence=0.7,
            sar_coherence_loss=rng.uniform(0.4, 0.65),
            change_mask_pct=rng.uniform(5, 20),
            source="SIM_SAR",
            satellite="SIM_Sentinel-1",
        ))

    return scenario

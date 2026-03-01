"""
Base interface for all data ingestors.
Every source speaks one language: Observable records.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ObservableType(Enum):
    """Types of raw observables we ingest across all domains."""
    # --- Satellite / Imagery ---
    THERMAL_HOTSPOT = "thermal_hotspot"
    SAR_CHANGE = "sar_change"
    SMOKE_PLUME = "smoke_plume"
    FIRE_VECTOR = "fire_vector"
    STRUCTURAL_COLLAPSE = "structural_collapse"
    # --- Seismic / Geological ---
    EARTHQUAKE = "earthquake"
    VOLCANIC_ACTIVITY = "volcanic_activity"
    # --- Weather / Climate ---
    WEATHER_ALERT = "weather_alert"
    EXTREME_WEATHER = "extreme_weather"
    # --- Hydrological ---
    FLOOD_ALERT = "flood_alert"
    WATER_LEVEL = "water_level"
    # --- Environmental ---
    AIR_QUALITY = "air_quality"
    DEFORESTATION = "deforestation"
    # --- Conflict / Political ---
    ARMED_CONFLICT = "armed_conflict"
    PROTEST = "protest"
    # --- Maritime / Aviation ---
    VESSEL_TRACKING = "vessel_tracking"
    AIRCRAFT_TRACKING = "aircraft_tracking"
    # --- Economic ---
    ECONOMIC_INDICATOR = "economic_indicator"
    SANCTIONS_CHANGE = "sanctions_change"
    # --- News / OSINT ---
    NEWS_EVENT = "news_event"
    # --- Health ---
    DISEASE_OUTBREAK = "disease_outbreak"
    # --- Cyber ---
    CYBER_THREAT = "cyber_threat"
    # --- Space Weather ---
    SPACE_WEATHER = "space_weather"
    # --- Humanitarian ---
    DISPLACEMENT = "displacement"
    # --- Generic fallback ---
    GENERIC = "generic"


# Observable types that have meaningful geospatial coordinates
GEOSPATIAL_TYPES = frozenset({
    ObservableType.THERMAL_HOTSPOT,
    ObservableType.SAR_CHANGE,
    ObservableType.SMOKE_PLUME,
    ObservableType.FIRE_VECTOR,
    ObservableType.STRUCTURAL_COLLAPSE,
    ObservableType.EARTHQUAKE,
    ObservableType.VOLCANIC_ACTIVITY,
    ObservableType.FLOOD_ALERT,
    ObservableType.WATER_LEVEL,
    ObservableType.AIR_QUALITY,
    ObservableType.DEFORESTATION,
    ObservableType.ARMED_CONFLICT,
    ObservableType.PROTEST,
    ObservableType.VESSEL_TRACKING,
    ObservableType.AIRCRAFT_TRACKING,
    ObservableType.WEATHER_ALERT,
    ObservableType.EXTREME_WEATHER,
})


@dataclass
class Observable:
    """
    A single raw observation from any source.
    This is the atom of truth in the system.
    """
    obs_type: ObservableType
    lat: float
    lon: float
    timestamp: datetime
    confidence: float              # 0.0–1.0
    brightness_temp_k: Optional[float] = None   # Kelvin (hotspots)
    temp_delta_k: Optional[float] = None        # change from baseline
    frp_mw: Optional[float] = None              # fire radiative power MW
    plume_vector_deg: Optional[float] = None    # wind-relative bearing
    plume_length_km: Optional[float] = None
    sar_coherence_loss: Optional[float] = None  # 0–1, 1 = total loss
    change_mask_pct: Optional[float] = None     # % area changed
    source: str = "unknown"
    satellite: str = "unknown"
    extra: dict = field(default_factory=dict)

    @property
    def intensity(self) -> float:
        """Normalised intensity score 0–1 for propagation math."""
        if self.obs_type == ObservableType.THERMAL_HOTSPOT:
            if self.brightness_temp_k:
                return min(1.0, max(0.0, (self.brightness_temp_k - 300) / 200))
            return self.confidence
        if self.obs_type == ObservableType.SAR_CHANGE:
            return self.sar_coherence_loss or self.confidence
        if self.obs_type == ObservableType.SMOKE_PLUME:
            if self.plume_length_km:
                return min(1.0, self.plume_length_km / 50.0)
            return self.confidence
        if self.obs_type == ObservableType.EARTHQUAKE:
            mag = self.extra.get("magnitude", 0)
            return min(1.0, max(0.0, (mag - 2.0) / 7.0))
        if self.obs_type == ObservableType.ARMED_CONFLICT:
            fatalities = self.extra.get("fatalities", 0)
            return min(1.0, max(0.0, fatalities / 100.0)) if fatalities else self.confidence
        if self.obs_type == ObservableType.AIR_QUALITY:
            aqi = self.extra.get("aqi", 0)
            return min(1.0, max(0.0, aqi / 500.0)) if aqi else self.confidence
        if self.obs_type == ObservableType.FLOOD_ALERT:
            severity = self.extra.get("severity", 0)
            return min(1.0, max(0.0, severity / 5.0)) if severity else self.confidence
        if self.obs_type == ObservableType.VOLCANIC_ACTIVITY:
            vei = self.extra.get("vei", 0)
            return min(1.0, max(0.0, vei / 8.0)) if vei else self.confidence
        if self.obs_type == ObservableType.CYBER_THREAT:
            threat_level = self.extra.get("threat_level", 0)
            return min(1.0, max(0.0, threat_level / 10.0)) if threat_level else self.confidence
        if self.obs_type == ObservableType.DISEASE_OUTBREAK:
            cases = self.extra.get("cases", 0)
            return min(1.0, max(0.0, cases / 10000.0)) if cases else self.confidence
        if self.obs_type == ObservableType.SPACE_WEATHER:
            kp_index = self.extra.get("kp_index", 0)
            return min(1.0, max(0.0, kp_index / 9.0)) if kp_index else self.confidence
        # Default: use extra.intensity or fall back to confidence
        return self.extra.get("intensity", self.confidence)


class BaseIngestor(abc.ABC):
    """All ingestors implement this interface."""

    @abc.abstractmethod
    def poll(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime] = None,
    ) -> List[Observable]:
        """
        Poll the data source for observables within a bounding box.
        bbox: (min_lat, min_lon, max_lat, max_lon)
        since: only return obs after this time (None = last 24h default)
        """
        ...

    @abc.abstractmethod
    def source_name(self) -> str: ...

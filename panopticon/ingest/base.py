"""
Base interface for all satellite data ingestors.
Every source speaks one language: Observable records.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class ObservableType(Enum):
    """Types of raw orbital observables we ingest."""
    THERMAL_HOTSPOT = "thermal_hotspot"       # FIRMS VIIRS/MODIS
    SAR_CHANGE = "sar_change"                 # Sentinel-1 SAR
    SMOKE_PLUME = "smoke_plume"               # GOES IR/visible
    FIRE_VECTOR = "fire_vector"               # Derived fire spread
    STRUCTURAL_COLLAPSE = "structural_collapse"  # SAR coherence loss


@dataclass
class Observable:
    """
    A single raw observation from orbit.
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
            # VIIRS brightness temps range ~300–500K for fires
            if self.brightness_temp_k:
                return min(1.0, max(0.0, (self.brightness_temp_k - 300) / 200))
            return self.confidence
        if self.obs_type == ObservableType.SAR_CHANGE:
            return self.sar_coherence_loss or self.confidence
        if self.obs_type == ObservableType.SMOKE_PLUME:
            if self.plume_length_km:
                return min(1.0, self.plume_length_km / 50.0)
            return self.confidence
        return self.confidence


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

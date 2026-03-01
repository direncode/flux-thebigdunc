"""
NOAA GOES Geostationary Smoke/Plume Detection ingestor (stub + simulator).

GOES-16/17/18 provide near-real-time fire/smoke detection at ~2km
resolution with rapid scan (1–5 min refresh). This module would ingest
the ABI Fire Detection & Characterization (FDC) product and smoke
plume vectors.

NOTE: Full GOES ingest requires GCS/S3 bucket access to netCDF4 files.
This provides the interface + metadata layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from panopticon.ingest.base import BaseIngestor, Observable, ObservableType

logger = logging.getLogger(__name__)


class GOESPlumeIngestor(BaseIngestor):
    """
    Poll NOAA GOES Fire/Smoke products.

    In production:
    1. Query GCS bucket for latest ABI-L2-FDCC (Fire Detection) netCDF
    2. Parse fire pixels + smoke mask
    3. Compute plume vectors from sequential frames
    4. Emit observables

    Stub for now.
    """

    def __init__(self, bucket: str = "gcp-public-data-goes-16"):
        self.bucket = bucket

    def source_name(self) -> str:
        return "GOES_ABI_FDC"

    def poll(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime] = None,
    ) -> List[Observable]:
        logger.info(
            "GOES plume poll (stub) bbox=%s since=%s — "
            "real implementation requires GCS netCDF pipeline",
            bbox, since,
        )
        return []


def make_plume_observable(
    lat: float,
    lon: float,
    timestamp: datetime,
    plume_vector_deg: float,
    plume_length_km: float,
    confidence: float = 0.7,
) -> Observable:
    """Helper to construct a smoke plume observable (used by simulator)."""
    return Observable(
        obs_type=ObservableType.SMOKE_PLUME,
        lat=lat,
        lon=lon,
        timestamp=timestamp,
        confidence=confidence,
        plume_vector_deg=plume_vector_deg,
        plume_length_km=plume_length_km,
        source="GOES_ABI_FDC",
        satellite="GOES-16",
    )

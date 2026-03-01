"""
ESA Sentinel-1 SAR Change Detection ingestor (stub + simulator).

Polls STAC catalogs for Sentinel-1 GRD imagery, computes coherence
change masks to detect structural collapse, cratering, or new
construction.

NOTE: Full SAR processing (SNAP/isce2) is heavy. This module provides
the polling + metadata ingest layer; actual pixel-level coherence
analysis would be a downstream pipeline stage.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from panopticon.ingest.base import BaseIngestor, Observable, ObservableType

logger = logging.getLogger(__name__)


class SentinelSARIngestor(BaseIngestor):
    """
    Poll ESA Sentinel-1 STAC catalog for SAR change products.

    In production this would:
    1. Query earth-search STAC for recent S1 GRD over bbox
    2. Download pre/post image pairs
    3. Run InSAR coherence → change mask
    4. Emit observables where coherence_loss > threshold

    For now: stub that logs the intent. Use SyntheticIngestor for testing.
    """

    def __init__(self, stac_url: str = "https://earth-search.aws.element84.com/v1"):
        self.stac_url = stac_url

    def source_name(self) -> str:
        return "Sentinel-1_SAR"

    def poll(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime] = None,
    ) -> List[Observable]:
        """
        Stub: would query STAC, process SAR, return change observables.
        """
        logger.info(
            "Sentinel-1 SAR poll (stub) bbox=%s since=%s — "
            "real implementation requires SAR processing pipeline",
            bbox, since,
        )
        # In production, we would return actual coherence-loss observables.
        # For now, the simulator fills this role.
        return []


def make_sar_observable(
    lat: float,
    lon: float,
    timestamp: datetime,
    coherence_loss: float,
    change_mask_pct: float,
    confidence: float = 0.8,
) -> Observable:
    """Helper to construct a SAR change observable (used by simulator)."""
    return Observable(
        obs_type=ObservableType.SAR_CHANGE,
        lat=lat,
        lon=lon,
        timestamp=timestamp,
        confidence=confidence,
        sar_coherence_loss=coherence_loss,
        change_mask_pct=change_mask_pct,
        source="Sentinel-1_SAR",
        satellite="Sentinel-1A",
    )

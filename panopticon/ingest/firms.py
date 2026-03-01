"""
NASA FIRMS (Fire Information for Resource Management System) ingestor.
Polls VIIRS and MODIS active fire / hotspot data via the FIRMS CSV API.

This is the primary thermal truth layer.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from panopticon.config import FIRMS_CSV_URL, FIRMS_MAP_KEY
from panopticon.ingest.base import BaseIngestor, Observable, ObservableType

logger = logging.getLogger(__name__)


class FIRMSIngestor(BaseIngestor):
    """
    Poll NASA FIRMS for VIIRS/MODIS hotspot detections.
    API docs: https://firms.modaps.eosdis.nasa.gov/api/area/

    Returns Observable records with thermal hotspot data.
    """

    def __init__(self, api_key: str = FIRMS_MAP_KEY, sensor: str = "VIIRS_SNPP_NRT"):
        self.api_key = api_key
        self.sensor = sensor  # VIIRS_SNPP_NRT, VIIRS_NOAA20_NRT, MODIS_NRT
        self.session = requests.Session()
        self.session.headers.update({"Accept": "text/csv"})

    def source_name(self) -> str:
        return f"FIRMS_{self.sensor}"

    def poll(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime] = None,
    ) -> List[Observable]:
        """
        Query FIRMS area CSV endpoint.
        bbox: (min_lat, min_lon, max_lat, max_lon)
        """
        min_lat, min_lon, max_lat, max_lon = bbox
        # FIRMS wants the area as "min_lon,min_lat,max_lon,max_lat"
        area = f"{min_lon},{min_lat},{max_lon},{max_lat}"
        # Day range: how many days back (1–10)
        days = 1
        if since:
            delta = datetime.now(timezone.utc) - since
            days = max(1, min(10, int(delta.total_seconds() / 86400) + 1))

        url = f"{FIRMS_CSV_URL}/{self.api_key}/{self.sensor}/{area}/{days}"
        logger.info("FIRMS poll: %s", url)

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("FIRMS request failed: %s", exc)
            return []

        return self._parse_csv(resp.text)

    def _parse_csv(self, text: str) -> List[Observable]:
        """Parse FIRMS CSV into Observable records."""
        observables: List[Observable] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                lat = float(row.get("latitude", 0))
                lon = float(row.get("longitude", 0))
                bright = float(row.get("bright_ti4", 0) or row.get("brightness", 0))
                conf_raw = row.get("confidence", "nominal")
                frp = float(row.get("frp", 0) or 0)

                # Parse confidence: VIIRS gives "nominal"/"high"/"low",
                # MODIS gives 0–100 int
                if conf_raw in ("high", "h"):
                    confidence = 0.9
                elif conf_raw in ("nominal", "n"):
                    confidence = 0.6
                elif conf_raw in ("low", "l"):
                    confidence = 0.3
                else:
                    confidence = min(1.0, float(conf_raw) / 100.0)

                # Parse timestamp
                acq_date = row.get("acq_date", "2026-01-01")
                acq_time = row.get("acq_time", "0000")
                ts = datetime.strptime(
                    f"{acq_date} {acq_time}", "%Y-%m-%d %H%M"
                ).replace(tzinfo=timezone.utc)

                obs = Observable(
                    obs_type=ObservableType.THERMAL_HOTSPOT,
                    lat=lat,
                    lon=lon,
                    timestamp=ts,
                    confidence=confidence,
                    brightness_temp_k=bright if bright > 0 else None,
                    frp_mw=frp if frp > 0 else None,
                    source=self.source_name(),
                    satellite=row.get("satellite", self.sensor),
                    extra={
                        "scan": row.get("scan"),
                        "track": row.get("track"),
                        "daynight": row.get("daynight"),
                    },
                )
                observables.append(obs)
            except (ValueError, KeyError) as exc:
                logger.debug("Skipping malformed FIRMS row: %s", exc)
                continue

        logger.info("FIRMS parsed %d observables", len(observables))
        return observables

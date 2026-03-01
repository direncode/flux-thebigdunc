"""
Generic catalog-driven ingestor.
Polls any REST API described by a SourceConfig — no source-specific Python needed.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from panopticon.ingest.adapters import ADAPTER_REGISTRY, _resolve_path
from panopticon.ingest.base import BaseIngestor, Observable, ObservableType
from panopticon.ingest.registry import SourceConfig

logger = logging.getLogger(__name__)

# Map string observable type names to enum values
_OBS_TYPE_MAP: Dict[str, ObservableType] = {t.value: t for t in ObservableType}
for t in ObservableType:
    _OBS_TYPE_MAP[t.name.lower()] = t
    _OBS_TYPE_MAP[t.name] = t


def _parse_timestamp(raw: Any, fmt: str) -> Optional[datetime]:
    """Parse a timestamp from various formats."""
    if raw is None:
        return None

    if fmt == "epoch_ms":
        try:
            return datetime.fromtimestamp(float(raw) / 1000, tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None

    if fmt == "epoch_s":
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            return None

    if fmt == "iso8601":
        raw_str = str(raw).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw_str)
        except ValueError:
            pass
        # Try common ISO formats
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(raw), pattern).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    if fmt.startswith("strftime:"):
        pattern = fmt[len("strftime:"):]
        try:
            return datetime.strptime(str(raw), pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    return None


def _apply_confidence_transform(raw: Any, transform: str) -> float:
    """Apply confidence value transformations."""
    if transform == "none" or not transform:
        try:
            return min(1.0, max(0.0, float(raw)))
        except (ValueError, TypeError):
            return 0.5

    if transform.startswith("divide:"):
        divisor = float(transform.split(":")[1])
        try:
            return min(1.0, max(0.0, float(raw) / divisor))
        except (ValueError, TypeError):
            return 0.5

    if transform.startswith("abs_divide:"):
        divisor = float(transform.split(":")[1])
        try:
            return min(1.0, max(0.0, abs(float(raw)) / divisor))
        except (ValueError, TypeError):
            return 0.5

    if transform.startswith("map:"):
        mapping = {}
        for pair in transform[4:].split(","):
            k, v = pair.split("=")
            mapping[k.strip().lower()] = float(v.strip())
        raw_str = str(raw).strip().lower()
        return mapping.get(raw_str, 0.5)

    return 0.5


def _resolve_field(record: Dict, path: str, context: Dict) -> Any:
    """Resolve a field path, supporting _static:, _request:, and dot-paths."""
    if not path:
        return None

    if path.startswith("_static:"):
        return path[len("_static:"):]

    if path.startswith("_request."):
        key = path[len("_request."):]
        return context.get(key)

    return _resolve_path(record, path)


class GenericIngestor(BaseIngestor):
    """
    Polls any REST API described by a SourceConfig.
    Uses format adapters for parsing and field mappings for extraction.
    """

    def __init__(self, config: SourceConfig, session: Optional[requests.Session] = None):
        self.config = config
        self._session = session or requests.Session()
        self._setup_auth()

    def _setup_auth(self) -> None:
        """Configure session authentication."""
        if self.config.auth_type == "header":
            header_name = self.config.auth_config.get("header_name", "Authorization")
            key = self.config.get_api_key()
            if key:
                prefix = self.config.auth_config.get("header_prefix", "")
                self._session.headers[header_name] = f"{prefix}{key}" if prefix else key

        if self.config.headers:
            self._session.headers.update(self.config.headers)

        # User-Agent for APIs that require it (e.g., NOAA NWS)
        if "User-Agent" not in self._session.headers:
            self._session.headers["User-Agent"] = "Panopticon-DarkKnight/1.0"

    def _build_params(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime],
    ) -> Dict[str, str]:
        """Resolve template variables in request params."""
        now = datetime.now(timezone.utc)
        since_dt = since or (now - timedelta(days=1))

        center_lat = (bbox[0] + bbox[2]) / 2
        center_lon = (bbox[1] + bbox[3]) / 2

        template_vars = {
            "bbox_south": str(bbox[0]),
            "bbox_west": str(bbox[1]),
            "bbox_north": str(bbox[2]),
            "bbox_east": str(bbox[3]),
            "bbox_min_lat": str(bbox[0]),
            "bbox_min_lon": str(bbox[1]),
            "bbox_max_lat": str(bbox[2]),
            "bbox_max_lon": str(bbox[3]),
            "center_lat": str(center_lat),
            "center_lon": str(center_lon),
            "since_iso": since_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "since_date": since_dt.strftime("%Y-%m-%d"),
            "now_iso": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "now_date": now.strftime("%Y-%m-%d"),
        }

        params = {}
        for key, val in self.config.params.items():
            resolved = str(val)
            for tpl_key, tpl_val in template_vars.items():
                resolved = resolved.replace(f"{{{tpl_key}}}", tpl_val)
            params[key] = resolved

        # Add API key as param if configured that way
        if self.config.auth_type == "api_key":
            key_param = self.config.auth_config.get("key_param", "api_key")
            api_key = self.config.get_api_key()
            if api_key:
                params[key_param] = api_key
            # Optional email param (e.g., ACLED)
            email_param = self.config.auth_config.get("email_param")
            email_env = self.config.auth_config.get("email_env_var")
            if email_param and email_env:
                import os
                email = os.environ.get(email_env, "")
                if email:
                    params[email_param] = email

        return params

    def poll(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime] = None,
    ) -> List[Observable]:
        """Poll the API and return parsed Observables."""
        params = self._build_params(bbox, since)

        try:
            resp = self._session.request(
                method=self.config.method,
                url=self.config.base_url,
                params=params if self.config.method == "GET" else None,
                json=self.config.body if self.config.method == "POST" else None,
                timeout=self.config.timeout_seconds,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Source %s poll failed: %s", self.config.id, exc)
            return []

        # Parse response
        adapter_cls = ADAPTER_REGISTRY.get(self.config.response_format)
        if not adapter_cls:
            logger.warning("No adapter for format: %s", self.config.response_format)
            return []

        adapter = adapter_cls()
        try:
            records = adapter.parse(resp.text, self.config.results_path)
        except Exception as exc:
            logger.warning("Source %s parse failed: %s", self.config.id, exc)
            return []

        # Map records to Observables
        obs_type = _OBS_TYPE_MAP.get(self.config.observable_type, ObservableType.GENERIC)
        mapping = self.config.field_mapping
        ts_fmt = self.config.timestamp_format
        conf_transform = mapping.get("confidence_transform", "none")

        request_context = {
            "latitude": str((bbox[0] + bbox[2]) / 2),
            "longitude": str((bbox[1] + bbox[3]) / 2),
        }

        observables: List[Observable] = []
        for record in records:
            try:
                lat_raw = _resolve_field(record, mapping.get("lat", ""), request_context)
                lon_raw = _resolve_field(record, mapping.get("lon", ""), request_context)
                ts_raw = _resolve_field(record, mapping.get("timestamp", ""), request_context)

                if lat_raw is None or lon_raw is None:
                    continue

                lat = float(lat_raw)
                lon = float(lon_raw)
                timestamp = _parse_timestamp(ts_raw, ts_fmt)
                if not timestamp:
                    timestamp = datetime.now(timezone.utc)

                # Confidence
                conf_path = mapping.get("confidence")
                if conf_path and not conf_path.startswith("_static:"):
                    conf_raw = _resolve_field(record, conf_path, request_context)
                    confidence = _apply_confidence_transform(conf_raw, conf_transform)
                elif conf_path and conf_path.startswith("_static:"):
                    confidence = float(conf_path[len("_static:"):])
                else:
                    confidence = 0.5

                # Extra fields
                extra: Dict[str, Any] = {}
                for key, path in self.config.extra_fields.items():
                    val = _resolve_field(record, path, request_context)
                    if val is not None:
                        extra[key] = val

                # Primary value field
                value_path = mapping.get("value")
                value_key = mapping.get("value_key", "value")
                if value_path:
                    val = _resolve_field(record, value_path, request_context)
                    if val is not None:
                        extra[value_key] = val

                obs = Observable(
                    obs_type=obs_type,
                    lat=lat,
                    lon=lon,
                    timestamp=timestamp,
                    confidence=confidence,
                    source=self.config.id,
                    satellite="API",
                    extra=extra,
                )
                observables.append(obs)

            except (ValueError, KeyError, TypeError) as exc:
                logger.debug("Skip record from %s: %s", self.config.id, exc)

        return observables

    def source_name(self) -> str:
        return self.config.id

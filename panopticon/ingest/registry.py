"""
Source Registry — loads sources.yaml catalog and creates ingestors.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "sources" / "catalog.yaml"


@dataclass
class SourceConfig:
    """Parsed configuration for a single data source."""

    id: str
    name: str
    category: str
    enabled: bool = True
    priority: int = 2

    # Connection
    base_url: str = ""
    auth_type: str = "none"
    auth_config: Dict[str, str] = field(default_factory=dict)

    # Polling
    poll_interval_seconds: int = 300
    rate_limit_per_minute: int = 30
    timeout_seconds: int = 30

    # Request
    method: str = "GET"
    params: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[Dict[str, Any]] = None

    # Response parsing
    response_format: str = "json"
    results_path: str = ""

    # Field mapping
    field_mapping: Dict[str, str] = field(default_factory=dict)
    observable_type: str = "generic"
    extra_fields: Dict[str, str] = field(default_factory=dict)
    confidence_expr: Optional[str] = None
    dedup_key: str = "{lat:.2f},{lon:.2f},{hour_bucket}"
    timestamp_format: str = "iso8601"

    # Legacy ingestor override
    ingestor_class: Optional[str] = None

    @property
    def requires_api_key(self) -> bool:
        return self.auth_type in ("api_key", "header")

    def get_api_key(self) -> Optional[str]:
        """Resolve API key from environment variable or fallback."""
        env_var = self.auth_config.get("key_env_var", "")
        if env_var:
            val = os.environ.get(env_var)
            if val:
                return val
        return self.auth_config.get("fallback_key")


class SourceRegistry:
    """Loads the source catalog and provides query methods."""

    def __init__(self, catalog_path: Optional[str] = None):
        self.catalog_path = Path(catalog_path) if catalog_path else _DEFAULT_CATALOG
        self.sources: Dict[str, SourceConfig] = {}
        self._load()

    def _load(self) -> None:
        if not self.catalog_path.exists():
            logger.warning("Source catalog not found: %s", self.catalog_path)
            return

        with open(self.catalog_path) as f:
            data = yaml.safe_load(f)

        raw_sources = data.get("sources", [])
        for entry in raw_sources:
            try:
                config = self._parse_entry(entry)
                self.sources[config.id] = config
            except Exception as exc:
                logger.warning("Failed to parse source entry: %s — %s", entry.get("id", "?"), exc)

        logger.info("Loaded %d sources from catalog", len(self.sources))

    def _parse_entry(self, entry: Dict[str, Any]) -> SourceConfig:
        """Parse a raw YAML dict into a SourceConfig."""
        request = entry.get("request", {})
        return SourceConfig(
            id=entry["id"],
            name=entry.get("name", entry["id"]),
            category=entry.get("category", "unknown"),
            enabled=entry.get("enabled", True),
            priority=entry.get("priority", 2),
            base_url=entry.get("base_url", ""),
            auth_type=entry.get("auth_type", "none"),
            auth_config=entry.get("auth_config", {}),
            poll_interval_seconds=entry.get("poll_interval_seconds", 300),
            rate_limit_per_minute=entry.get("rate_limit_per_minute", 30),
            timeout_seconds=entry.get("timeout_seconds", 30),
            method=request.get("method", entry.get("method", "GET")),
            params=request.get("params", entry.get("params", {})),
            headers=request.get("headers", entry.get("headers", {})),
            body=request.get("body"),
            response_format=entry.get("response_format", "json"),
            results_path=entry.get("results_path", ""),
            field_mapping=entry.get("field_mapping", {}),
            observable_type=entry.get("observable_type", "generic"),
            extra_fields=entry.get("extra_fields", {}),
            confidence_expr=entry.get("confidence_expr"),
            dedup_key=entry.get("dedup_key", "{lat:.2f},{lon:.2f},{hour_bucket}"),
            timestamp_format=entry.get("field_mapping", {}).get("timestamp_format", "iso8601"),
            ingestor_class=entry.get("ingestor_class"),
        )

    def get_enabled(self) -> List[SourceConfig]:
        return [s for s in self.sources.values() if s.enabled]

    def get_by_category(self, category: str) -> List[SourceConfig]:
        return [s for s in self.sources.values() if s.category == category and s.enabled]

    def get_by_id(self, source_id: str) -> Optional[SourceConfig]:
        return self.sources.get(source_id)

    def get_categories(self) -> List[str]:
        return sorted({s.category for s in self.sources.values() if s.enabled})

    def __len__(self) -> int:
        return len(self.sources)

"""
Poll Scheduler — manages multi-source polling with rate limiting and health tracking.
Designed for single-process Streamlit: tick() called once per rerun cycle.
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from panopticon.ingest.base import BaseIngestor, Observable
from panopticon.ingest.generic import GenericIngestor
from panopticon.ingest.registry import SourceConfig, SourceRegistry

logger = logging.getLogger(__name__)


@dataclass
class SourceHealth:
    """Runtime health tracking for a single source."""

    source_id: str
    source_name: str = ""
    category: str = ""
    last_poll_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_failures: int = 0
    total_polls: int = 0
    total_records: int = 0
    total_errors: int = 0
    last_error: Optional[str] = None
    avg_latency_ms: float = 0.0
    enabled: bool = True
    backoff_until: Optional[float] = None

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < 5 and self.enabled

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.consecutive_failures >= 5:
            return "failed"
        if self.consecutive_failures > 0:
            return "degraded"
        if self.total_polls == 0:
            return "pending"
        return "healthy"


def _import_class(dotted_path: str) -> type:
    """Dynamically import a class from a dotted path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class PollScheduler:
    """
    Round-robin scheduler across all enabled sources.
    tick() polls one source per call. tick_burst() polls up to N.
    """

    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self._sources: Dict[str, Union[GenericIngestor, BaseIngestor]] = {}
        self._health: Dict[str, SourceHealth] = {}
        self._session = None
        self._initialize()

    def _initialize(self) -> None:
        """Create ingestor instances for all enabled sources."""
        try:
            import requests
            self._session = requests.Session()
            self._session.headers["User-Agent"] = "Panopticon-DarkKnight/1.0"
        except ImportError:
            self._session = None

        for config in self.registry.get_enabled():
            try:
                if config.ingestor_class:
                    cls = _import_class(config.ingestor_class)
                    # Try to pass API key to legacy ingestors
                    api_key = config.get_api_key()
                    if api_key:
                        try:
                            self._sources[config.id] = cls(api_key=api_key)
                        except TypeError:
                            self._sources[config.id] = cls()
                    else:
                        self._sources[config.id] = cls()
                else:
                    self._sources[config.id] = GenericIngestor(config, self._session)

                self._health[config.id] = SourceHealth(
                    source_id=config.id,
                    source_name=config.name,
                    category=config.category,
                )
            except Exception as exc:
                logger.warning("Failed to initialize source %s: %s", config.id, exc)

        logger.info("Scheduler initialized with %d sources", len(self._sources))

    def tick(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime] = None,
    ) -> Tuple[str, List[Observable]]:
        """Poll the next due source. Returns (source_id, observables)."""
        source_id = self._select_next()
        if not source_id:
            return ("none", [])

        return self._poll_source(source_id, bbox, since)

    def tick_burst(
        self,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime] = None,
        max_sources: int = 5,
    ) -> List[Tuple[str, List[Observable]]]:
        """Poll up to max_sources in one burst."""
        results = []
        polled = set()

        for _ in range(max_sources):
            source_id = self._select_next(exclude=polled)
            if not source_id:
                break
            polled.add(source_id)
            results.append(self._poll_source(source_id, bbox, since))

        return results

    def _poll_source(
        self,
        source_id: str,
        bbox: tuple[float, float, float, float],
        since: Optional[datetime],
    ) -> Tuple[str, List[Observable]]:
        """Poll a single source and update health."""
        source = self._sources.get(source_id)
        health = self._health.get(source_id)
        if not source or not health:
            return (source_id, [])

        start = time.monotonic()
        try:
            obs = source.poll(bbox, since)

            elapsed = (time.monotonic() - start) * 1000
            health.last_poll_time = time.monotonic()
            health.last_success_time = time.monotonic()
            health.total_polls += 1
            health.total_records += len(obs)
            health.consecutive_failures = 0
            health.avg_latency_ms = (health.avg_latency_ms * 0.8) + (elapsed * 0.2)
            health.last_error = None
            health.backoff_until = None

            return (source_id, obs)

        except Exception as exc:
            health.total_polls += 1
            health.total_errors += 1
            health.consecutive_failures += 1
            health.last_error = str(exc)[:200]
            health.last_poll_time = time.monotonic()
            backoff = min(480, 30 * (2 ** (health.consecutive_failures - 1)))
            health.backoff_until = time.monotonic() + backoff
            logger.warning("Source %s poll error: %s", source_id, exc)
            return (source_id, [])

    def _select_next(self, exclude: Optional[set] = None) -> Optional[str]:
        """Select the next source to poll based on priority and timing."""
        now = time.monotonic()
        exclude = exclude or set()
        candidates: List[Tuple[str, float]] = []

        for source_id, health in self._health.items():
            if source_id in exclude:
                continue
            if not health.enabled or not health.is_healthy:
                continue
            if health.backoff_until and now < health.backoff_until:
                continue

            config = self.registry.get_by_id(source_id)
            if not config:
                continue

            if health.last_poll_time:
                elapsed = now - health.last_poll_time
                if elapsed < config.poll_interval_seconds:
                    continue
                overdue = elapsed / config.poll_interval_seconds
            else:
                overdue = 10.0  # never polled

            score = overdue / config.priority
            candidates.append((source_id, score))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def get_all_health(self) -> Dict[str, SourceHealth]:
        return dict(self._health)

    def get_health_summary(self) -> Dict[str, Any]:
        """Summary stats for dashboard display."""
        total = len(self._health)
        healthy = sum(1 for h in self._health.values() if h.status == "healthy")
        pending = sum(1 for h in self._health.values() if h.status == "pending")
        degraded = sum(1 for h in self._health.values() if h.status == "degraded")
        failed = sum(1 for h in self._health.values() if h.status == "failed")
        total_records = sum(h.total_records for h in self._health.values())

        return {
            "total_sources": total,
            "healthy": healthy,
            "pending": pending,
            "degraded": degraded,
            "failed": failed,
            "total_records": total_records,
        }

    def get_source_count(self) -> int:
        return len(self._sources)

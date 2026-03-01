"""
Response format adapters for the generic ingestor.
Parses raw API responses (JSON, CSV, GeoJSON, XML) into lists of record dicts.
"""

from __future__ import annotations

import abc
import csv
import io
import json
import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _resolve_path(data: Any, path: str) -> Any:
    """
    Navigate a dot-path into a nested dict/list structure.
    Supports: 'a.b.c', 'a[0]', 'features[1].properties.name'
    """
    if not path or data is None:
        return data

    parts = []
    current = ""
    for ch in path:
        if ch == ".":
            if current:
                parts.append(current)
                current = ""
        elif ch == "[":
            if current:
                parts.append(current)
                current = ""
        elif ch == "]":
            if current:
                parts.append(int(current))
                current = ""
        else:
            current += ch
    if current:
        parts.append(current)

    result = data
    for part in parts:
        if result is None:
            return None
        if isinstance(part, int):
            if isinstance(result, (list, tuple)) and part < len(result):
                result = result[part]
            else:
                return None
        elif isinstance(result, dict):
            result = result.get(part)
        else:
            return None
    return result


class BaseAdapter(abc.ABC):
    """Parses raw API response text into a list of record dicts."""

    @abc.abstractmethod
    def parse(self, raw_content: str, records_path: str) -> List[Dict[str, Any]]:
        ...


class JSONAdapter(BaseAdapter):
    """Handles JSON and JSON-API responses."""

    def parse(self, raw_content: str, records_path: str) -> List[Dict[str, Any]]:
        data = json.loads(raw_content)

        if records_path == "_singleton":
            return [data] if isinstance(data, dict) else []

        records = _resolve_path(data, records_path)
        if isinstance(records, list):
            return records
        if isinstance(records, dict):
            return [records]
        return []


class GeoJSONAdapter(BaseAdapter):
    """Handles GeoJSON FeatureCollections. Flattens geometry into records."""

    def parse(self, raw_content: str, records_path: str) -> List[Dict[str, Any]]:
        data = json.loads(raw_content)
        features = data.get("features", [])

        records = []
        for feat in features:
            record = {}
            record["geometry"] = feat.get("geometry", {})
            record["properties"] = feat.get("properties", {})
            record["id"] = feat.get("id")
            records.append(record)
        return records


class CSVAdapter(BaseAdapter):
    """Handles CSV responses (like FIRMS)."""

    def parse(self, raw_content: str, records_path: str) -> List[Dict[str, Any]]:
        reader = csv.DictReader(io.StringIO(raw_content))
        return [dict(row) for row in reader]


class XMLAdapter(BaseAdapter):
    """Handles XML responses. Uses records_path as XPath-like tag selector."""

    def parse(self, raw_content: str, records_path: str) -> List[Dict[str, Any]]:
        try:
            root = ET.fromstring(raw_content)
        except ET.ParseError:
            logger.warning("XMLAdapter: failed to parse XML response")
            return []

        # Simple tag-based record extraction
        records = []
        elements = root.iter(records_path) if records_path != "_singleton" else [root]

        for elem in elements:
            record: Dict[str, Any] = {}
            for child in elem:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                record[tag] = child.text
            if record:
                records.append(record)

        return records


ADAPTER_REGISTRY: Dict[str, type] = {
    "json": JSONAdapter,
    "geojson": GeoJSONAdapter,
    "csv": CSVAdapter,
    "xml": XMLAdapter,
}

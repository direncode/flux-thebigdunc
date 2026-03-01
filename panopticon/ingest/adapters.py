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
    """Handles XML responses including RSS/Atom feeds.

    For RSS feeds, set records_path='item' — the adapter auto-detects
    RSS structure (channel > item) and strips namespace prefixes.
    """

    def parse(self, raw_content: str, records_path: str) -> List[Dict[str, Any]]:
        try:
            root = ET.fromstring(raw_content)
        except ET.ParseError:
            logger.warning("XMLAdapter: failed to parse XML response")
            return []

        # Detect RSS / Atom structure
        if self._is_rss(root):
            return self._parse_rss(root, records_path)
        if self._is_atom(root):
            return self._parse_atom(root)

        # Fallback: simple tag-based record extraction
        records = []
        elements = root.iter(records_path) if records_path != "_singleton" else [root]

        for elem in elements:
            record: Dict[str, Any] = {}
            for child in elem:
                tag = self._strip_ns(child.tag)
                record[tag] = child.text
            if record:
                records.append(record)

        return records

    @staticmethod
    def _strip_ns(tag: str) -> str:
        """Remove namespace prefix: {http://...}localname -> localname."""
        if "}" in tag:
            return tag.split("}")[-1]
        return tag

    @staticmethod
    def _is_rss(root: ET.Element) -> bool:
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        return tag.lower() == "rss"

    @staticmethod
    def _is_atom(root: ET.Element) -> bool:
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        return tag.lower() == "feed"

    def _parse_rss(self, root: ET.Element, records_path: str) -> List[Dict[str, Any]]:
        """Parse RSS 2.0 <channel><item>...</item></channel> structure."""
        records = []
        # Find all <item> elements anywhere in the tree
        for item in root.iter():
            tag = self._strip_ns(item.tag)
            if tag != (records_path or "item"):
                continue
            record = self._elem_to_dict(item)
            if record:
                records.append(record)
        return records

    def _parse_atom(self, root: ET.Element) -> List[Dict[str, Any]]:
        """Parse Atom <feed><entry>...</entry></feed> structure."""
        records = []
        for entry in root.iter():
            tag = self._strip_ns(entry.tag)
            if tag != "entry":
                continue
            record = self._elem_to_dict(entry)
            # Atom <link> uses href attribute
            for link in entry.iter():
                if self._strip_ns(link.tag) == "link":
                    href = link.get("href")
                    if href:
                        record.setdefault("link", href)
            if record:
                records.append(record)
        return records

    def _elem_to_dict(self, elem: ET.Element) -> Dict[str, Any]:
        """Convert an XML element's children into a flat dict."""
        record: Dict[str, Any] = {}
        for child in elem:
            tag = self._strip_ns(child.tag)
            # For nested elements, try text first, then recursion
            if child.text and child.text.strip():
                record[tag] = child.text.strip()
            elif len(child) > 0:
                # Nested element — flatten with dot notation
                for grandchild in child:
                    gtag = self._strip_ns(grandchild.tag)
                    if grandchild.text and grandchild.text.strip():
                        record[f"{tag}.{gtag}"] = grandchild.text.strip()
            # Also check for useful attributes (e.g., <source url="...">)
            if child.attrib:
                for attr_key, attr_val in child.attrib.items():
                    attr_key_clean = self._strip_ns(attr_key)
                    record[f"{tag}@{attr_key_clean}"] = attr_val
        # Also grab element's own attributes
        for attr_key, attr_val in elem.attrib.items():
            record[f"@{self._strip_ns(attr_key)}"] = attr_val
        return record


ADAPTER_REGISTRY: Dict[str, type] = {
    "json": JSONAdapter,
    "geojson": GeoJSONAdapter,
    "csv": CSVAdapter,
    "xml": XMLAdapter,
}

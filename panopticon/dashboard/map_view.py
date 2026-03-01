"""
Panopticon Intelligence Map — Folium/Leaflet Satellite Surface
==============================================================
Builds a fully interactive Leaflet.js map with real satellite imagery,
intelligence overlays, and navigable markers.

Pure function module — no Streamlit calls. Data in, folium.Map out.
Never store the returned Map in session state (not picklable).

"The sonar gives you a picture of the whole city."
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import folium
import folium.plugins
from folium import FeatureGroup, IFrame

from panopticon.config import (
    CRITICAL_NODES,
    CARTO_DARK_ATTRIBUTION,
    CARTO_DARK_TILE_URL,
    DEFAULT_WATCH_ZONES,
    ESRI_SATELLITE_ATTRIBUTION,
    ESRI_SATELLITE_TILE_URL,
    BoundingBox,
    CriticalNode,
)
from panopticon.core.events import EventSeed, EventType
from panopticon.core.graph import TemporalGraph
from panopticon.ingest.base import Observable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENT_TYPE_COLORS: Dict[str, str] = {
    "strike_barrage": "#ff4444",
    "structural_collapse": "#ff8800",
    "industrial_fire": "#ffaa00",
    "wildfire_spread": "#ff6600",
    "smoke_corridor": "#888888",
    "military_activity": "#ff0066",
    "anomalous_thermal": "#cc44ff",
    "unknown_cluster": "#666666",
}

CRITICAL_NODE_ICONS: Dict[str, Tuple[str, str]] = {
    "port": ("anchor", "darkblue"),
    "airport": ("plane", "cadetblue"),
    "oil": ("tint", "orange"),
    "chokepoint": ("warning-sign", "red"),
    "military": ("screenshot", "darkred"),
    "urban": ("home", "gray"),
}

# CSS for pulsing high-intensity markers
PULSE_CSS = """
<style>
@keyframes panopticon-pulse {
    0%   { box-shadow: 0 0 0 0 rgba(255, 68, 68, 0.7); }
    70%  { box-shadow: 0 0 0 18px rgba(255, 68, 68, 0); }
    100% { box-shadow: 0 0 0 0 rgba(255, 68, 68, 0); }
}
.pulse-marker {
    animation: panopticon-pulse 1.5s infinite;
    border-radius: 50%;
}
</style>
"""

# Popup HTML template (Dark Knight palette)
POPUP_STYLE = (
    "background:#111;color:#e0e0e0;font-family:'Courier New',monospace;"
    "padding:10px;min-width:220px;border:1px solid #1a3a5c;border-radius:4px;"
    "font-size:12px;line-height:1.5"
)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_panopticon_map(
    seeds: Optional[List[EventSeed]] = None,
    graph: Optional[TemporalGraph] = None,
    observables: Optional[List[Observable]] = None,
    center_lat: float = 25.0,
    center_lon: float = 45.0,
    zoom: int = 4,
    show_watch_zones: bool = True,
    show_critical_nodes: bool = True,
    show_chains: bool = True,
    max_chain_markers: int = 200,
) -> folium.Map:
    """
    Build the full Panopticon intelligence map.

    Returns a folium.Map ready for st_folium(). Do NOT cache this object.
    """
    seeds = seeds or []
    observables = observables or []

    # Auto-center if we have seeds
    if seeds:
        center_lat, center_lon, zoom = _auto_center(seeds)

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        tiles=None,  # we'll add tiles manually
        control_scale=True,
        prefer_canvas=True,
    )

    # Inject pulse CSS
    m.get_root().html.add_child(folium.Element(PULSE_CSS))

    # --- Base layers ---
    _add_satellite_layer(m)
    _add_dark_layer(m)

    # --- Overlay layers ---
    if show_watch_zones:
        _add_watch_zones(m)

    if show_critical_nodes:
        _add_critical_nodes(m)

    if observables:
        _add_observable_heatmap(m, observables)
        _add_observable_markers(m, observables)

    if seeds:
        _add_seed_markers(m, seeds)

    if graph and show_chains:
        _add_propagation_chains(m, graph, max_chain_markers)

    # Layer control
    folium.LayerControl(collapsed=False, position="topright").add_to(m)

    return m


# ---------------------------------------------------------------------------
# Tile layers
# ---------------------------------------------------------------------------

def _add_satellite_layer(m: folium.Map) -> None:
    folium.TileLayer(
        tiles=ESRI_SATELLITE_TILE_URL,
        attr=ESRI_SATELLITE_ATTRIBUTION,
        name="Satellite Imagery",
        overlay=False,
        control=True,
    ).add_to(m)


def _add_dark_layer(m: folium.Map) -> None:
    folium.TileLayer(
        tiles=CARTO_DARK_TILE_URL,
        attr=CARTO_DARK_ATTRIBUTION,
        name="Dark Matter",
        overlay=False,
        control=True,
    ).add_to(m)


# ---------------------------------------------------------------------------
# Watch zones
# ---------------------------------------------------------------------------

def _add_watch_zones(m: folium.Map) -> None:
    fg = FeatureGroup(name="Watch Zones", show=True)
    for min_lat, min_lon, max_lat, max_lon, label in DEFAULT_WATCH_ZONES:
        folium.Rectangle(
            bounds=[[min_lat, min_lon], [max_lat, max_lon]],
            color="#4da6ff",
            weight=1.5,
            fill=True,
            fill_color="#4da6ff",
            fill_opacity=0.08,
            tooltip=label,
            popup=folium.Popup(
                f'<div style="{POPUP_STYLE}">'
                f"<b style='color:#4da6ff'>{label}</b><br>"
                f"<hr style='border-color:#1a3a5c;margin:5px 0'>"
                f"{min_lat:.1f}°N – {max_lat:.1f}°N<br>"
                f"{min_lon:.1f}°E – {max_lon:.1f}°E"
                f"</div>",
                max_width=250,
            ),
        ).add_to(fg)
    fg.add_to(m)


# ---------------------------------------------------------------------------
# Critical infrastructure
# ---------------------------------------------------------------------------

def _add_critical_nodes(m: folium.Map) -> None:
    fg = FeatureGroup(name="Critical Infrastructure", show=True)
    for lat, lon, name, category in CRITICAL_NODES:
        icon_name, icon_color = CRITICAL_NODE_ICONS.get(category, ("info-sign", "gray"))
        folium.Marker(
            location=[lat, lon],
            icon=folium.Icon(
                icon=icon_name, prefix="glyphicon",
                color=icon_color, icon_color="white",
            ),
            tooltip=f"[{category.upper()}] {name}",
            popup=folium.Popup(
                f'<div style="{POPUP_STYLE}">'
                f"<b style='color:#4da6ff'>{name}</b><br>"
                f"<span style='color:#888'>Category: {category}</span><br>"
                f"<hr style='border-color:#1a3a5c;margin:5px 0'>"
                f"Lat: {lat:.4f}° | Lon: {lon:.4f}°"
                f"</div>",
                max_width=250,
            ),
        ).add_to(fg)
    fg.add_to(m)


# ---------------------------------------------------------------------------
# Raw observables (heatmap + optional markers)
# ---------------------------------------------------------------------------

def _add_observable_heatmap(m: folium.Map, observables: List[Observable]) -> None:
    """Render raw observables as a heatmap layer (handles thousands of points)."""
    if not observables:
        return
    fg = FeatureGroup(name="Hotspot Density", show=True)
    heat_data = [
        [obs.lat, obs.lon, obs.intensity * obs.confidence]
        for obs in observables
    ]
    folium.plugins.HeatMap(
        heat_data,
        radius=18,
        blur=12,
        max_zoom=13,
        gradient={
            "0.2": "#000066",
            "0.4": "#0044aa",
            "0.6": "#ff8800",
            "0.8": "#ff4400",
            "1.0": "#ff0000",
        },
    ).add_to(fg)
    fg.add_to(m)


def _add_observable_markers(m: folium.Map, observables: List[Observable]) -> None:
    """Render raw observables as small circle markers (capped for performance)."""
    if not observables:
        return
    fg = FeatureGroup(name="Raw Hotspots", show=False)  # off by default
    # Cap at 500 for performance
    display_obs = observables[:500] if len(observables) > 500 else observables
    for obs in display_obs:
        radius = 3 + (obs.intensity * 4)
        color = "#ff6600" if obs.obs_type.value == "thermal_hotspot" else "#4da6ff"
        folium.CircleMarker(
            location=[obs.lat, obs.lon],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.5 * obs.confidence,
            weight=0.5,
            tooltip=(
                f"{obs.obs_type.value} | conf={obs.confidence:.2f}"
            ),
            popup=folium.Popup(
                f'<div style="{POPUP_STYLE}">'
                f"<b style='color:#ff8800'>{obs.obs_type.value.upper()}</b><br>"
                f"<hr style='border-color:#1a3a5c;margin:5px 0'>"
                f"Lat: {obs.lat:.4f}° | Lon: {obs.lon:.4f}°<br>"
                f"Confidence: {obs.confidence:.2f}<br>"
                f"{'Brightness: ' + str(round(obs.brightness_temp_k, 1)) + 'K<br>' if obs.brightness_temp_k else ''}"
                f"{'FRP: ' + str(round(obs.frp_mw, 1)) + ' MW<br>' if obs.frp_mw else ''}"
                f"{'SAR loss: ' + str(round(obs.sar_coherence_loss, 2)) + '<br>' if obs.sar_coherence_loss else ''}"
                f"{'Plume: ' + str(round(obs.plume_vector_deg or 0)) + '° / ' + str(round(obs.plume_length_km or 0, 1)) + 'km<br>' if obs.plume_length_km else ''}"
                f"Time: {obs.timestamp.strftime('%Y-%m-%d %H:%M UTC')}<br>"
                f"Source: {obs.source} / {obs.satellite}"
                f"</div>",
                max_width=280,
            ),
        ).add_to(fg)
    fg.add_to(m)


# ---------------------------------------------------------------------------
# Event seed markers (large, pulsing for high intensity)
# ---------------------------------------------------------------------------

def _add_seed_markers(m: folium.Map, seeds: List[EventSeed]) -> None:
    fg = FeatureGroup(name="Event Seeds", show=True)
    for seed in seeds:
        color = EVENT_TYPE_COLORS.get(seed.event_type.value, "#4da6ff")
        radius = 10 + seed.intensity * 14

        # Standard circle marker
        folium.CircleMarker(
            location=[seed.lat, seed.lon],
            radius=radius,
            color="white",
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=max(0.5, seed.confidence),
            tooltip=seed.label,
            popup=folium.Popup(_make_seed_popup(seed), max_width=300),
        ).add_to(fg)

        # Pulsing ring for high-intensity events
        if seed.intensity > 0.6:
            pulse_size = int(16 + seed.intensity * 16)
            folium.Marker(
                location=[seed.lat, seed.lon],
                icon=folium.DivIcon(
                    html=(
                        f'<div class="pulse-marker" style="'
                        f"width:{pulse_size}px;height:{pulse_size}px;"
                        f"background:{color};opacity:0.5;"
                        f'margin-left:-{pulse_size//2}px;margin-top:-{pulse_size//2}px'
                        f'"></div>'
                    ),
                    icon_size=(pulse_size, pulse_size),
                ),
            ).add_to(fg)

    fg.add_to(m)


def _make_seed_popup(seed: EventSeed) -> str:
    """Build HTML popup for an event seed."""
    color = EVENT_TYPE_COLORS.get(seed.event_type.value, "#4da6ff")
    loc = seed.nearest_critical[2] if seed.nearest_critical else f"{seed.lat:.3f}°, {seed.lon:.3f}°"
    cat = seed.nearest_critical[3] if seed.nearest_critical else "—"
    cluster_size = seed.metadata.get("cluster_size", len(seed.observables))

    cascade_html = ""
    cascades = seed.metadata.get("cascade_effects", [])
    if cascades:
        cascade_items = "".join(
            f"<li>{c['effect']} ({c['timeline_hours']}h) — {c['category']}</li>"
            for c in cascades[:4]
        )
        cascade_html = (
            f"<br><b style='color:#ffaa00'>Cascade Effects:</b>"
            f"<ul style='margin:3px 0;padding-left:18px'>{cascade_items}</ul>"
        )

    return (
        f'<div style="{POPUP_STYLE}">'
        f"<b style='color:{color};font-size:14px'>"
        f"{seed.event_type.value.upper().replace('_', ' ')}</b><br>"
        f"<span style='color:#4da6ff'>{loc}</span> "
        f"<span style='color:#666'>[{cat}]</span>"
        f"<hr style='border-color:#1a3a5c;margin:6px 0'>"
        f"Intensity: <b>{seed.intensity:.2f}</b> | "
        f"Confidence: <b>{seed.confidence:.2f}</b><br>"
        f"Observables: {cluster_size} | "
        f"Persistence: {seed.persistence:.2f}<br>"
        f"Proximity: {seed.proximity_to_critical:.2f}<br>"
        f"Time: {seed.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        f"{cascade_html}"
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Propagation chains (edges + propagated nodes)
# ---------------------------------------------------------------------------

def _add_propagation_chains(
    m: folium.Map,
    graph: TemporalGraph,
    max_markers: int = 200,
) -> None:
    """Draw causal edges and propagated event nodes from the TemporalGraph."""
    # Edges
    edges_fg = FeatureGroup(name="Causal Chains", show=True)
    for u, v, data in graph.G.edges(data=True):
        seed_u = graph.get_seed(u)
        seed_v = graph.get_seed(v)
        if not seed_u or not seed_v:
            continue
        momentum = data.get("momentum", 0.0)
        propensity = data.get("propensity", 0.0)

        # Color gradient: blue (low) → red (high momentum)
        intensity = min(1.0, momentum * 2.5)
        r = int(77 + intensity * 178)
        g = int(166 - intensity * 150)
        b = int(255 - intensity * 200)
        color = f"#{r:02x}{g:02x}{b:02x}"
        weight = 1.5 + propensity * 3

        folium.PolyLine(
            locations=[[seed_u.lat, seed_u.lon], [seed_v.lat, seed_v.lon]],
            color=color,
            weight=weight,
            opacity=0.7,
            tooltip=f"p={propensity:.2f} M={momentum:.3f}",
            dash_array="5 3" if data.get("link_type") == "wildcard" else None,
        ).add_to(edges_fg)
    edges_fg.add_to(m)

    # Propagated nodes (depth > 0)
    nodes_fg = FeatureGroup(name="Propagated Events", show=True)
    propagated = [
        (nid, graph.get_seed(nid))
        for nid in graph.G.nodes()
        if graph.get_seed(nid) and graph.get_seed(nid).depth > 0
    ]
    # Sort by momentum, take top N
    propagated.sort(
        key=lambda x: graph.get_chain_momentum(x[0]), reverse=True
    )
    for nid, seed in propagated[:max_markers]:
        momentum = graph.get_chain_momentum(nid)
        color = EVENT_TYPE_COLORS.get(seed.event_type.value, "#4da6ff")
        radius = 4 + momentum * 10

        folium.CircleMarker(
            location=[seed.lat, seed.lon],
            radius=radius,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.6,
            weight=1,
            tooltip=f"{seed.label} (d={seed.depth}, M={momentum:.3f})",
            popup=folium.Popup(
                f'<div style="{POPUP_STYLE}">'
                f"<b style='color:{color}'>"
                f"{seed.event_type.value.upper().replace('_', ' ')}</b><br>"
                f"Depth: {seed.depth} | Momentum: {momentum:.3f}<br>"
                f"Intensity: {seed.intensity:.2f} | Conf: {seed.confidence:.2f}<br>"
                f"Cause: {seed.metadata.get('cause', '—')}"
                f"</div>",
                max_width=280,
            ),
        ).add_to(nodes_fg)
    nodes_fg.add_to(m)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auto_center(seeds: List[EventSeed]) -> Tuple[float, float, int]:
    """Compute map center and zoom from seed locations."""
    if not seeds:
        return 25.0, 45.0, 4

    lats = [s.lat for s in seeds]
    lons = [s.lon for s in seeds]
    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    lat_span = max(lats) - min(lats)
    lon_span = max(lons) - min(lons)
    span = max(lat_span, lon_span)

    if span < 0.1:
        zoom = 12
    elif span < 0.5:
        zoom = 10
    elif span < 2:
        zoom = 8
    elif span < 10:
        zoom = 6
    elif span < 40:
        zoom = 4
    else:
        zoom = 3

    return center_lat, center_lon, zoom

"""
Multi-source frontline data service.
Fetches Ukraine war frontline data from multiple mapping sources.
Each source is cached independently with configurable TTL.
"""

import asyncio
import logging
import re
import time
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

# KML namespace
KML_NS = "{http://www.opengis.net/kml/2.2}"

# Map DeepState fill colors to our status categories
FILL_STATUS_MAP = {
    "#a52714": "occupied",
    "#880e4f": "occupied",
    "#ff5252": "occupied",
    "#0f9d58": "liberated",
    "#01579b": "liberated",
    "#bcaaa4": "contested",
    "#bdbdbd": "contested",
}

# Map icon files to battle event types
ICON_TYPE_MAP = {
    "images/icon-1.png": "fortification",
    "images/icon-2.png": "battle",
    "images/icon-3.png": "shelling",
    "images/icon-4.png": "advance",
    "images/icon-5.png": "retreat",
    "images/icon-6.png": "explosion",
}

# Source definitions
SOURCES = {
    "deepstate": {
        "name": "DeepStateMap",
        "type": "deepstate_api",
        "url": "https://deepstatemap.live/api/history/last",
        "cache_ttl": 3600,  # 1 hour
        "description": "Most detailed daily frontline updates from the DeepState team",
    },
    "amk": {
        "name": "AMK Mapping",
        "type": "google_kml",
        "google_maps_id": "1thW9kqnDOaS2lAepLhLdzSX8Ur9Sc4k",
        "cache_ttl": 21600,  # 6 hours
        "description": "Pro-Ukrainian mapper with daily control map updates",
    },
    "suriyak": {
        "name": "Suriyakmaps",
        "type": "google_kml",
        "google_maps_id": "1xWP_FpuoVX_EiRpuUNF-8vjMKceydyA",
        "cache_ttl": 21600,
        "description": "Detailed conflict mapper covering Ukraine and Middle East",
    },
    "uacontrol": {
        "name": "UA Control Map",
        "type": "google_kml",
        "google_maps_id": "1V8NzjQkzMOhpuLhkktbiKgodOQ27X6IV",
        "cache_ttl": 21600,
        "description": "Community-maintained Ukraine control map",
    },
    "playfra": {
        "name": "Playfra Map",
        "type": "playfra",
        "base_url": "https://playframap.github.io/data",
        "files": ["Russia.geojson", "Grayzone.geojson"],
        "cache_ttl": 21600,
        "description": "Detailed frontline analysis with gray zone tracking",
    },
    "radov": {
        "name": "Anatoly Radov",
        "type": "google_kml",
        "google_maps_id": "1gO8X7RC8cUzc-1q7-s4-09X53HNIEJA",
        "cache_ttl": 21600,
        "description": "Independent conflict analyst mapping",
    },
}

# Note: TID (27MB) and Weeb (26MB) excluded by default due to size.
# Can be enabled by adding to SOURCES if needed.


def _kml_color_to_hex(kml_color: str) -> str:
    """Convert KML AABBGGRR color to #RRGGBB hex."""
    kml_color = kml_color.strip().lstrip("#")
    if len(kml_color) == 8:
        # AABBGGRR -> RRGGBB
        rr = kml_color[6:8]
        gg = kml_color[4:6]
        bb = kml_color[2:4]
        return f"#{rr}{gg}{bb}"
    elif len(kml_color) == 6:
        # Might already be RGB — return as-is
        return f"#{kml_color}"
    return "#888888"


def _folder_name_to_status(folder_name: str) -> str:
    """Map a KML folder name to a status category."""
    name_lower = folder_name.lower()
    if any(kw in name_lower for kw in ("russian", "occupied", "controlled", "russia")):
        return "occupied"
    if any(kw in name_lower for kw in ("liberated", "ukrainian", "ukraine")):
        return "liberated"
    if any(kw in name_lower for kw in ("gray", "grey", "contested", "disputed", "grayzone")):
        return "contested"
    if "advance" in name_lower:
        return "advance"
    return "unknown"


def _parse_kml_coordinates(coord_str: str) -> list:
    """Parse KML coordinate string (lng,lat,alt ...) into [[lng, lat], ...]."""
    coords = []
    for token in coord_str.strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                lng = float(parts[0])
                lat = float(parts[1])
                coords.append([lng, lat])
            except ValueError:
                pass
    return coords


def _extract_placemarks(element, ns: str, folder_status: str, styles: dict) -> list:
    """Recursively extract Placemarks from a KML element (Document/Folder)."""
    features = []

    # Look for folders first (recurse)
    for folder in element.findall(f"{ns}Folder"):
        folder_name_el = folder.find(f"{ns}name")
        folder_name = folder_name_el.text.strip() if folder_name_el is not None and folder_name_el.text else ""
        status = _folder_name_to_status(folder_name) if folder_name else folder_status
        features.extend(_extract_placemarks(folder, ns, status, styles))

    # Process placemarks in this element
    for placemark in element.findall(f"{ns}Placemark"):
        name_el = placemark.find(f"{ns}name")
        name = name_el.text.strip() if name_el is not None and name_el.text else ""

        description_el = placemark.find(f"{ns}description")
        description = description_el.text.strip() if description_el is not None and description_el.text else ""

        # Determine fill color from styleUrl or inline Style
        fill_color = "#888888"
        style_url_el = placemark.find(f"{ns}styleUrl")
        if style_url_el is not None and style_url_el.text:
            style_id = style_url_el.text.lstrip("#")
            if style_id in styles:
                fill_color = styles[style_id]
            # Also check map styles (styleMap)
            elif f"map_{style_id}" in styles:
                fill_color = styles[f"map_{style_id}"]

        # Inline style
        inline_style = placemark.find(f"{ns}Style")
        if inline_style is not None:
            poly_style = inline_style.find(f"{ns}PolyStyle")
            if poly_style is not None:
                color_el = poly_style.find(f"{ns}color")
                if color_el is not None and color_el.text:
                    fill_color = _kml_color_to_hex(color_el.text)
            line_style = inline_style.find(f"{ns}LineStyle")
            if line_style is not None and fill_color == "#888888":
                color_el = line_style.find(f"{ns}color")
                if color_el is not None and color_el.text:
                    fill_color = _kml_color_to_hex(color_el.text)
            icon_style = inline_style.find(f"{ns}IconStyle")
            if icon_style is not None and fill_color == "#888888":
                color_el = icon_style.find(f"{ns}color")
                if color_el is not None and color_el.text:
                    fill_color = _kml_color_to_hex(color_el.text)

        # Parse geometry
        polygon = placemark.find(f".//{ns}Polygon")
        point = placemark.find(f".//{ns}Point")
        linestring = placemark.find(f".//{ns}LineString")
        multigeometry = placemark.find(f".//{ns}MultiGeometry")

        geom_features = []

        if polygon is not None:
            outer = polygon.find(f".//{ns}outerBoundaryIs//{ns}coordinates")
            if outer is not None and outer.text:
                outer_coords = _parse_kml_coordinates(outer.text)
                if len(outer_coords) >= 3:
                    rings = [outer_coords]
                    # Inner rings (holes)
                    for inner_el in polygon.findall(f".//{ns}innerBoundaryIs//{ns}coordinates"):
                        if inner_el.text:
                            inner_coords = _parse_kml_coordinates(inner_el.text)
                            if inner_coords:
                                rings.append(inner_coords)
                    geom_features.append(("Polygon", {"type": "Polygon", "coordinates": rings}, "zone"))

        elif multigeometry is not None:
            # Handle MultiGeometry — extract all polygons/linestrings within
            for sub_poly in multigeometry.findall(f".//{ns}Polygon"):
                outer = sub_poly.find(f".//{ns}outerBoundaryIs//{ns}coordinates")
                if outer is not None and outer.text:
                    outer_coords = _parse_kml_coordinates(outer.text)
                    if len(outer_coords) >= 3:
                        rings = [outer_coords]
                        for inner_el in sub_poly.findall(f".//{ns}innerBoundaryIs//{ns}coordinates"):
                            if inner_el.text:
                                inner_coords = _parse_kml_coordinates(inner_el.text)
                                if inner_coords:
                                    rings.append(inner_coords)
                        geom_features.append(("Polygon", {"type": "Polygon", "coordinates": rings}, "zone"))
            for sub_line in multigeometry.findall(f".//{ns}LineString"):
                coords_el = sub_line.find(f".//{ns}coordinates")
                if coords_el is not None and coords_el.text:
                    coords = _parse_kml_coordinates(coords_el.text)
                    if len(coords) >= 2:
                        geom_features.append(("LineString", {"type": "LineString", "coordinates": coords}, "line"))

        elif point is not None:
            coords_el = point.find(f"{ns}coordinates")
            if coords_el is not None and coords_el.text:
                coords = _parse_kml_coordinates(coords_el.text)
                if coords:
                    geom_features.append(("Point", {"type": "Point", "coordinates": coords[0]}, "event"))

        elif linestring is not None:
            coords_el = linestring.find(f"{ns}coordinates")
            if coords_el is not None and coords_el.text:
                coords = _parse_kml_coordinates(coords_el.text)
                if len(coords) >= 2:
                    geom_features.append(("LineString", {"type": "LineString", "coordinates": coords}, "line"))

        for geom_type, geometry, layer_type in geom_features:
            features.append({
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "name": name,
                    "description": description[:300] if description else "",
                    "status": folder_status,
                    "fill": fill_color,
                    "layer_type": layer_type,
                },
            })

    return features


def _kml_to_geojson(kml_text: str, source_name: str = "") -> dict:
    """Convert KML XML string to GeoJSON FeatureCollection."""
    try:
        root = ElementTree.fromstring(kml_text)
    except ElementTree.ParseError as e:
        logger.error("KML parse error for %s: %s", source_name, e)
        return {"type": "FeatureCollection", "features": []}

    ns = KML_NS

    # Extract styles (styleId -> fill_color)
    styles: dict[str, str] = {}

    # Parse Style elements
    for style_el in root.iter(f"{ns}Style"):
        style_id = style_el.get("id", "")
        if not style_id:
            continue
        fill_color = None
        poly_style = style_el.find(f"{ns}PolyStyle")
        if poly_style is not None:
            color_el = poly_style.find(f"{ns}color")
            if color_el is not None and color_el.text:
                fill_color = _kml_color_to_hex(color_el.text)
        if fill_color is None:
            line_style = style_el.find(f"{ns}LineStyle")
            if line_style is not None:
                color_el = line_style.find(f"{ns}color")
                if color_el is not None and color_el.text:
                    fill_color = _kml_color_to_hex(color_el.text)
        if fill_color is None:
            icon_style = style_el.find(f"{ns}IconStyle")
            if icon_style is not None:
                color_el = icon_style.find(f"{ns}color")
                if color_el is not None and color_el.text:
                    fill_color = _kml_color_to_hex(color_el.text)
        if fill_color:
            styles[style_id] = fill_color

    # Parse StyleMap — map styleMap id to the normal style's color
    for style_map_el in root.iter(f"{ns}StyleMap"):
        map_id = style_map_el.get("id", "")
        if not map_id:
            continue
        for pair in style_map_el.findall(f"{ns}Pair"):
            key_el = pair.find(f"{ns}key")
            style_url_el = pair.find(f"{ns}styleUrl")
            if key_el is not None and key_el.text == "normal" and style_url_el is not None:
                ref_id = style_url_el.text.lstrip("#") if style_url_el.text else ""
                if ref_id in styles:
                    styles[map_id] = styles[ref_id]
                    break

    # Find Document or use root
    document = root.find(f"{ns}Document")
    if document is None:
        document = root

    features = _extract_placemarks(document, ns, "unknown", styles)

    logger.info("KML→GeoJSON for %s: %d features extracted", source_name, len(features))
    return {"type": "FeatureCollection", "features": features}


class FrontlineService:
    def __init__(self):
        self._cache: dict[str, dict] = {}  # source_id -> {data, fetched_at}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, source_id: str) -> asyncio.Lock:
        if source_id not in self._locks:
            self._locks[source_id] = asyncio.Lock()
        return self._locks[source_id]

    def get_available_sources(self) -> list[dict]:
        """Return list of available frontline sources with metadata."""
        return [
            {
                "id": sid,
                "name": s["name"],
                "description": s["description"],
                "cached": sid in self._cache,
                "cached_at": self._cache[sid]["fetched_at"] if sid in self._cache else None,
            }
            for sid, s in SOURCES.items()
        ]

    async def get_frontlines(self, source_id: str = "deepstate") -> dict:
        """Get frontline GeoJSON for a specific source."""
        if source_id not in SOURCES:
            return {
                "type": "FeatureCollection",
                "features": [],
                "error": f"Unknown source: {source_id}",
            }

        source = SOURCES[source_id]
        now = time.time()

        # Check cache (without lock for fast path)
        if source_id in self._cache:
            cached = self._cache[source_id]
            if (now - cached["fetched_at"]) < source["cache_ttl"]:
                return cached["data"]

        async with self._get_lock(source_id):
            # Double-check after acquiring lock
            if source_id in self._cache:
                cached = self._cache[source_id]
                if (time.time() - cached["fetched_at"]) < source["cache_ttl"]:
                    return cached["data"]

            try:
                if source["type"] == "deepstate_api":
                    data = await self._fetch_deepstate(source)
                elif source["type"] == "google_kml":
                    data = await self._fetch_google_kml(source)
                elif source["type"] == "playfra":
                    data = await self._fetch_playfra(source)
                else:
                    data = {"type": "FeatureCollection", "features": []}

                self._cache[source_id] = {"data": data, "fetched_at": time.time()}
                logger.info(
                    "Frontline data fetched for %s: %d features",
                    source_id,
                    len(data.get("features", [])),
                )
                return data

            except Exception as e:
                logger.error("Failed to fetch frontline data for %s: %s", source_id, e)
                if source_id in self._cache:
                    logger.info("Returning stale cache for %s", source_id)
                    return self._cache[source_id]["data"]
                return {
                    "type": "FeatureCollection",
                    "features": [],
                    "error": str(e),
                }

    async def _fetch_deepstate(self, source: dict) -> dict:
        """Fetch latest frontline GeoJSON from DeepState API."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(source["url"])
            resp.raise_for_status()
            data = resp.json()

        raw_geojson = data.get("map", {})
        features = raw_geojson.get("features", [])

        processed = []
        for f in features:
            geom = f.get("geometry", {})
            props = f.get("properties", {})
            name = props.get("name", "")

            if geom.get("type") == "Polygon":
                coords = geom.get("coordinates", [])
                flat_coords = []
                for ring in coords:
                    flat_coords.append([[c[0], c[1]] for c in ring])

                fill = props.get("fill", "")
                status = FILL_STATUS_MAP.get(fill, "unknown")
                fill_opacity = float(props.get("fill-opacity", 0.4))
                stroke_color = props.get("stroke", fill)

                display_name = name
                parts = name.split("///")
                if len(parts) >= 2:
                    display_name = parts[1].strip()

                processed.append({
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": flat_coords},
                    "properties": {
                        "name": display_name,
                        "status": status,
                        "fill": fill,
                        "fill_opacity": fill_opacity,
                        "stroke": stroke_color,
                        "stroke_width": float(props.get("stroke-width", 2)),
                        "layer_type": "zone",
                    },
                })

            elif geom.get("type") == "Point":
                icon = props.get("icon", "")
                event_type = ICON_TYPE_MAP.get(icon, "event")

                description = props.get("description", "")
                plain_desc = re.sub(r"<[^>]+>", " ", description).strip()
                plain_desc = re.sub(r"\s+", " ", plain_desc)[:300]

                display_name = name
                parts = name.split("///")
                if len(parts) >= 2:
                    display_name = parts[1].strip()

                coords = geom.get("coordinates", [0, 0])
                processed.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [coords[0], coords[1]],
                    },
                    "properties": {
                        "name": display_name,
                        "event_type": event_type,
                        "icon_src": icon,
                        "description": plain_desc,
                        "layer_type": "event",
                    },
                })

        return {"type": "FeatureCollection", "features": processed}

    async def _fetch_google_kml(self, source: dict) -> dict:
        """Fetch and convert a Google Maps KML to GeoJSON."""
        mid = source["google_maps_id"]
        url = f"https://www.google.com/maps/d/kml?forcekml=1&mid={mid}"
        source_name = source.get("name", mid)

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        return _kml_to_geojson(resp.text, source_name)

    async def _fetch_playfra(self, source: dict) -> dict:
        """Fetch Playfra GeoJSON files and merge into one FeatureCollection."""
        base = source["base_url"]
        files = source["files"]
        all_features = []

        async with httpx.AsyncClient(timeout=30) as client:
            for filename in files:
                try:
                    resp = await client.get(f"{base}/{filename}")
                    if resp.status_code != 200:
                        logger.warning("Playfra: %s returned %d", filename, resp.status_code)
                        continue
                    geojson = resp.json()

                    # Determine status from filename
                    if "Russia" in filename:
                        status = "occupied"
                    elif "Gray" in filename or "gray" in filename:
                        status = "contested"
                    else:
                        status = "unknown"

                    for feature in geojson.get("features", []):
                        feature.setdefault("properties", {})
                        feature["properties"]["status"] = status
                        feature["properties"]["layer_type"] = "zone"
                        feature["properties"]["source"] = "playfra"
                        all_features.append(feature)

                    logger.info("Playfra: loaded %s (%d features)", filename, len(geojson.get("features", [])))
                except Exception as e:
                    logger.error("Playfra: failed to load %s: %s", filename, e)

        return {"type": "FeatureCollection", "features": all_features}


# Singleton
frontline_service = FrontlineService()

"""Map layer data endpoints — FIRMS, frontlines, flights, ships, satellites, translation."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.firms_collector import CONFLICT_ZONES
from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.post import Post
from app.models.user import User
from app.services.frontline_service import frontline_service
from app.services.sentiment_analyzer import analyze_sentiment
from app.services.translator import translator

logger = logging.getLogger("orthanc.routers.layers")

router = APIRouter(tags=["layers"])


# ---------------------------------------------------------------------------
# FIRMS thermal data
# ---------------------------------------------------------------------------

@router.get("/layers/firms")
async def get_firms_data(
    region: str | None = Query(default=None, description="Conflict zone: ukraine, middle_east, sudan, myanmar"),
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Get recent FIRMS thermal anomaly detections for map overlay."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    stmt = (
        select(Post)
        .where(Post.source_type == "firms")
        .where(Post.timestamp >= cutoff)
        .order_by(Post.timestamp.desc())
        .limit(2000)
    )

    result = await db.execute(stmt)
    posts = result.scalars().all()

    out = []
    for post in posts:
        raw = post.raw_json or {}
        lat = raw.get("lat")
        lng = raw.get("lng")
        if lat is None or lng is None:
            continue

        # Filter by region bounding box if requested
        if region and region in CONFLICT_ZONES:
            bbox = CONFLICT_ZONES[region]
            if not (
                bbox["lat_min"] <= lat <= bbox["lat_max"]
                and bbox["lng_min"] <= lng <= bbox["lng_max"]
            ):
                continue

        out.append({
            "lat": lat,
            "lng": lng,
            "brightness": raw.get("brightness"),
            "frp": raw.get("frp"),
            "confidence": raw.get("confidence"),
            "satellite": raw.get("satellite"),
            "daynight": raw.get("daynight"),
            "zone": raw.get("zone"),
            "timestamp": post.timestamp.isoformat() if post.timestamp else None,
            "post_id": str(post.id),
        })

    logger.debug("FIRMS query: region=%s hours=%d → %d detections", region, hours, len(out))
    return out


# ---------------------------------------------------------------------------
# Frontlines
# ---------------------------------------------------------------------------

@router.get("/layers/frontlines/sources")
async def get_frontline_sources(
    current_user: User = Depends(get_current_user),
) -> list:
    """List available frontline data sources with metadata."""
    return frontline_service.get_available_sources()


@router.get("/layers/frontlines")
async def get_frontlines_endpoint(
    source: str = Query(default="deepstate", description="Frontline data source id"),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get frontline GeoJSON from the specified source."""
    return await frontline_service.get_frontlines(source)


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------

@router.get("/layers/flights")
async def get_flights_endpoint(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get currently tracked flights as GeoJSON FeatureCollection.
    Pulls from the FlightCollector's in-memory cache.
    """
    try:
        from app.collectors.flight_collector import flight_collector
        flights = flight_collector.get_current_flights()
    except Exception as exc:
        logger.warning("Flight collector unavailable: %s", exc)
        flights = []

    features = []
    for f in flights:
        lat = f.get("lat")
        lng = f.get("lng")
        if lat is None or lng is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "icao24": f.get("icao24"),
                "callsign": f.get("callsign"),
                "altitude": f.get("altitude"),
                "velocity": f.get("velocity"),
                "heading": f.get("heading"),
                "origin_country": f.get("origin_country"),
                "on_ground": f.get("on_ground"),
                "zone": f.get("zone"),
                "is_military": f.get("is_military", False),
                "updated_at": f.get("updated_at"),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Ships (AIS + demo data)
# ---------------------------------------------------------------------------

# Demo ship data for immediate map functionality
DEMO_SHIPS = [
    # Black Sea
    {
        "vessel_name": "IVAN PAPANIN",
        "mmsi": "273355150",
        "ship_type": "Military",
        "lat": 43.20,
        "lng": 33.50,
        "speed": 12.4,
        "heading": 285,
        "destination": "SEVASTOPOL",
        "region": "black_sea",
    },
    {
        "vessel_name": "CAESAR KUNIKOV",
        "mmsi": "273310840",
        "ship_type": "Military",
        "lat": 44.60,
        "lng": 33.30,
        "speed": 8.2,
        "heading": 178,
        "destination": "NOVOROSSIYSK",
        "region": "black_sea",
    },
    {
        "vessel_name": "ODESSA GLORY",
        "mmsi": "272123456",
        "ship_type": "Cargo",
        "lat": 46.30,
        "lng": 30.70,
        "speed": 10.1,
        "heading": 220,
        "destination": "ISTANBUL",
        "region": "black_sea",
    },
    {
        "vessel_name": "SEA BREEZE",
        "mmsi": "212654321",
        "ship_type": "Tanker",
        "lat": 42.10,
        "lng": 37.80,
        "speed": 14.3,
        "heading": 95,
        "destination": "TRABZON",
        "region": "black_sea",
    },
    # Strait of Hormuz
    {
        "vessel_name": "MAKRAN",
        "mmsi": "422000001",
        "ship_type": "Military",
        "lat": 26.55,
        "lng": 56.70,
        "speed": 9.0,
        "heading": 265,
        "destination": "BANDAR ABBAS",
        "region": "hormuz",
    },
    {
        "vessel_name": "GULF UNITY",
        "mmsi": "463000123",
        "ship_type": "Tanker",
        "lat": 26.60,
        "lng": 57.10,
        "speed": 11.5,
        "heading": 280,
        "destination": "FUJAIRAH",
        "region": "hormuz",
    },
    {
        "vessel_name": "PERSIAN STAR",
        "mmsi": "422100452",
        "ship_type": "Tanker",
        "lat": 26.40,
        "lng": 56.20,
        "speed": 13.2,
        "heading": 65,
        "destination": "SINGAPORE",
        "region": "hormuz",
    },
    {
        "vessel_name": "USS BATAAN",
        "mmsi": "338000001",
        "ship_type": "Military",
        "lat": 25.90,
        "lng": 58.30,
        "speed": 16.0,
        "heading": 180,
        "destination": "FIFTH FLEET",
        "region": "hormuz",
    },
    # Red Sea
    {
        "vessel_name": "GALAXY LEADER",
        "mmsi": "248750000",
        "ship_type": "Vehicle Carrier",
        "lat": 14.50,
        "lng": 42.80,
        "speed": 0.0,
        "heading": 0,
        "destination": "HODEIDAH",
        "region": "red_sea",
    },
    {
        "vessel_name": "MSC PALATIUM III",
        "mmsi": "215123456",
        "ship_type": "Container Ship",
        "lat": 22.30,
        "lng": 38.10,
        "speed": 15.4,
        "heading": 355,
        "destination": "SUEZ",
        "region": "red_sea",
    },
    {
        "vessel_name": "MAERSK HANGZHOU",
        "mmsi": "219456789",
        "ship_type": "Container Ship",
        "lat": 18.70,
        "lng": 41.60,
        "speed": 13.8,
        "heading": 340,
        "destination": "PORT SAID",
        "region": "red_sea",
    },
    {
        "vessel_name": "USS CARNEY",
        "mmsi": "338100001",
        "ship_type": "Military",
        "lat": 20.10,
        "lng": 39.80,
        "speed": 18.0,
        "heading": 15,
        "destination": "PATROL",
        "region": "red_sea",
    },
]


@router.get("/layers/ships")
async def get_ships_endpoint(
    region: str | None = Query(default=None, description="Region filter: black_sea, hormuz, red_sea"),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get ship positions as GeoJSON FeatureCollection.
    Merges live AIS data (if configured) with demo data.
    """
    # Try to get live AIS data
    live_ships: list[dict] = []
    try:
        from app.collectors.ais_collector import ais_collector
        live_ships = ais_collector.get_current_ships()
    except Exception as exc:
        logger.debug("AIS collector unavailable: %s", exc)

    # Build features from live data
    features = []
    seen_mmsi: set[str] = set()

    for ship in live_ships:
        lat = ship.get("lat")
        lng = ship.get("lng")
        mmsi = ship.get("mmsi", "")
        if lat is None or lng is None:
            continue
        if region and ship.get("region") and ship["region"] != region:
            continue
        seen_mmsi.add(mmsi)
        features.append(_ship_feature(ship))

    # Add demo ships (fill in what live data doesn't have)
    for ship in DEMO_SHIPS:
        if ship["mmsi"] in seen_mmsi:
            continue
        if region and ship.get("region") != region:
            continue
        features.append(_ship_feature(ship))

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "live_count": len(live_ships),
            "demo_count": len(features) - len(live_ships),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _ship_feature(ship: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [ship.get("lng"), ship.get("lat")],
        },
        "properties": {
            "vessel_name": ship.get("vessel_name", "Unknown"),
            "mmsi": ship.get("mmsi"),
            "ship_type": ship.get("ship_type", "Unknown"),
            "speed": ship.get("speed", 0),
            "heading": ship.get("heading", 0),
            "destination": ship.get("destination", ""),
            "call_sign": ship.get("call_sign"),
            "region": ship.get("region"),
            "updated_at": ship.get("updated_at"),
        },
    }


# ---------------------------------------------------------------------------
# Satellites
# ---------------------------------------------------------------------------

@router.get("/layers/satellites")
async def get_satellites_endpoint(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return current satellite positions as GeoJSON FeatureCollection."""
    try:
        from app.collectors.satellite_collector import satellite_collector
        positions = satellite_collector.current_positions
    except Exception as exc:
        logger.warning("Satellite collector unavailable: %s", exc)
        positions = []

    features = []
    for pos in positions:
        lat = pos.get("lat")
        lng = pos.get("lng")
        if lat is None or lng is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "name": pos.get("name", "Unknown"),
                "group": pos.get("group", "unknown"),
                "altitude_km": pos.get("altitude_km"),
                "velocity_kms": pos.get("velocity_kms"),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "count": len(features),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Sentiment heatmap layer
# ---------------------------------------------------------------------------

def _score_to_color(score: float) -> str:
    """Map sentiment score to hex color. -1=red, 0=yellow, +1=green."""
    if score < -0.3:
        return '#ef4444'  # Red — high threat
    elif score < -0.1:
        return '#f97316'  # Orange — elevated
    elif score < 0.1:
        return '#eab308'  # Yellow — neutral
    elif score < 0.3:
        return '#84cc16'  # Lime — positive
    else:
        return '#22c55e'  # Green — very positive


@router.get("/layers/sentiment")
async def get_sentiment_layer(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """GeoJSON layer with sentiment-scored events for heatmap coloring."""
    since = datetime.utcnow() - timedelta(hours=hours)

    # Get events with post content
    result = await db.execute(text("""
        SELECT e.lat, e.lng, e.place_name, p.content, p.source_type, p.timestamp
        FROM events e
        JOIN posts p ON p.id = e.post_id
        WHERE p.timestamp >= :since
          AND e.lat IS NOT NULL AND e.lng IS NOT NULL
    """), {"since": since})

    rows = result.fetchall()

    # Group by place_name (or round coordinates for unnamed locations)
    locations: dict = {}
    for row in rows:
        key = row.place_name or f"{round(row.lat, 1)},{round(row.lng, 1)}"
        if key not in locations:
            locations[key] = {
                "lat": row.lat,
                "lng": row.lng,
                "place_name": row.place_name or key,
                "scores": [],
                "post_count": 0,
            }
        score, _ = analyze_sentiment(row.content or "")
        locations[key]["scores"].append(score)
        locations[key]["post_count"] += 1

    # Build GeoJSON
    features = []
    for loc_data in locations.values():
        scores = loc_data["scores"]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        avg_score = round(avg_score, 3)
        if avg_score < -0.2:
            label = 'negative'
        elif avg_score > 0.2:
            label = 'positive'
        else:
            label = 'neutral'

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [loc_data["lng"], loc_data["lat"]],
            },
            "properties": {
                "place_name": loc_data["place_name"],
                "sentiment_score": avg_score,
                "sentiment_label": label,
                "post_count": loc_data["post_count"],
                "color": _score_to_color(avg_score),
                "radius": min(30, max(8, loc_data["post_count"] * 2)),
            },
        })

    logger.debug("Sentiment layer: hours=%d → %d locations", hours, len(features))
    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Translation endpoint
# ---------------------------------------------------------------------------

class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "en"


@router.post("/translate")
async def translate_text(
    body: TranslateRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Translate text to the target language using user's AI credentials.
    Detects source language automatically.
    """
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="text field is required")
    if len(body.text) > 10000:
        raise HTTPException(status_code=400, detail="text too long (max 10000 chars)")

    result = await translator.translate(
        text=body.text,
        target_lang=body.target_lang,
        user_id=str(current_user.id),
    )
    return result

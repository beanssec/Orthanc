"""Natural Language Query endpoint for Orthanc OSINT platform.

POST /query
Accepts a natural language question, translates it into a structured query plan
via LLM, executes the plan against the database, and returns both structured
data and a natural language answer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models.entity import Entity, EntityMention
from app.models.event import Event
from app.models.financial import Signal
from app.models.post import Post
from app.models.user import User
from app.services.collector_manager import collector_manager

logger = logging.getLogger("orthanc.routers.nlquery")

router = APIRouter(tags=["nlquery"])

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class NLQueryRequest(BaseModel):
    question: str
    model_id: Optional[str] = None  # override model


# ---------------------------------------------------------------------------
# LLM helpers — same pattern as brief_generator.py
# ---------------------------------------------------------------------------

PLAN_SYSTEM_PROMPT = """You are an intelligence analyst assistant for the Orthanc OSINT platform.
Given a user's question, generate a JSON query plan to answer it.

Available data:
- posts: OSINT feed items (fields: content, source_type, author, timestamp)
  source_types: rss, x, telegram, reddit, discord, shodan, webhook, firms, document, cashtag
- entities: extracted named entities (fields: name, type [GPE/PERSON/ORG/NORP/EVENT])
- events: geo-located events (fields: place_name, lat, lng, post_id)
- signals: OSINT→market correlation signals (fields: title, summary, signal_type, affected_tickers)
- quotes: market data (tickers, prices)

Respond with ONLY valid JSON (no markdown, no explanation):
{
  "plan": "brief description of what you will search for",
  "queries": [
    {"type": "search", "q": "search terms", "types": "posts,entities", "hours": 48},
    {"type": "entity_top", "hours": 24, "limit": 10},
    {"type": "entity_search", "q": "entity name"},
    {"type": "events_near", "lat": 33.3, "lng": 44.4, "radius_km": 100, "hours": 48},
    {"type": "signals", "hours": 72, "limit": 10},
    {"type": "summarize"}
  ]
}

Query type details:
- search: text search across data. Required: q (string). Optional: types (comma-separated: posts,entities,events), hours (default 48)
- entity_top: top entities by mention count. Optional: hours (default 48), limit (default 10)
- entity_search: search for a specific entity by name. Required: q (string)
- events_near: find events near coordinates. Required: lat, lng. Optional: radius_km (default 200), hours (default 48)
- signals: recent OSINT→market signals. Optional: hours (default 72), limit (default 10)
- summarize: generate a natural language answer from all collected data (always include this last)

IMPORTANT: Always include a "summarize" query as the LAST item. Keep queries focused and relevant.
"""

SUMMARIZE_SYSTEM_PROMPT = """You are an intelligence analyst for Orthanc OSINT platform.
You have been given data collected from OSINT sources to answer a user's question.
Provide a concise, analytical answer. Be direct and factual. Cite sources where relevant.
Format your answer in clear prose — no markdown headers, just paragraphs.
If the data is insufficient to fully answer the question, say so and summarize what IS available.
Keep your answer under 400 words."""


async def _get_llm_credentials(user_id: str) -> tuple[str, str, str] | None:
    """Try xAI first, then OpenRouter. Returns (api_key, endpoint, model_id) or None."""
    # Try xAI / Grok
    xai_keys = await collector_manager.get_keys(user_id, "x")
    if xai_keys and xai_keys.get("api_key"):
        return (
            xai_keys["api_key"],
            "https://api.x.ai/v1/chat/completions",
            "grok-3-mini",
        )

    # Fall back to OpenRouter
    or_keys = await collector_manager.get_keys(user_id, "openrouter")
    if or_keys and or_keys.get("api_key"):
        return (
            or_keys["api_key"],
            "https://openrouter.ai/api/v1/chat/completions",
            "anthropic/claude-haiku-3.5",
        )

    return None


async def _call_llm(
    api_key: str,
    endpoint: str,
    model_id: str,
    system: str,
    user_msg: str,
    timeout: float = 20.0,
) -> str:
    """Call an OpenAI-compatible LLM endpoint and return the assistant's message content."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if "openrouter" in endpoint:
        headers["HTTP-Referer"] = "https://orthanc.local"
        headers["X-Title"] = "Orthanc OSINT"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            endpoint,
            json={
                "model": model_id,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.1,
            },
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Query executors — hit the DB directly, no HTTP calls
# ---------------------------------------------------------------------------


async def _exec_search(q: dict, db: AsyncSession) -> dict[str, list]:
    """Execute a 'search' query: text search across posts, entities, events."""
    search_q = q.get("q", "")
    hours = q.get("hours", 48)
    types_str = q.get("types", "posts,entities,events")
    types = {t.strip() for t in types_str.split(",")}

    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    results: dict[str, list] = {}

    if "posts" in types and search_q:
        stmt = (
            select(Post)
            .where(Post.content.ilike(f"%{search_q}%"))
            .where(Post.timestamp >= since)
            .order_by(Post.timestamp.desc())
            .limit(20)
        )
        rows = (await db.execute(stmt)).scalars().all()
        results["posts"] = [
            {
                "id": str(p.id),
                "source_type": p.source_type,
                "author": p.author or "",
                "snippet": (p.content or "")[:300],
                "timestamp": p.timestamp.isoformat() if p.timestamp else None,
            }
            for p in rows
        ]

    if "entities" in types and search_q:
        stmt = (
            select(Entity)
            .where(Entity.name.ilike(f"%{search_q}%"))
            .where(Entity.last_seen >= since)
            .order_by(Entity.mention_count.desc())
            .limit(15)
        )
        rows = (await db.execute(stmt)).scalars().all()
        results["entities"] = [
            {
                "id": str(e.id),
                "name": e.name,
                "type": e.type,
                "mention_count": e.mention_count,
                "last_seen": e.last_seen.isoformat() if e.last_seen else None,
            }
            for e in rows
        ]

    if "events" in types and search_q:
        stmt = (
            select(Event)
            .join(Post, Event.post_id == Post.id)
            .where(Event.place_name.ilike(f"%{search_q}%"))
            .where(Post.timestamp >= since)
            .order_by(Post.timestamp.desc())
            .limit(15)
        )
        rows = (await db.execute(stmt)).scalars().all()
        results["events"] = [
            {
                "id": str(ev.id),
                "place_name": ev.place_name or "",
                "lat": ev.lat,
                "lng": ev.lng,
                "post_id": str(ev.post_id),
            }
            for ev in rows
        ]

    return results


async def _exec_entity_top(q: dict, db: AsyncSession) -> list:
    """Get top entities by recent mention count."""
    hours = q.get("hours", 48)
    limit = q.get("limit", 10)
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    rows = await db.execute(
        text("""
            SELECT e.id, e.name, e.type, count(em.id) AS mentions
            FROM entities e
            JOIN entity_mentions em ON em.entity_id = e.id
            JOIN posts p ON p.id = em.post_id
            WHERE p.timestamp >= :since
            GROUP BY e.id, e.name, e.type
            ORDER BY mentions DESC
            LIMIT :limit
        """),
        {"since": since, "limit": limit},
    )
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "type": row.type,
            "recent_mentions": row.mentions,
        }
        for row in rows.fetchall()
    ]


async def _exec_entity_search(q: dict, db: AsyncSession) -> list:
    """Search for a specific entity by name."""
    search_q = q.get("q", "")
    if not search_q:
        return []
    stmt = (
        select(Entity)
        .where(Entity.name.ilike(f"%{search_q}%"))
        .order_by(Entity.mention_count.desc())
        .limit(10)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "type": e.type,
            "mention_count": e.mention_count,
            "first_seen": e.first_seen.isoformat() if e.first_seen else None,
            "last_seen": e.last_seen.isoformat() if e.last_seen else None,
        }
        for e in rows
    ]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in km."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _exec_events_near(q: dict, db: AsyncSession) -> list:
    """Find geo events near a coordinate."""
    lat = float(q.get("lat", 0))
    lng = float(q.get("lng", 0))
    radius_km = float(q.get("radius_km", 200))
    hours = q.get("hours", 48)
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    # Bounding box pre-filter (1 degree ≈ 111 km)
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))

    rows = await db.execute(
        text("""
            SELECT ev.id, ev.place_name, ev.lat, ev.lng, ev.post_id,
                   p.timestamp, p.content, p.source_type
            FROM events ev
            JOIN posts p ON p.id = ev.post_id
            WHERE ev.lat BETWEEN :lat_min AND :lat_max
              AND ev.lng BETWEEN :lng_min AND :lng_max
              AND p.timestamp >= :since
            ORDER BY p.timestamp DESC
            LIMIT 100
        """),
        {
            "lat_min": lat - lat_delta,
            "lat_max": lat + lat_delta,
            "lng_min": lng - lng_delta,
            "lng_max": lng + lng_delta,
            "since": since,
        },
    )
    all_rows = rows.fetchall()

    # Exact haversine filter
    nearby = []
    for row in all_rows:
        if row.lat is not None and row.lng is not None:
            dist = _haversine_km(lat, lng, row.lat, row.lng)
            if dist <= radius_km:
                nearby.append(
                    {
                        "id": str(row.id),
                        "place_name": row.place_name or "",
                        "lat": row.lat,
                        "lng": row.lng,
                        "post_id": str(row.post_id),
                        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                        "snippet": (row.content or "")[:200],
                        "source_type": row.source_type,
                        "distance_km": round(dist, 1),
                    }
                )

    nearby.sort(key=lambda x: x["distance_km"])
    return nearby[:30]


async def _exec_signals(q: dict, db: AsyncSession, user_id: str) -> list:
    """Get recent OSINT→market signals."""
    hours = q.get("hours", 72)
    limit = q.get("limit", 10)
    since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

    import uuid as uuid_mod

    stmt = (
        select(Signal)
        .where(Signal.user_id == uuid_mod.UUID(user_id))
        .where(Signal.generated_at >= since)
        .order_by(Signal.generated_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(s.id),
            "signal_type": s.signal_type,
            "severity": s.severity,
            "title": s.title,
            "summary": s.summary,
            "affected_tickers": s.affected_tickers,
            "generated_at": s.generated_at.isoformat() if s.generated_at else None,
        }
        for s in rows
    ]


# ---------------------------------------------------------------------------
# Context builder — turns collected data into LLM-readable text
# ---------------------------------------------------------------------------


def _build_context(data: dict[str, Any], question: str) -> str:
    """Format collected data as text context for the summarize LLM call."""
    sections: list[str] = [f"USER QUESTION: {question}\n"]

    posts = data.get("posts", [])
    if posts:
        sections.append(f"=== POSTS ({len(posts)}) ===")
        for p in posts[:20]:
            ts = p.get("timestamp", "")[:16] if p.get("timestamp") else "?"
            sections.append(f"[{p.get('source_type','?').upper()}] [{ts}] {p.get('author','')}: {p.get('snippet','')[:200]}")

    entities = data.get("entities", [])
    if entities:
        sections.append(f"\n=== ENTITIES ({len(entities)}) ===")
        for e in entities[:15]:
            mentions = e.get("mention_count") or e.get("recent_mentions", 0)
            sections.append(f"  {e['name']} ({e['type']}) — {mentions} mentions")

    events = data.get("events", [])
    if events:
        sections.append(f"\n=== GEO EVENTS ({len(events)}) ===")
        for ev in events[:15]:
            dist = f" [{ev['distance_km']}km]" if "distance_km" in ev else ""
            sections.append(f"  {ev.get('place_name','?')}{dist} — {ev.get('snippet','')[:100]}")

    signals = data.get("signals", [])
    if signals:
        sections.append(f"\n=== MARKET SIGNALS ({len(signals)}) ===")
        for s in signals:
            sections.append(f"  [{s.get('severity','?').upper()}] {s['title']}: {s['summary'][:150]}")

    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------


@router.post("/query")
async def natural_language_query(
    body: NLQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Process a natural language intelligence question.

    1. Ask LLM to create a query plan
    2. Execute each query against the DB
    3. Ask LLM to summarize the results
    4. Return structured data + natural language answer
    """
    question = body.question.strip()
    if not question:
        return {"error": "Question cannot be empty"}

    user_id = str(current_user.id)

    # Get LLM credentials
    creds = await _get_llm_credentials(user_id)
    if not creds:
        return {
            "error": (
                "No AI credentials configured. "
                "Add your xAI or OpenRouter API key in Settings → Credentials."
            )
        }

    api_key, endpoint, model_id = creds
    if body.model_id:
        model_id = body.model_id

    logger.info("NL query: user=%s question=%r model=%s", user_id, question[:80], model_id)

    # ── Step 1: Generate query plan ──────────────────────────────────────────
    plan_text = "unknown"
    queries: list[dict] = []

    try:
        raw_plan = await asyncio.wait_for(
            _call_llm(api_key, endpoint, model_id, PLAN_SYSTEM_PROMPT, question, timeout=20.0),
            timeout=22.0,
        )
        # Strip markdown fences if LLM wrapped in ```json
        raw_plan = raw_plan.strip()
        if raw_plan.startswith("```"):
            raw_plan = raw_plan.split("```", 2)[1]
            if raw_plan.startswith("json"):
                raw_plan = raw_plan[4:]
            raw_plan = raw_plan.rstrip("`").strip()

        plan_obj = json.loads(raw_plan)
        plan_text = plan_obj.get("plan", "Query plan")
        queries = plan_obj.get("queries", [])
        logger.info("Query plan: %s | %d queries", plan_text, len(queries))

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("LLM returned invalid JSON plan, falling back to simple search: %s", e)
        # Fallback: simple search + summarize
        queries = [
            {"type": "search", "q": question, "types": "posts,entities,events", "hours": 48},
            {"type": "summarize"},
        ]
        plan_text = f"Fallback: simple text search for '{question[:50]}'"

    except Exception as e:
        logger.error("LLM plan generation failed: %s", e)
        return {"error": f"AI query planning failed: {str(e)[:200]}"}

    # ── Step 2: Execute each query ───────────────────────────────────────────
    collected: dict[str, Any] = {
        "posts": [],
        "entities": [],
        "events": [],
        "signals": [],
    }
    queries_executed = 0
    needs_summarize = False

    for q in queries:
        qtype = q.get("type", "")

        try:
            if qtype == "search":
                res = await _exec_search(q, db)
                collected["posts"] = _merge_list(collected["posts"], res.get("posts", []), "id")
                collected["entities"] = _merge_list(collected["entities"], res.get("entities", []), "id")
                collected["events"] = _merge_list(collected["events"], res.get("events", []), "id")
                queries_executed += 1

            elif qtype == "entity_top":
                ents = await _exec_entity_top(q, db)
                collected["entities"] = _merge_list(collected["entities"], ents, "id")
                queries_executed += 1

            elif qtype == "entity_search":
                ents = await _exec_entity_search(q, db)
                collected["entities"] = _merge_list(collected["entities"], ents, "id")
                queries_executed += 1

            elif qtype == "events_near":
                evts = await _exec_events_near(q, db)
                collected["events"] = _merge_list(collected["events"], evts, "id")
                queries_executed += 1

            elif qtype == "signals":
                sigs = await _exec_signals(q, db, user_id)
                collected["signals"] = _merge_list(collected["signals"], sigs, "id")
                queries_executed += 1

            elif qtype == "summarize":
                needs_summarize = True
                # Don't count this as a data query

        except Exception as e:
            logger.warning("Query execution error for type=%s: %s", qtype, e)

    # ── Step 3: Summarize ────────────────────────────────────────────────────
    answer = ""
    if needs_summarize or True:  # always summarize
        total = sum(len(v) for v in collected.values())
        context = _build_context(collected, question)

        if total == 0:
            answer = (
                "No relevant data was found in the database matching your question. "
                "This may be because no sources have ingested data on this topic yet, "
                "or the relevant time window has no matching posts."
            )
        else:
            try:
                answer = await asyncio.wait_for(
                    _call_llm(
                        api_key,
                        endpoint,
                        model_id,
                        SUMMARIZE_SYSTEM_PROMPT,
                        context,
                        timeout=20.0,
                    ),
                    timeout=22.0,
                )
            except Exception as e:
                logger.warning("Summarize LLM call failed: %s", e)
                answer = (
                    f"Found {total} results but could not generate a summary: {str(e)[:100]}"
                )

    total_results = sum(len(v) for v in collected.values())

    return {
        "question": question,
        "plan": plan_text,
        "answer": answer,
        "data": collected,
        "metadata": {
            "model_used": model_id,
            "queries_executed": queries_executed,
            "total_results": total_results,
        },
    }


def _merge_list(existing: list, new_items: list, key: str) -> list:
    """Merge two lists, deduplicating by a key field."""
    seen = {item[key] for item in existing if key in item}
    for item in new_items:
        if item.get(key) not in seen:
            existing.append(item)
            seen.add(item.get(key))
    return existing

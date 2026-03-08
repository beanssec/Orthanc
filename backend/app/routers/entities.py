"""Entity linking API router."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import Post, User
from app.models.entity import Entity, EntityMention
from app.models.entity_relationship import EntityRelationship
from app.schemas.entities import EntityConnectionItem, EntityDetailSchema, EntitySchema

logger = logging.getLogger("orthanc.routers.entities")

router = APIRouter(prefix="/entities", tags=["entities"])

# ── Relationship types ─────────────────────────────────────
RELATIONSHIP_TYPES = [
    {"id": "commands", "label": "Commands", "directed": True},
    {"id": "funds", "label": "Funds", "directed": True},
    {"id": "supplies", "label": "Supplies to", "directed": True},
    {"id": "sanctions", "label": "Sanctions", "directed": True},
    {"id": "allied_with", "label": "Allied with", "directed": False},
    {"id": "opposes", "label": "Opposes", "directed": False},
    {"id": "member_of", "label": "Member of", "directed": True},
    {"id": "located_in", "label": "Located in", "directed": True},
    {"id": "parent_org", "label": "Parent org of", "directed": True},
    {"id": "subsidiary", "label": "Subsidiary of", "directed": True},
    {"id": "associated", "label": "Associated with", "directed": False},
]
VALID_REL_TYPES = {r["id"] for r in RELATIONSHIP_TYPES}


# ── Pydantic schemas ───────────────────────────────────────
class RelationshipCreate(BaseModel):
    target_entity_id: uuid.UUID
    relationship_type: str
    confidence: float = 0.5
    notes: Optional[str] = None
    evidence_post_ids: Optional[list[uuid.UUID]] = None





@router.get("/", response_model=list[EntitySchema])
async def list_entities(
    type: Optional[str] = Query(None, description="Filter by entity type (PERSON, ORG, GPE, EVENT, NORP)"),
    sort_by: Literal["mention_count", "last_seen", "name"] = Query("mention_count"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[EntitySchema]:
    query = select(Entity)
    if type:
        query = query.where(Entity.type == type.upper())

    if sort_by == "mention_count":
        query = query.order_by(Entity.mention_count.desc())
    elif sort_by == "last_seen":
        query = query.order_by(Entity.last_seen.desc())
    elif sort_by == "name":
        query = query.order_by(Entity.name.asc())

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/graph")
async def get_entity_graph(
    hours: int = Query(default=48, ge=1, le=720),
    min_mentions: int = Query(default=2, ge=1),
    limit: int = Query(default=50, ge=10, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Entity co-occurrence graph data for force-directed visualization."""
    since = datetime.utcnow() - timedelta(hours=hours)

    top_result = await db.execute(
        text("""
            SELECT e.id, e.name, e.type, count(em.id) AS mentions
            FROM entities e
            JOIN entity_mentions em ON em.entity_id = e.id
            JOIN posts p ON p.id = em.post_id
            WHERE p.timestamp >= :since
            GROUP BY e.id, e.name, e.type
            HAVING count(em.id) >= :min_mentions
            ORDER BY mentions DESC
            LIMIT :limit
        """),
        {"since": since, "min_mentions": min_mentions, "limit": limit},
    )
    entities = top_result.fetchall()
    entity_ids = [row.id for row in entities]  # UUID objects

    edge_list = []
    if len(entity_ids) >= 2:
        # Build dynamic IN clause — works reliably across all asyncpg versions
        placeholders = ", ".join(f":eid{i}" for i in range(len(entity_ids)))
        id_params: dict = {f"eid{i}": entity_ids[i] for i in range(len(entity_ids))}

        edges_result = await db.execute(
            text(f"""
                SELECT
                    e1.id AS source_id,
                    e2.id AS target_id,
                    count(DISTINCT em1.post_id) AS weight
                FROM entity_mentions em1
                JOIN entity_mentions em2
                    ON em1.post_id = em2.post_id
                    AND em1.entity_id < em2.entity_id
                JOIN entities e1 ON e1.id = em1.entity_id
                JOIN entities e2 ON e2.id = em2.entity_id
                JOIN posts p ON p.id = em1.post_id
                WHERE p.timestamp >= :since
                  AND em1.entity_id IN ({placeholders})
                  AND em2.entity_id IN ({placeholders})
                GROUP BY e1.id, e2.id
                HAVING count(DISTINCT em1.post_id) >= 2
                ORDER BY weight DESC
                LIMIT 200
            """),
            {"since": since, **id_params},
        )
        edge_list = edges_result.fetchall()

    return {
        "nodes": [
            {
                "id": str(row.id),
                "name": row.name,
                "type": row.type,
                "mentions": row.mentions,
            }
            for row in entities
        ],
        "edges": [
            {
                "source": str(row.source_id),
                "target": str(row.target_id),
                "weight": row.weight,
            }
            for row in edge_list
        ],
    }


@router.get("/path")
async def find_entity_path(
    source_id: uuid.UUID = Query(...),
    target_id: uuid.UUID = Query(...),
    max_depth: int = Query(default=3, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Find shortest connection path between two entities via co-occurrence (BFS)."""

    def _entity_dict(e: Entity) -> dict:
        return {"id": str(e.id), "name": e.name, "type": e.type}

    # Load source and target
    src_result = await db.execute(select(Entity).where(Entity.id == source_id))
    source_entity = src_result.scalar_one_or_none()
    if not source_entity:
        raise HTTPException(status_code=404, detail="Source entity not found")

    tgt_result = await db.execute(select(Entity).where(Entity.id == target_id))
    target_entity = tgt_result.scalar_one_or_none()
    if not target_entity:
        raise HTTPException(status_code=404, detail="Target entity not found")

    if source_id == target_id:
        return {
            "source": _entity_dict(source_entity),
            "target": _entity_dict(target_entity),
            "path": [{"entity": _entity_dict(source_entity), "connecting_posts": 0}],
            "depth": 0,
            "found": True,
        }

    # BFS: parent[node_id] = (parent_id | None, shared_posts)
    parent: dict[uuid.UUID, tuple[uuid.UUID | None, int]] = {source_id: (None, 0)}
    queue: list[uuid.UUID] = [source_id]
    found = False

    for _depth in range(max_depth):
        if not queue:
            break
        next_queue: list[uuid.UUID] = []
        for current_id in queue:
            nbr_result = await db.execute(
                text("""
                    SELECT DISTINCT
                        CASE
                            WHEN em1.entity_id = :cid THEN em2.entity_id
                            ELSE em1.entity_id
                        END AS neighbor_id,
                        count(DISTINCT em1.post_id) AS shared_posts
                    FROM entity_mentions em1
                    JOIN entity_mentions em2
                        ON em1.post_id = em2.post_id
                        AND em1.entity_id != em2.entity_id
                    WHERE em1.entity_id = :cid OR em2.entity_id = :cid
                    GROUP BY
                        CASE
                            WHEN em1.entity_id = :cid THEN em2.entity_id
                            ELSE em1.entity_id
                        END
                    HAVING count(DISTINCT em1.post_id) >= 2
                """),
                {"cid": current_id},
            )
            for row in nbr_result.fetchall():
                nbr_id = row.neighbor_id
                if nbr_id not in parent:
                    parent[nbr_id] = (current_id, row.shared_posts)
                    if nbr_id == target_id:
                        found = True
                        break
                    next_queue.append(nbr_id)
            if found:
                break
        if found:
            break
        queue = next_queue

    if not found:
        return {
            "source": _entity_dict(source_entity),
            "target": _entity_dict(target_entity),
            "path": [],
            "depth": -1,
            "found": False,
        }

    # Reconstruct path by walking back through parent map
    path_ids: list[tuple[uuid.UUID, int]] = []
    cur = target_id
    while cur is not None:
        par_id, shared = parent[cur]
        path_ids.append((cur, shared))
        cur = par_id  # type: ignore[assignment]
    path_ids.reverse()

    # Load entity names for path nodes
    path_items = []
    for eid, shared in path_ids:
        e_result = await db.execute(select(Entity).where(Entity.id == eid))
        e_obj = e_result.scalar_one_or_none()
        if e_obj:
            path_items.append({"entity": _entity_dict(e_obj), "connecting_posts": shared})

    return {
        "source": _entity_dict(source_entity),
        "target": _entity_dict(target_entity),
        "path": path_items,
        "depth": len(path_items) - 1,
        "found": True,
    }








def _rel_dict(rel: EntityRelationship) -> dict:
    return {
        "id": str(rel.id),
        "entity_a_id": str(rel.entity_a_id),
        "entity_b_id": str(rel.entity_b_id),
        "weight": rel.weight,
        "first_seen": rel.first_seen.isoformat(),
        "last_seen": rel.last_seen.isoformat(),
        "entity_a": {
            "id": str(rel.entity_a.id),
            "name": rel.entity_a.name,
            "type": rel.entity_a.type,
        } if rel.entity_a else None,
        "entity_b": {
            "id": str(rel.entity_b.id),
            "name": rel.entity_b.name,
            "type": rel.entity_b.type,
        } if rel.entity_b else None,
    }


@router.get("/{entity_id}", response_model=EntityDetailSchema)
async def get_entity(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> EntityDetailSchema:
    result = await db.execute(
        select(Entity)
        .where(Entity.id == entity_id)
        .options(selectinload(Entity.mentions))
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.get("/{entity_id}/relationships")
async def get_entity_relationships(
    entity_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    """Get co-occurrence relationships for an entity."""
    from sqlalchemy import or_
    result = await db.execute(
        select(EntityRelationship)
        .where(
            or_(
                EntityRelationship.entity_a_id == entity_id,
                EntityRelationship.entity_b_id == entity_id,
            )
        )
        .options(
            selectinload(EntityRelationship.entity_a),
            selectinload(EntityRelationship.entity_b),
        )
        .order_by(EntityRelationship.weight.desc())
        .limit(50)
    )
    return [_rel_dict(r) for r in result.scalars().all()]





@router.get("/{entity_id}/connections", response_model=list[EntityConnectionItem])
async def get_entity_connections(
    entity_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[EntityConnectionItem]:
    # Check entity exists
    entity_result = await db.execute(select(Entity).where(Entity.id == entity_id))
    if not entity_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Entity not found")

    # Find all posts this entity appears in
    post_ids_result = await db.execute(
        select(EntityMention.post_id).where(EntityMention.entity_id == entity_id)
    )
    post_ids = [row[0] for row in post_ids_result.fetchall()]

    if not post_ids:
        return []

    # Find all other entities in those posts, count co-occurrences
    co_result = await db.execute(
        select(EntityMention.entity_id, func.count(EntityMention.entity_id).label("co_count"))
        .where(
            EntityMention.post_id.in_(post_ids),
            EntityMention.entity_id != entity_id,
        )
        .group_by(EntityMention.entity_id)
        .order_by(func.count(EntityMention.entity_id).desc())
        .limit(limit)
    )
    rows = co_result.fetchall()

    connections: list[EntityConnectionItem] = []
    for row in rows:
        co_entity_id, co_count = row
        ent_result = await db.execute(select(Entity).where(Entity.id == co_entity_id))
        co_entity = ent_result.scalar_one_or_none()
        if co_entity:
            connections.append(EntityConnectionItem(
                entity=co_entity,
                co_occurrences=co_count,
            ))

    return connections


@router.get("/{entity_id}/timeline")
async def get_entity_timeline(
    entity_id: uuid.UUID,
    hours: int = Query(default=168, ge=1, le=99999),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Chronological timeline of all posts mentioning this entity."""
    entity_result = await db.execute(select(Entity).where(Entity.id == entity_id))
    entity = entity_result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    since = datetime.utcnow() - timedelta(hours=hours)
    offset = (page - 1) * page_size

    # Count distinct posts (entity may appear multiple times in one post)
    count_result = await db.execute(
        text("""
            SELECT count(DISTINCT p.id)
            FROM entity_mentions em
            JOIN posts p ON p.id = em.post_id
            WHERE em.entity_id = :eid
              AND (p.timestamp >= :since OR p.timestamp IS NULL)
        """),
        {"eid": entity_id, "since": since},
    )
    total = count_result.scalar() or 0

    # Fetch timeline: one row per post, include first geo event if available
    rows_result = await db.execute(
        text("""
            WITH ranked AS (
                SELECT DISTINCT ON (p.id)
                    p.id        AS post_id,
                    p.content,
                    p.source_type,
                    p.author,
                    p.timestamp,
                    em.context_snippet,
                    ev.lat,
                    ev.lng,
                    ev.place_name
                FROM entity_mentions em
                JOIN posts p ON p.id = em.post_id
                LEFT JOIN LATERAL (
                    SELECT lat, lng, place_name
                    FROM events
                    WHERE post_id = p.id
                    LIMIT 1
                ) ev ON true
                WHERE em.entity_id = :eid
                  AND (p.timestamp >= :since OR p.timestamp IS NULL)
                ORDER BY p.id, p.timestamp DESC
            )
            SELECT * FROM ranked
            ORDER BY timestamp DESC NULLS LAST
            LIMIT :lim OFFSET :off
        """),
        {"eid": entity_id, "since": since, "lim": page_size, "off": offset},
    )
    rows = rows_result.fetchall()

    items = []
    for row in rows:
        items.append({
            "post_id": str(row.post_id),
            "content": row.content,
            "source_type": row.source_type,
            "author": row.author,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "context_snippet": row.context_snippet,
            "event": {
                "lat": row.lat,
                "lng": row.lng,
                "place_name": row.place_name,
            } if row.lat is not None else None,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
        "entity": {
            "id": str(entity.id),
            "name": entity.name,
            "type": entity.type,
            "first_seen": entity.first_seen.isoformat(),
            "last_seen": entity.last_seen.isoformat(),
        },
    }


@router.post("/backfill", status_code=202)
async def backfill_entities(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Trigger background entity extraction for all posts without entity mentions."""
    background_tasks.add_task(_run_entity_backfill)
    return {"status": "accepted", "message": "Entity backfill started in background"}


async def _run_entity_backfill() -> None:
    """Process all posts that don't yet have entity mentions."""
    from datetime import datetime, timezone

    from app.db import AsyncSessionLocal
    from app.services.entity_extractor import entity_extractor

    logger.info("Starting entity backfill")
    processed = 0
    errors = 0

    try:
        async with AsyncSessionLocal() as session:
            # Find posts without any entity mentions
            subquery = select(EntityMention.post_id).distinct()
            result = await session.execute(
                select(Post).where(Post.id.not_in(subquery)).order_by(Post.ingested_at.asc())
            )
            posts = result.scalars().all()

        logger.info("Entity backfill: %d posts to process", len(posts))

        for post in posts:
            try:
                async with AsyncSessionLocal() as session:
                    extracted = entity_extractor.extract_entities(post.content or "")
                    for ent in extracted:
                        canonical = entity_extractor.canonical_name(ent["name"])
                        existing_ent = await session.execute(
                            select(Entity).where(
                                Entity.canonical_name == canonical,
                                Entity.type == ent["type"],
                            )
                        )
                        entity_obj = existing_ent.scalar_one_or_none()
                        if entity_obj:
                            entity_obj.mention_count += 1
                            entity_obj.last_seen = datetime.now(tz=timezone.utc)
                        else:
                            entity_obj = Entity(
                                name=ent["name"],
                                type=ent["type"],
                                canonical_name=canonical,
                                mention_count=1,
                            )
                            session.add(entity_obj)
                            await session.flush()
                        mention = EntityMention(
                            entity_id=entity_obj.id,
                            post_id=post.id,
                            context_snippet=ent["context_snippet"],
                        )
                        session.add(mention)
                    await session.commit()
                processed += 1
            except Exception as exc:
                errors += 1
                logger.warning("Entity backfill error for post %s: %s", post.id, exc)

        logger.info("Entity backfill complete: %d processed, %d errors", processed, errors)
    except Exception as exc:
        logger.error("Entity backfill failed: %s", exc, exc_info=True)

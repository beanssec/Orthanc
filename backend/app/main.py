from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, credentials, sources, feed, alerts, events, media
from app.routers import telegram_auth
from app.routers import entities, dashboard, briefs, webhook
from app.routers import layers
from app.routers import finance
from app.routers import search
from app.routers import documents
from app.routers import collaboration
from app.routers import nlquery
from app.routers import gdelt
from app.routers import investigations
from app.routers import sanctions
from app.routers import fusion
from app.routers import cases
from app.routers import oql
from app.routers import maritime
from app.routers import watchpoints
from app.routers import narratives as narratives_router_module
from app.routers.models import router as models_router
from app.collectors.orchestrator import orchestrator
from app.collectors.satellite_collector import satellite_collector
from app.services.brief_scheduler import brief_scheduler
from app.services.fusion_service import fusion_service
from app.services.maritime_intel_service import maritime_intel_service
from app.services.narrative_engine import narrative_engine
from app.services.narrative_analyzer import narrative_analyzer
from app.services.sentinel_service import sentinel_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orthanc")


async def _velocity_loop() -> None:
    """Periodic background task — evaluates velocity rules every 60 seconds."""
    from app.services import correlation_engine
    from app.db import AsyncSessionLocal

    while True:
        try:
            async with AsyncSessionLocal() as db:
                await correlation_engine.evaluate_velocity_rules(db)
        except Exception as e:
            logger.error("Velocity evaluation error: %s", e)
        await asyncio.sleep(60)


async def _silence_loop() -> None:
    """Periodic background task — evaluates silence rules every 5 minutes."""
    from app.services import correlation_engine
    from app.db import AsyncSessionLocal

    # Stagger start by 30s so it doesn't coincide with velocity on first run
    await asyncio.sleep(30)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await correlation_engine.evaluate_silence_rules(db)
        except Exception as e:
            logger.error("Silence evaluation error: %s", e)
        await asyncio.sleep(300)  # every 5 minutes


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Orthanc API starting up")
    await orchestrator.start_rss()
    await orchestrator.start_reddit()
    await orchestrator.start_youtube()
    await orchestrator.start_bluesky()
    await orchestrator.start_mastodon()
    await orchestrator.start_firms()
    await orchestrator.start_flights()
    await orchestrator.start_market()
    await orchestrator.start_notams()
    try:
        await satellite_collector.start()
    except Exception as exc:
        logger.warning("Satellite collector failed to start: %s", exc)

    # Start correlation engine velocity loop
    velocity_task = asyncio.create_task(_velocity_loop())
    logger.info("Correlation engine velocity loop started")

    # Start silence detection loop (every 5 minutes)
    silence_task = asyncio.create_task(_silence_loop())
    logger.info("Correlation engine silence detection loop started")

    # Start brief scheduler
    scheduler_task = asyncio.create_task(brief_scheduler.run_loop())
    logger.info("Brief scheduler started")

    # Start cross-source intelligence fusion service
    await fusion_service.start()
    logger.info("Fusion service started")

    # Start maritime intelligence analysis loop (every 15 min)
    maritime_task = asyncio.create_task(maritime_intel_service.run_loop())
    logger.info("Maritime intelligence loop started")

    # Start Sentinel-2 satellite change detection service
    await sentinel_service.start()
    logger.info("Sentinel-2 change detection started")

    # Seed default source groups (no-op if already seeded)
    try:
        from app.services.source_group_seeder import seed_source_groups
        await seed_source_groups()
    except Exception as _sg_err:
        logger.warning("Source group seeding skipped (will retry on next start): %s", _sg_err)
    logger.info("Source groups seeded")

    # Try to load the OpenRouter API key for high-quality embeddings.
    # Credential decryption requires a user to have logged in (key material
    # lives in memory), so we attempt it and silently fall back to the
    # deterministic hash-based embeddings when it fails.
    try:
        from app.services.embedding_service import embedding_service
        from app.services.crypto import crypto_service
        from app.models.credential import Credential
        from app.db import AsyncSessionLocal as _ASL
        from sqlalchemy import select as _select

        async with _ASL() as _session:
            _cred_result = await _session.execute(
                _select(Credential).where(Credential.provider == "openrouter")
            )
            _cred = _cred_result.scalars().first()
            if _cred and getattr(_cred, "encrypted_data", None):
                import json as _json
                _decrypted = crypto_service.decrypt(_cred.encrypted_data)
                _cred_data = _json.loads(_decrypted)
                _api_key = _cred_data.get("api_key", "")
                if _api_key:
                    embedding_service.set_api_key(_api_key)
                    logger.info("Embedding service: OpenRouter API key loaded")
                else:
                    logger.info("Embedding service: OpenRouter credential present but empty — using hash-based fallback")
            else:
                logger.info("Embedding service: no OpenRouter credential found — using hash-based fallback")
    except Exception as _emb_err:
        logger.info("Embedding service: using hash-based fallback (%s)", _emb_err)

    # Start narrative clustering engine (embeds posts + clusters into narratives every 10 min)
    await narrative_engine.start()
    logger.info("Narrative clustering engine started")

    # Load OpenRouter key into stance classifier (uses same key as embedding service)
    try:
        from app.services.embedding_service import embedding_service as _emb_svc
        from app.services.stance_classifier import stance_classifier
        if _emb_svc._openrouter_key:
            stance_classifier._api_key = _emb_svc._openrouter_key
            logger.info("Stance classifier: AI mode (OpenRouter)")
        else:
            logger.info("Stance classifier: keyword fallback mode")
    except Exception as _sc_err:
        logger.warning("Stance classifier init error: %s", _sc_err)

    # Start narrative analysis loop (stance classification + evidence correlation every 15 min)
    asyncio.create_task(narrative_analyzer.start())
    logger.info("Narrative analyzer started")

    yield

    logger.info("Orthanc API shutting down")
    velocity_task.cancel()
    silence_task.cancel()
    scheduler_task.cancel()
    maritime_task.cancel()
    for task in (velocity_task, silence_task, scheduler_task, maritime_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    await narrative_engine.stop()
    await narrative_analyzer.stop()
    await sentinel_service.stop()
    await fusion_service.stop()
    await orchestrator.stop_all()
    try:
        await satellite_collector.stop()
    except Exception:
        pass


app = FastAPI(title="Orthanc API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(credentials.router)
app.include_router(sources.router)
app.include_router(feed.router)
app.include_router(alerts.router)
app.include_router(telegram_auth.router)
app.include_router(events.router)
app.include_router(entities.router)
app.include_router(dashboard.router)
app.include_router(briefs.router)
app.include_router(webhook.router)
app.include_router(layers.router)
app.include_router(finance.router)
app.include_router(search.router)
app.include_router(documents.router)
app.include_router(collaboration.router)
app.include_router(nlquery.router)
app.include_router(media.router)
app.include_router(gdelt.router)
app.include_router(investigations.router)
app.include_router(sanctions.router)
app.include_router(fusion.router)
app.include_router(cases.router)
app.include_router(oql.router)
app.include_router(maritime.router)
app.include_router(watchpoints.router)
app.include_router(narratives_router_module.router)
app.include_router(models_router)


@app.get("/")
async def root() -> dict:
    return {"status": "operational", "service": "orthanc"}

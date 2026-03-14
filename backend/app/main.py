from __future__ import annotations
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, credentials, sources, feed, alerts, events, media
from app.routers.frontlines import router as frontlines_router
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
from app.routers import graph as graph_router_module
from app.routers import health as health_router_module
from app.middleware.rate_limit import rate_limit_middleware
from app.collectors.orchestrator import orchestrator
from app.collectors.satellite_collector import satellite_collector
from app.services.brief_scheduler import brief_scheduler
from app.services.fusion_service import fusion_service
from app.services.maritime_intel_service import maritime_intel_service
from app.services.narrative_engine import narrative_engine
from app.services.narrative_analyzer import narrative_analyzer
from app.services.sentinel_service import sentinel_service
from app.services.cooccurrence_service import cooccurrence_service

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

    # OpenRouter credentials are decrypted on user login and providers are
    # registered in auth.login. At startup there is no user password/key
    # material available, so embedding falls back until a user logs in.
    logger.info("Embedding service: waiting for user login to load provider credentials")

    # Start narrative clustering engine (embeds posts + clusters into narratives every 10 min)
    await narrative_engine.start()
    logger.info("Narrative clustering engine started")

    # Start frontline snapshot scheduler (polls every 6h, stores if changed)
    from app.services.frontline_service import frontline_service
    await frontline_service.start()
    logger.info("Frontline snapshot scheduler started")

    # Stance classifier uses model_router directly; if OpenRouter/xAI are
    # registered after login it will use AI mode automatically, otherwise
    # it keeps keyword fallback behavior.
    try:
        from app.services.model_router import model_router as _mr
        if _mr._providers:
            logger.info("Stance classifier: AI-capable providers registered (%s)", ", ".join(sorted(_mr._providers.keys())))
        else:
            logger.info("Stance classifier: keyword fallback mode (no providers registered yet)")
    except Exception as _sc_err:
        logger.warning("Stance classifier init status check error: %s", _sc_err)

    # Start narrative analysis loop (stance classification + evidence correlation every 15 min)
    narrative_analyzer_task = asyncio.create_task(narrative_analyzer.start())
    logger.info("Narrative analyzer started")

    # Start entity co-occurrence service (builds relationship graph every 30 min)
    await cooccurrence_service.start()
    logger.info("Entity co-occurrence service started")


    # Load persisted task→model overrides into model_router on startup.
    # Reads the most-recently-updated override per task across all users so
    # that the singleton starts in the last-known configured state.
    try:
        from app.db import AsyncSessionLocal
        from app.models.task_model_override import TaskModelOverride
        from app.services.model_router import model_router as _mr
        from sqlalchemy import select, text as sa_text
        async with AsyncSessionLocal() as _db:
            # Latest override per task (across all users; last-write wins)
            _result = await _db.execute(
                select(TaskModelOverride).order_by(TaskModelOverride.updated_at.desc())
            )
            _rows = _result.scalars().all()
            _seen: set = set()
            for _row in _rows:
                if _row.task not in _seen:
                    _mr.set_task_model(_row.task, _row.model_id)
                    _seen.add(_row.task)
        if _seen:
            logger.info("Loaded %d persisted task model override(s) from DB", len(_seen))
        else:
            logger.info("No persisted task model overrides found — using defaults")
    except Exception as _tmo_err:
        logger.warning("Failed to load task model overrides from DB: %s", _tmo_err)

    yield

    logger.info("Orthanc API shutting down — cancelling background tasks...")
    velocity_task.cancel()
    silence_task.cancel()
    scheduler_task.cancel()
    maritime_task.cancel()
    narrative_analyzer_task.cancel()
    for task in (velocity_task, silence_task, scheduler_task, maritime_task, narrative_analyzer_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    await narrative_engine.stop()
    await narrative_analyzer.stop()
    await cooccurrence_service.stop()
    await sentinel_service.stop()
    await fusion_service.stop()
    await orchestrator.stop_all()
    try:
        await satellite_collector.stop()
    except Exception:
        pass
    logger.info("Shutdown complete")


app = FastAPI(title="Orthanc API", lifespan=lifespan)

# ── Middleware (applied in reverse order: last-added = outermost) ─────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log requests that take longer than 1 second."""
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    if duration > 1.0:
        logger.warning(
            "Slow request: %s %s took %.2fs",
            request.method,
            request.url.path,
            duration,
        )
    return response


app.middleware("http")(rate_limit_middleware)

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
app.include_router(graph_router_module.router)
app.include_router(frontlines_router)
app.include_router(health_router_module.router)


@app.get("/")
async def root() -> dict:
    return {"status": "operational", "service": "orthanc"}

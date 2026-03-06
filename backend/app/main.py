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
from app.collectors.orchestrator import orchestrator
from app.collectors.satellite_collector import satellite_collector
from app.services.brief_scheduler import brief_scheduler

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
    await orchestrator.start_firms()
    await orchestrator.start_flights()
    await orchestrator.start_market()
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

    yield

    logger.info("Orthanc API shutting down")
    velocity_task.cancel()
    silence_task.cancel()
    scheduler_task.cancel()
    for task in (velocity_task, silence_task, scheduler_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
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


@app.get("/")
async def root() -> dict:
    return {"status": "operational", "service": "orthanc"}

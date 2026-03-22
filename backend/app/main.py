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
from app.routers import agent as agent_router_module
from app.routers import api_keys as api_keys_router_module
from app.routers import scheduled_briefs as scheduled_briefs_router_module
from app.routers import digests as digests_router_module
from app.routers import metrics as metrics_router_module
from app.routers import dashboard_tabs as dashboard_tabs_router_module
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
    import signal

    # ── SIGTERM / SIGINT graceful-shutdown handler ─────────────────────────
    # Sets a flag that can be checked by the shutdown block, and schedules
    # an orderly stop via the existing lifespan teardown path.
    _shutdown_event = asyncio.Event()

    def _handle_signal(signum, frame):  # noqa: ANN001
        sig_name = signal.Signals(signum).name
        logger.info("Received %s — initiating graceful shutdown", sig_name)
        _shutdown_event.set()

    loop = asyncio.get_event_loop()
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(_sig, lambda s=_sig: _handle_signal(s, None))
        except (NotImplementedError, RuntimeError):
            # Windows / non-default loop fallback
            signal.signal(_sig, _handle_signal)

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
        await orchestrator.start_maritime_advisories()
    except Exception as exc:
        logger.warning("Maritime Advisory Collector failed to start: %s", exc)
    try:
        await orchestrator.start_official_sources()
    except Exception as exc:
        logger.warning("Official sources collector failed to start: %s", exc)
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

    # Seed Telegram Wave 1 channels for all existing users (idempotent)
    try:
        from app.services.telegram_wave1_seeder import seed_telegram_wave1
        await seed_telegram_wave1()
    except Exception as _tw1_err:
        logger.warning("Telegram Wave 1 seeder skipped (will retry on next start): %s", _tw1_err)
    logger.info("Telegram Wave 1 channels seeded")

    # Seed official/sanctions/maritime Source records with metadata (idempotent)
    try:
        from app.services.official_sources_seeder import seed_official_sources
        await seed_official_sources()
    except Exception as _off_err:
        logger.warning("Official sources seeder skipped (will retry on next start): %s", _off_err)
    logger.info("Official sources seeded")

    # OpenRouter credentials are decrypted on user login and providers are
    # registered in auth.login. At startup there is no user password/key
    # material available, so embedding falls back until a user logs in.
    logger.info("Embedding service: waiting for user login to load provider credentials")

    # Start narrative clustering engine (embeds posts + clusters into narratives every 10 min)
    await narrative_engine.start()
    logger.info("Narrative clustering engine started")

    # Start strike tracker (extracts daily strike/sortie counts every hour)
    from app.services.strike_tracker import strike_tracker
    asyncio.create_task(strike_tracker.start_daily_loop(), name="strike_tracker")
    logger.info("Strike tracker started")

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

    # Start official sanctions services (OFAC, UK FCDO, UN SC, EU FSF) — daily refresh
    try:
        from app.services.ofac_sanctions_service import ofac_sanctions_service
        await ofac_sanctions_service.start()
        logger.info("OFAC sanctions service started")
    except Exception as _ofac_err:
        logger.warning("OFAC sanctions service failed to start: %s", _ofac_err)

    try:
        from app.services.uk_sanctions_service import uk_sanctions_service
        await uk_sanctions_service.start()
        logger.info("UK FCDO sanctions service started")
    except Exception as _uk_err:
        logger.warning("UK sanctions service failed to start: %s", _uk_err)

    try:
        from app.services.un_sanctions_service import un_sanctions_service
        await un_sanctions_service.start()
        logger.info("UN SC sanctions service started")
    except Exception as _un_err:
        logger.warning("UN SC sanctions service failed to start: %s", _un_err)

    try:
        from app.services.eu_sanctions_service import eu_sanctions_service
        await eu_sanctions_service.start()
        logger.info("EU FSF sanctions service started")
    except Exception as _eu_err:
        logger.warning("EU FSF sanctions service failed to start: %s", _eu_err)


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
    # Stop sanctions services
    for _svc_name, _svc_mod, _svc_attr in [
        ("OFAC", "app.services.ofac_sanctions_service", "ofac_sanctions_service"),
        ("UK", "app.services.uk_sanctions_service", "uk_sanctions_service"),
        ("UN SC", "app.services.un_sanctions_service", "un_sanctions_service"),
        ("EU FSF", "app.services.eu_sanctions_service", "eu_sanctions_service"),
    ]:
        try:
            import importlib
            _mod = importlib.import_module(_svc_mod)
            _svc = getattr(_mod, _svc_attr, None)
            if _svc and hasattr(_svc, "stop"):
                await _svc.stop()
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
    """Log all requests as structured JSON at INFO level; skip health-check noise."""
    import json

    # Skip health/ping endpoints to reduce log noise
    skip_paths = {"/", "/health", "/health/", "/api/health"}
    path = request.url.path

    start = time.time()
    response = await call_next(request)
    duration_ms = int((time.time() - start) * 1000)

    if path not in skip_paths:
        # Extract authenticated user_id from JWT if present (best-effort, non-blocking)
        user_id: str | None = None
        try:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                from jose import jwt as _jwt
                from app.config import settings as _settings
                payload = _jwt.decode(
                    auth_header[7:],
                    _settings.JWT_SECRET,
                    algorithms=[_settings.JWT_ALGORITHM],
                    options={"verify_exp": False},
                )
                user_id = payload.get("sub")
        except Exception:
            pass

        log_record = {
            "method": request.method,
            "path": path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }
        if user_id:
            log_record["user_id"] = user_id

        if duration_ms > 1000:
            logger.warning(json.dumps(log_record))
        else:
            logger.info(json.dumps(log_record))

    return response


app.middleware("http")(rate_limit_middleware)


# ── TASK-89: API key scope enforcement ────────────────────────────────────────
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@app.middleware("http")
async def api_key_scope_middleware(request: Request, call_next):
    """Reject write requests from read_only API keys.

    This middleware runs AFTER authentication (which stamps request.state.api_key_scope).
    JWT-authenticated requests (request.state.jwt_authenticated=True) bypass this check.
    """
    if request.method in _WRITE_METHODS:
        api_key_scope = getattr(request.state, "api_key_scope", None)
        if api_key_scope == "read_only":
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "This API key is read-only and cannot perform write operations."},
            )
    return await call_next(request)

# ── Unversioned routes (legacy — kept for backwards compatibility) ─────────────
# Clients should migrate to /api/v1/* paths.

_ALL_ROUTERS = [
    auth.router,
    credentials.router,
    sources.router,
    feed.router,
    alerts.router,
    telegram_auth.router,
    events.router,
    entities.router,
    dashboard.router,
    briefs.router,
    webhook.router,
    layers.router,
    finance.router,
    search.router,
    documents.router,
    collaboration.router,
    nlquery.router,
    media.router,
    gdelt.router,
    investigations.router,
    sanctions.router,
    fusion.router,
    cases.router,
    oql.router,
    maritime.router,
    watchpoints.router,
    narratives_router_module.router,
    models_router,
    graph_router_module.router,
    frontlines_router,
    health_router_module.router,
    agent_router_module.router,
    api_keys_router_module.router,
    scheduled_briefs_router_module.router,
    digests_router_module.router,
    metrics_router_module.router,
    dashboard_tabs_router_module.router,
]

for _r in _ALL_ROUTERS:
    app.include_router(_r)

# ── /api/v1 versioned routes ────────────────────────────────────────────────
# All routers are also mounted under /api/v1 prefix.
# New clients should use these paths.
from fastapi import APIRouter as _APIRouter

_v1 = _APIRouter(prefix="/api/v1")
for _r in _ALL_ROUTERS:
    _v1.include_router(_r)
app.include_router(_v1)


# ── Deprecation warning middleware for unversioned routes ───────────────────
@app.middleware("http")
async def _deprecation_header(request: Request, call_next):
    """Add Deprecation header on unversioned API routes to encourage migration."""
    path = request.url.path
    # Only flag unversioned API paths (not /api/v1/*, not /ws/*, not /, not /health)
    is_unversioned_api = (
        not path.startswith("/api/")
        and not path.startswith("/ws/")
        and path not in ("/", "/health", "/health/")
        and "/" in path[1:]  # has at least one sub-path component
    )
    response = await call_next(request)
    if is_unversioned_api:
        response.headers["Deprecation"] = "true"
        response.headers["Link"] = f'</api/v1{path}>; rel="successor-version"'
    return response


@app.get("/")
async def root() -> dict:
    return {"status": "operational", "service": "orthanc"}

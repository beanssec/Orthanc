"""Prometheus-compatible metrics endpoint.

Returns plain-text metrics in the Prometheus exposition format.
No prometheus_client dependency — hand-crafted text output.

Metrics exposed:
  orthanc_posts_total             - total row count in posts table
  orthanc_sources_active          - count of enabled/active sources
  orthanc_narratives_active       - count of active narratives
  orthanc_llm_calls_total         - total LLM calls logged in llm_usage table
  orthanc_collector_errors_total  - sum of error_count across all sources
  orthanc_db_pool_size            - SQLAlchemy pool size (if accessible)
  orthanc_uptime_seconds          - process uptime in seconds
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["metrics"])

# Process start time for uptime calculation
_PROCESS_START = time.time()


def _prom_gauge(name: str, value: float, help_text: str = "", labels: Optional[dict] = None) -> str:
    """Format a single Prometheus gauge metric."""
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")
    return "\n".join(lines)


def _prom_counter(name: str, value: float, help_text: str = "", labels: Optional[dict] = None) -> str:
    """Format a single Prometheus counter metric."""
    lines = []
    if help_text:
        lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} counter")
    if labels:
        label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
        lines.append(f"{name}{{{label_str}}} {value}")
    else:
        lines.append(f"{name} {value}")
    return "\n".join(lines)


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    """Prometheus text format metrics for Orthanc.

    Scrape with: prometheus.yml scrape_configs target pointing at this endpoint.
    No authentication required (suitable for internal monitoring networks).
    """
    from app.db import AsyncSessionLocal
    from sqlalchemy import text

    metrics: list[str] = []

    # ── uptime ────────────────────────────────────────────────────────────────
    uptime = time.time() - _PROCESS_START
    metrics.append(_prom_gauge(
        "orthanc_uptime_seconds",
        round(uptime, 2),
        "Process uptime in seconds",
    ))

    async with AsyncSessionLocal() as db:

        # ── posts total ───────────────────────────────────────────────────────
        try:
            result = await db.execute(text("SELECT COUNT(*) FROM posts"))
            posts_total = result.scalar() or 0
        except Exception:
            posts_total = -1
        metrics.append(_prom_counter(
            "orthanc_posts_total",
            posts_total,
            "Total number of posts ingested",
        ))

        # ── active sources ────────────────────────────────────────────────────
        try:
            result = await db.execute(
                text("SELECT COUNT(*) FROM sources WHERE enabled = true")
            )
            sources_active = result.scalar() or 0
        except Exception:
            sources_active = -1
        metrics.append(_prom_gauge(
            "orthanc_sources_active",
            sources_active,
            "Number of enabled (active) sources",
        ))

        # ── active narratives ─────────────────────────────────────────────────
        try:
            result = await db.execute(
                text("SELECT COUNT(*) FROM narratives WHERE active = true")
            )
            narratives_active = result.scalar() or 0
        except Exception:
            # Table may not exist or column name differs — fall back gracefully
            try:
                result = await db.execute(text("SELECT COUNT(*) FROM narratives"))
                narratives_active = result.scalar() or 0
            except Exception:
                narratives_active = -1
        metrics.append(_prom_gauge(
            "orthanc_narratives_active",
            narratives_active,
            "Number of active narratives",
        ))

        # ── LLM calls total ───────────────────────────────────────────────────
        try:
            result = await db.execute(text("SELECT COUNT(*) FROM llm_usage"))
            llm_calls_total = result.scalar() or 0
        except Exception:
            llm_calls_total = -1
        metrics.append(_prom_counter(
            "orthanc_llm_calls_total",
            llm_calls_total,
            "Total LLM API calls recorded in llm_usage table",
        ))

        # ── collector errors total ────────────────────────────────────────────
        try:
            result = await db.execute(
                text("SELECT COALESCE(SUM(error_count), 0) FROM sources")
            )
            collector_errors = result.scalar() or 0
        except Exception:
            collector_errors = -1
        metrics.append(_prom_counter(
            "orthanc_collector_errors_total",
            collector_errors,
            "Sum of error_count across all sources",
        ))

        # ── DB pool size ──────────────────────────────────────────────────────
        try:
            from app.db import engine  # type: ignore[attr-defined]
            pool = engine.pool
            pool_size = pool.size()
        except Exception:
            pool_size = -1
        metrics.append(_prom_gauge(
            "orthanc_db_pool_size",
            pool_size,
            "SQLAlchemy connection pool size (-1 = not accessible)",
        ))

    # ── embedding cache stats (bonus) ─────────────────────────────────────────
    try:
        from app.services.embedding_cache import embedding_cache
        stats = embedding_cache.stats()
        metrics.append(_prom_gauge(
            "orthanc_embedding_cache_size",
            stats["size"],
            "Current number of entries in embedding LRU cache",
        ))
        metrics.append(_prom_counter(
            "orthanc_embedding_cache_hits_total",
            stats["hits"],
            "Total embedding cache hits",
        ))
        metrics.append(_prom_counter(
            "orthanc_embedding_cache_misses_total",
            stats["misses"],
            "Total embedding cache misses",
        ))
    except Exception:
        pass

    # ── provider health (bonus) ───────────────────────────────────────────────
    try:
        from app.services.model_router import model_router
        for pname, health in model_router.provider_health_status().items():
            metrics.append(_prom_gauge(
                "orthanc_provider_healthy",
                1 if health["healthy"] else 0,
                "1 if provider is healthy, 0 if in cooldown",
                labels={"provider": pname},
            ))
            metrics.append(_prom_gauge(
                "orthanc_provider_consecutive_failures",
                health["failures"],
                "Consecutive failure count for provider",
                labels={"provider": pname},
            ))
    except Exception:
        pass

    return "\n\n".join(metrics) + "\n"

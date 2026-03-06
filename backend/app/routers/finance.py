"""Financial intelligence API router.

Endpoints:
  Portfolio  : GET/POST/PUT/DELETE /finance/portfolio
  Quotes     : GET /finance/quotes, /finance/quotes/{ticker}
  Watchlist  : GET /finance/watchlist
  Cashtags   : GET /finance/cashtags, /finance/cashtags/{ticker}
  Signals    : GET /finance/signals, POST /finance/signals/scan
  Mappings   : GET/POST/DELETE /finance/mappings
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.middleware.auth import get_current_user
from app.models import User
from app.models.financial import Holding, Quote, Signal
from app.models.post import Post
from app.services.entity_ticker_service import entity_ticker_service
from app.services.opportunity_scanner import opportunity_scanner

logger = logging.getLogger("orthanc.routers.finance")

router = APIRouter(prefix="/finance", tags=["finance"])

# ─────────────────────────────────────────────────────────────────────────────
# Default watchlist tickers (always shown on /watchlist)
# ─────────────────────────────────────────────────────────────────────────────
WATCHLIST_TICKERS = {
    # Indices
    "GSPC": "INDEX",
    "VIX": "INDEX",
    "AXJO": "INDEX",
    # Commodities
    "CL": "COMMODITY",
    "BZ": "COMMODITY",
    "GC": "COMMODITY",
    "NG": "COMMODITY",
    "SI": "COMMODITY",
    "HG": "COMMODITY",
    "ZW": "COMMODITY",
    # Forex
    "AUDUSD": "FOREX",
    "EURUSD": "FOREX",
    "USDJPY": "FOREX",
    # Crypto
    "BTC": "CRYPTO",
    "ETH": "CRYPTO",
}

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ─────────────────────────────────────────────────────────────────────────────


class HoldingCreate(BaseModel):
    ticker: str
    exchange: str = "NYSE"
    quantity: float
    avg_cost: Optional[float] = None
    currency: Optional[str] = None
    notes: Optional[str] = None


class HoldingUpdate(BaseModel):
    quantity: Optional[float] = None
    avg_cost: Optional[float] = None
    currency: Optional[str] = None
    notes: Optional[str] = None


class MappingCreate(BaseModel):
    entity_name: str
    entity_type: Optional[str] = None
    ticker: str
    exchange: str = "NYSE"
    relationship: Optional[str] = None
    confidence: float = 0.7


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _exchange_currency(exchange: str) -> str:
    return "AUD" if exchange == "ASX" else "USD"


async def _latest_quote(db: AsyncSession, ticker: str, exchange: str) -> Optional[Quote]:
    """Fetch the most recent cached quote for a ticker."""
    result = await db.execute(
        select(Quote)
        .where(Quote.ticker == ticker, Quote.exchange == exchange)
        .order_by(Quote.fetched_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _holding_with_quote(holding: Holding, quote: Optional[Quote]) -> dict:
    """Build holding response dict with P&L calculations."""
    avg_cost = holding.avg_cost
    currency = holding.currency or _exchange_currency(holding.exchange or "NYSE")

    current_price = quote.price if quote else None
    change_pct = quote.change_pct if quote else None

    if current_price is not None and avg_cost is not None and holding.quantity:
        market_value = current_price * holding.quantity
        cost_basis = avg_cost * holding.quantity
        profit_loss = market_value - cost_basis
        profit_loss_pct = (profit_loss / cost_basis * 100) if cost_basis else None
    else:
        market_value = None
        profit_loss = None
        profit_loss_pct = None

    return {
        "id": str(holding.id),
        "ticker": holding.ticker,
        "exchange": holding.exchange,
        "quantity": holding.quantity,
        "avg_cost": avg_cost,
        "current_price": current_price,
        "change_pct": change_pct,
        "market_value": round(market_value, 2) if market_value is not None else None,
        "profit_loss": round(profit_loss, 2) if profit_loss is not None else None,
        "profit_loss_pct": round(profit_loss_pct, 2) if profit_loss_pct is not None else None,
        "currency": currency,
        "notes": holding.notes,
        "created_at": holding.created_at.isoformat() if holding.created_at else None,
        "updated_at": holding.updated_at.isoformat() if holding.updated_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/portfolio")
async def get_portfolio(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """List all holdings with current quotes and P&L."""
    result = await db.execute(
        select(Holding)
        .where(Holding.user_id == current_user.id)
        .order_by(Holding.created_at)
    )
    holdings = result.scalars().all()

    enriched = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings:
        quote = await _latest_quote(db, h.ticker, h.exchange or "NYSE")
        item = _holding_with_quote(h, quote)
        enriched.append(item)

        if item["market_value"] is not None:
            total_value += item["market_value"]
        if h.avg_cost and h.quantity:
            total_cost += h.avg_cost * h.quantity

    total_profit_loss = total_value - total_cost if total_cost else None
    total_profit_loss_pct = (
        (total_profit_loss / total_cost * 100) if total_cost and total_profit_loss is not None else None
    )

    return {
        "holdings": enriched,
        "total_value": round(total_value, 2),
        "total_profit_loss": round(total_profit_loss, 2) if total_profit_loss is not None else None,
        "total_profit_loss_pct": round(total_profit_loss_pct, 2) if total_profit_loss_pct is not None else None,
    }


@router.post("/portfolio", status_code=status.HTTP_201_CREATED)
async def add_holding(
    data: HoldingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Add a holding to the portfolio."""
    # Check for duplicate
    existing = await db.execute(
        select(Holding).where(
            Holding.user_id == current_user.id,
            Holding.ticker == data.ticker.upper(),
            Holding.exchange == data.exchange.upper(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Holding {data.ticker.upper()} ({data.exchange.upper()}) already exists. Use PUT to update.",
        )

    currency = data.currency or _exchange_currency(data.exchange)
    holding = Holding(
        user_id=current_user.id,
        ticker=data.ticker.upper(),
        exchange=data.exchange.upper(),
        quantity=data.quantity,
        avg_cost=data.avg_cost,
        currency=currency,
        notes=data.notes,
    )
    db.add(holding)
    await db.commit()
    await db.refresh(holding)

    # Trigger a market data refresh in the background (non-blocking)
    try:
        from app.collectors.market_collector import market_collector
        import asyncio
        asyncio.create_task(market_collector.force_refresh())
    except Exception:
        pass  # Non-critical

    quote = await _latest_quote(db, holding.ticker, holding.exchange or "NYSE")
    logger.info("Added holding: %s %s for user %s", holding.ticker, holding.exchange, current_user.id)
    return _holding_with_quote(holding, quote)


@router.put("/portfolio/{holding_id}")
async def update_holding(
    holding_id: str,
    data: HoldingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Update an existing holding."""
    result = await db.execute(
        select(Holding).where(
            Holding.id == uuid.UUID(holding_id),
            Holding.user_id == current_user.id,
        )
    )
    holding = result.scalar_one_or_none()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    if data.quantity is not None:
        holding.quantity = data.quantity
    if data.avg_cost is not None:
        holding.avg_cost = data.avg_cost
    if data.currency is not None:
        holding.currency = data.currency
    if data.notes is not None:
        holding.notes = data.notes
    holding.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(holding)

    quote = await _latest_quote(db, holding.ticker, holding.exchange or "NYSE")
    return _holding_with_quote(holding, quote)


@router.delete("/portfolio/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(
    holding_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Remove a holding from the portfolio."""
    result = await db.execute(
        select(Holding).where(
            Holding.id == uuid.UUID(holding_id),
            Holding.user_id == current_user.id,
        )
    )
    holding = result.scalar_one_or_none()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    await db.delete(holding)
    await db.commit()
    logger.info("Deleted holding %s for user %s", holding_id, current_user.id)


# ─────────────────────────────────────────────────────────────────────────────
# Market data endpoints
# ─────────────────────────────────────────────────────────────────────────────


def _quote_dict(q: Quote) -> dict:
    return {
        "ticker": q.ticker,
        "exchange": q.exchange,
        "price": q.price,
        "change_pct": q.change_pct,
        "volume": q.volume,
        "market_cap": q.market_cap,
        "currency": q.currency,
        "fetched_at": q.fetched_at.isoformat() if q.fetched_at else None,
    }


@router.get("/quotes")
async def get_all_quotes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Return the most recent quote for every tracked ticker."""
    # Subquery: max fetched_at per (ticker, exchange)
    from sqlalchemy import func

    subq = (
        select(
            Quote.ticker,
            Quote.exchange,
            func.max(Quote.fetched_at).label("max_fetched"),
        )
        .group_by(Quote.ticker, Quote.exchange)
        .subquery()
    )
    result = await db.execute(
        select(Quote).join(
            subq,
            (Quote.ticker == subq.c.ticker)
            & (Quote.exchange == subq.c.exchange)
            & (Quote.fetched_at == subq.c.max_fetched),
        )
    )
    quotes = result.scalars().all()
    return [_quote_dict(q) for q in quotes]


@router.get("/quotes/{ticker}")
async def get_quote(
    ticker: str,
    exchange: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Get the most recent quote for a specific ticker."""
    stmt = select(Quote).where(Quote.ticker == ticker.upper())
    if exchange:
        stmt = stmt.where(Quote.exchange == exchange.upper())
    stmt = stmt.order_by(Quote.fetched_at.desc()).limit(1)

    result = await db.execute(stmt)
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail=f"No quote found for {ticker}")
    return _quote_dict(q)


@router.get("/watchlist")
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return default market overview — indices, commodities, forex, crypto."""
    from sqlalchemy import func

    subq = (
        select(
            Quote.ticker,
            Quote.exchange,
            func.max(Quote.fetched_at).label("max_fetched"),
        )
        .where(Quote.ticker.in_(list(WATCHLIST_TICKERS.keys())))
        .group_by(Quote.ticker, Quote.exchange)
        .subquery()
    )
    result = await db.execute(
        select(Quote).join(
            subq,
            (Quote.ticker == subq.c.ticker)
            & (Quote.exchange == subq.c.exchange)
            & (Quote.fetched_at == subq.c.max_fetched),
        )
    )
    quotes = result.scalars().all()

    # Group by category
    categories: dict[str, list[dict]] = {
        "indices": [],
        "commodities": [],
        "forex": [],
        "crypto": [],
    }
    cat_map = {
        "INDEX": "indices",
        "COMMODITY": "commodities",
        "FOREX": "forex",
        "CRYPTO": "crypto",
    }
    for q in quotes:
        cat = cat_map.get(q.exchange or "", "indices")
        categories[cat].append(_quote_dict(q))

    return categories


# ─────────────────────────────────────────────────────────────────────────────
# Cashtag endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/cashtags/{ticker}")
async def get_cashtag_posts(
    ticker: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Recent cashtag posts for a specific ticker."""
    result = await db.execute(
        select(Post)
        .where(
            Post.source_type == "cashtag",
            Post.content.ilike(f"%${ticker.upper()}%"),
        )
        .order_by(Post.timestamp.desc())
        .limit(limit)
    )
    posts = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "author": p.author,
            "content": p.content,
            "timestamp": p.timestamp.isoformat() if p.timestamp else None,
            "sentiment": (p.raw_json or {}).get("sentiment", "neutral"),
            "cashtags": (p.raw_json or {}).get("cashtags", []),
        }
        for p in posts
    ]


@router.get("/cashtags")
async def get_all_cashtag_posts(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """Recent cashtag posts across all tracked portfolio tickers."""
    # Get user's tickers
    holdings_result = await db.execute(
        select(Holding).where(Holding.user_id == current_user.id)
    )
    holdings = holdings_result.scalars().all()

    if not holdings:
        return []

    result = await db.execute(
        select(Post)
        .where(Post.source_type == "cashtag")
        .order_by(Post.timestamp.desc())
        .limit(limit)
    )
    posts = result.scalars().all()

    portfolio_tickers = {h.ticker.upper() for h in holdings}

    # Filter to posts that mention any portfolio ticker
    filtered = []
    for p in posts:
        cashtags_in_post = (p.raw_json or {}).get("cashtags", [])
        if any(t.upper() in portfolio_tickers for t in cashtags_in_post):
            filtered.append(
                {
                    "id": str(p.id),
                    "author": p.author,
                    "content": p.content,
                    "timestamp": p.timestamp.isoformat() if p.timestamp else None,
                    "sentiment": (p.raw_json or {}).get("sentiment", "neutral"),
                    "cashtags": cashtags_in_post,
                }
            )

    return filtered


# ─────────────────────────────────────────────────────────────────────────────
# Signal endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/signals")
async def get_signals(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List AI-generated financial signals for the current user, newest first."""
    result = await db.execute(
        select(Signal)
        .where(Signal.user_id == current_user.id)
        .order_by(Signal.generated_at.desc())
        .limit(limit)
    )
    signals = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "signal_type": s.signal_type,
            "severity": s.severity,
            "title": s.title,
            "summary": s.summary,
            "affected_tickers": _parse_json_field(s.affected_tickers),
            "trigger_entities": _parse_json_field(s.trigger_entities),
            "trigger_post_count": s.trigger_post_count,
            "portfolio_impact": s.portfolio_impact,
            "generated_at": s.generated_at.isoformat() if s.generated_at else None,
        }
        for s in signals
    ]


@router.post("/signals/scan")
async def trigger_scan(
    model_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Trigger an AI opportunity scan for the current user."""
    logger.info("Triggering opportunity scan for user %s", current_user.id)
    try:
        signals = await opportunity_scanner.scan(str(current_user.id), model_id=model_id)
    except Exception:
        logger.exception("Opportunity scan failed for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="Scan failed — check server logs")

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "signal_count": len(signals),
        "signals": signals,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entity-ticker mapping endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/mappings")
async def list_mappings(
    entity_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """List entity-ticker mappings."""
    return await entity_ticker_service.list_mappings(entity_name)


@router.post("/mappings", status_code=status.HTTP_201_CREATED)
async def add_mapping(
    data: MappingCreate,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Add a custom entity-ticker mapping."""
    return await entity_ticker_service.add_mapping(
        entity_name=data.entity_name,
        entity_type=data.entity_type,
        ticker=data.ticker.upper(),
        exchange=data.exchange.upper(),
        relationship=data.relationship,
        confidence=data.confidence,
    )


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mapping(
    mapping_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete an entity-ticker mapping."""
    deleted = await entity_ticker_service.delete_mapping(mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mapping not found")


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────


def _parse_json_field(val: Optional[str]) -> list:
    """Safely parse a JSON text field into a list."""
    if not val:
        return []
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else [parsed]
    except (json.JSONDecodeError, TypeError):
        return [val]

"""Market data collector — polls Yahoo Finance (yfinance) for tracked tickers.

yfinance is a synchronous library; all calls are run in a thread executor.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, time as dtime

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.financial import Holding, Quote

logger = logging.getLogger("orthanc.collectors.market")

# Default watchlist — always tracked regardless of user holdings
DEFAULT_TICKERS: dict[str, tuple[str, str]] = {
    # Indices
    "^GSPC": ("INDEX", "USD"),    # S&P 500
    "^VIX": ("INDEX", "USD"),     # VIX Fear Index
    "^AXJO": ("INDEX", "AUD"),    # ASX 200
    # Commodities
    "CL=F": ("COMMODITY", "USD"),  # WTI Crude Oil
    "BZ=F": ("COMMODITY", "USD"),  # Brent Crude
    "GC=F": ("COMMODITY", "USD"),  # Gold
    "NG=F": ("COMMODITY", "USD"),  # Natural Gas
    "SI=F": ("COMMODITY", "USD"),  # Silver
    "HG=F": ("COMMODITY", "USD"),  # Copper
    "ZW=F": ("COMMODITY", "USD"),  # Wheat
    # Forex
    "AUDUSD=X": ("FOREX", "USD"),  # AUD/USD
    "EURUSD=X": ("FOREX", "USD"),  # EUR/USD
    "USDJPY=X": ("FOREX", "USD"),  # USD/JPY
    # Crypto (24/7)
    "BTC-USD": ("CRYPTO", "USD"),
    "ETH-USD": ("CRYPTO", "USD"),
}

POLL_INTERVAL_MARKET_HOURS = 300    # 5 min during trading hours
POLL_INTERVAL_OFF_HOURS = 3600      # 1 hour off-hours / weekends


def _is_market_hours() -> bool:
    """Rough check for US/ASX market hours (UTC). Returns True during likely trading times."""
    now_utc = datetime.now(timezone.utc)
    weekday = now_utc.weekday()  # 0=Mon, 6=Sun
    if weekday >= 5:
        return False  # Weekend
    hour = now_utc.hour
    # US market: roughly 13:30–20:00 UTC | ASX: roughly 00:00–06:00 UTC
    return (0 <= hour < 7) or (13 <= hour < 21)


def _build_ticker_dict(user_tickers: list[tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """Merge default watchlist with user holdings, converting to Yahoo Finance format."""
    all_tickers: dict[str, tuple[str, str]] = dict(DEFAULT_TICKERS)
    for ticker, exchange in user_tickers:
        if exchange == "ASX":
            yf_sym = f"{ticker}.AX"
            all_tickers[yf_sym] = ("ASX", "AUD")
        elif exchange == "CRYPTO":
            yf_sym = f"{ticker}-USD"
            all_tickers[yf_sym] = ("CRYPTO", "USD")
        elif exchange == "INDEX":
            all_tickers[ticker] = ("INDEX", "USD")
        elif exchange == "COMMODITY":
            # Already stored as clean name in holdings; map back to YF format
            all_tickers[ticker] = ("COMMODITY", "USD")
        else:
            all_tickers[ticker] = (exchange or "NYSE", "USD")
    return all_tickers


def _fetch_yfinance(ticker_str: str) -> object:
    """Synchronous yfinance fetch — runs in executor."""
    import yfinance as yf  # noqa: PLC0415 — deferred to avoid startup cost
    return yf.Tickers(ticker_str)


def _get_fast_info(ticker_obj: object) -> object:
    """Synchronous fast_info fetch — runs in executor."""
    return ticker_obj.fast_info  # type: ignore[attr-defined]


class MarketCollector:
    """Polls market data for all tracked tickers and caches in the quotes table."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._task and not self._task.done():
            logger.warning("MarketCollector already running")
            return
        logger.info("Starting MarketCollector")
        self._task = asyncio.create_task(self._poll_loop(), name="market_collector")

    async def stop(self) -> None:
        """Cancel the polling task."""
        if self._task and not self._task.done():
            logger.info("Stopping MarketCollector")
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _poll_loop(self) -> None:
        """Main polling loop — adaptive interval based on market hours."""
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("MarketCollector poll error")

            interval = POLL_INTERVAL_MARKET_HOURS if _is_market_hours() else POLL_INTERVAL_OFF_HOURS
            logger.debug("MarketCollector sleeping %ds", interval)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    async def _poll_once(self) -> None:
        """Fetch quotes for all tickers and upsert into the quotes table."""
        logger.info("MarketCollector: fetching quotes")

        # Grab user tickers from holdings
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Holding.ticker, Holding.exchange).distinct()
                )
                user_tickers: list[tuple[str, str]] = result.all()  # type: ignore[assignment]
        except Exception:
            logger.exception("MarketCollector: failed to query holdings")
            user_tickers = []

        all_tickers = _build_ticker_dict(user_tickers)
        ticker_str = " ".join(all_tickers.keys())

        loop = asyncio.get_event_loop()

        try:
            data = await loop.run_in_executor(None, _fetch_yfinance, ticker_str)
        except Exception:
            logger.exception("MarketCollector: yfinance.Tickers() failed")
            return

        now = datetime.now(timezone.utc)
        inserted = 0

        async with AsyncSessionLocal() as session:
            for symbol, (exchange, currency) in all_tickers.items():
                try:
                    ticker_obj = data.tickers.get(symbol)  # type: ignore[attr-defined]
                    if not ticker_obj:
                        logger.debug("No ticker object for %s", symbol)
                        continue

                    info = await loop.run_in_executor(None, _get_fast_info, ticker_obj)

                    price = getattr(info, "last_price", None)
                    if price is None:
                        logger.debug("No price for %s — market likely closed", symbol)
                        continue

                    # Calculate day change % from previous close
                    prev_close = getattr(info, "previous_close", None)
                    if price is not None and prev_close:
                        change_pct_val: float | None = (float(price) - float(prev_close)) / float(prev_close) * 100.0
                    else:
                        # Fallback: try fast_info day_change attribute (absolute, not pct)
                        raw_change = getattr(info, "day_change", None)
                        if raw_change is not None and prev_close:
                            change_pct_val = float(raw_change) / float(prev_close) * 100.0
                        else:
                            change_pct_val = None

                    # Normalise symbol back to clean ticker
                    clean = (
                        symbol
                        .replace(".AX", "")
                        .replace("-USD", "")
                        .replace("=X", "")
                        .replace("=F", "")
                        .lstrip("^")
                    )

                    quote = Quote(
                        ticker=clean,
                        exchange=exchange,
                        price=float(price),
                        change_pct=change_pct_val,
                        volume=_safe_int(getattr(info, "last_volume", None)),
                        market_cap=_safe_int(getattr(info, "market_cap", None)),
                        currency=currency,
                        fetched_at=now,
                    )
                    session.add(quote)
                    inserted += 1

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("MarketCollector: failed to fetch %s: %s", symbol, e)

            await session.commit()

        logger.info("MarketCollector: upserted %d quotes", inserted)

    async def force_refresh(self) -> None:
        """Trigger an immediate poll (e.g. when user adds a holding)."""
        await self._poll_once()


def _safe_float(val: object) -> float | None:
    try:
        return float(val) if val is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _safe_int(val: object) -> int | None:
    try:
        return int(val) if val is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# Module-level singleton
market_collector = MarketCollector()

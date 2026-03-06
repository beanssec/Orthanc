from __future__ import annotations

import logging

from sqlalchemy import select

from app.db import AsyncSessionLocal
from app.models.source import Source
from app.services.collector_manager import collector_manager
from .rss_collector import RSSCollector
from .x_collector import XCollector
from .shodan_collector import ShodanCollector
from .discord_collector import DiscordCollector
from .reddit_collector import RedditCollector
from .firms_collector import FIRMSCollector
from .flight_collector import FlightCollector, flight_collector
from .ais_collector import ais_collector
from .market_collector import market_collector
from .cashtag_collector import cashtag_collector
from .telegram_collector import TelegramCollector
from .acled_collector import acled_collector

logger = logging.getLogger("orthanc.collectors.orchestrator")


class CollectorOrchestrator:
    """Manages lifecycle of all collector instances."""

    def __init__(self):
        self._rss_collector = RSSCollector()
        self._reddit_collector = RedditCollector()
        self._firms_collector = FIRMSCollector()
        self._flight_collector = flight_collector  # module-level singleton
        self._market_collector = market_collector  # module-level singleton
        self._cashtag_collector = cashtag_collector  # module-level singleton
        self._x_collectors: dict[str, XCollector] = {}       # user_id -> XCollector
        self._shodan_collectors: dict[str, ShodanCollector] = {}  # user_id -> ShodanCollector
        self._discord_collectors: dict[str, DiscordCollector] = {}  # user_id -> DiscordCollector
        self._telegram_collectors: dict[str, TelegramCollector] = {}  # user_id -> TelegramCollector

    async def start_rss(self) -> None:
        """Start RSS collector for all enabled RSS sources (no auth needed)."""
        logger.info("Querying enabled RSS sources")
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Source).where(Source.type == "rss", Source.enabled.is_(True))
                )
                sources = result.scalars().all()

            logger.info("Found %d enabled RSS sources", len(sources))
            await self._rss_collector.start(sources)
        except Exception:
            logger.exception("Failed to start RSS collector")

    async def start_firms(self) -> None:
        """Start NASA FIRMS thermal anomaly collector (no auth needed)."""
        logger.info("Starting FIRMS thermal collector")
        try:
            await self._firms_collector.start()
        except Exception:
            logger.exception("Failed to start FIRMS collector")

    async def start_flights(self) -> None:
        """Start OpenSky flight tracking collector (no auth needed)."""
        logger.info("Starting flight tracking collector")
        try:
            await self._flight_collector.start()
        except Exception:
            logger.exception("Failed to start flight collector")

    async def start_ais(self, api_key: str) -> None:
        """Start AIS ship tracking collector (requires aisstream.io API key)."""
        logger.info("Starting AIS ship tracking collector")
        try:
            await ais_collector.start(api_key)
        except Exception:
            logger.exception("Failed to start AIS collector")

    async def start_market(self) -> None:
        """Start the market data collector (no auth needed — uses Yahoo Finance)."""
        logger.info("Starting market data collector")
        try:
            await self._market_collector.start()
        except Exception:
            logger.exception("Failed to start market collector")

    async def start_reddit(self) -> None:
        """Start Reddit collector for all enabled Reddit sources (no auth needed)."""
        logger.info("Querying enabled Reddit sources")
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Source).where(Source.type == "reddit", Source.enabled.is_(True))
                )
                sources = result.scalars().all()

            logger.info("Found %d enabled Reddit sources", len(sources))
            if sources:
                await self._reddit_collector.start(sources)
        except Exception:
            logger.exception("Failed to start Reddit collector")

    async def start_user_collectors(self, user_id: str) -> None:
        """Called on user login — start their X, Shodan, and Discord collectors."""
        logger.info("Starting collectors for user %s", user_id)

        # --- X collector ---
        x_keys = await collector_manager.get_keys(user_id, "x")
        if x_keys:
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Source).where(
                            Source.user_id == user_id,
                            Source.type == "x",
                            Source.enabled.is_(True),
                        )
                    )
                    x_sources = result.scalars().all()

                if x_sources:
                    logger.info("Found %d enabled X sources for user %s", len(x_sources), user_id)
                    # Stop any existing X collector for this user before re-starting
                    existing_x = self._x_collectors.pop(user_id, None)
                    if existing_x:
                        await existing_x.stop()
                    collector = XCollector()
                    self._x_collectors[user_id] = collector
                    await collector.start(user_id, x_sources)
                else:
                    logger.info("No enabled X sources for user %s", user_id)
            except Exception:
                logger.exception("Failed to start X collectors for user %s", user_id)
        else:
            logger.info("No X keys for user %s — X collector not started", user_id)

        # --- Shodan collector ---
        shodan_keys = await collector_manager.get_keys(user_id, "shodan")
        if shodan_keys:
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Source).where(
                            Source.user_id == user_id,
                            Source.type == "shodan",
                            Source.enabled.is_(True),
                        )
                    )
                    shodan_sources = result.scalars().all()

                if shodan_sources:
                    logger.info("Found %d enabled Shodan sources for user %s", len(shodan_sources), user_id)
                    existing_shodan = self._shodan_collectors.pop(user_id, None)
                    if existing_shodan:
                        await existing_shodan.stop()
                    shodan_collector = ShodanCollector()
                    self._shodan_collectors[user_id] = shodan_collector
                    await shodan_collector.start(user_id, shodan_sources)
                else:
                    logger.info("No enabled Shodan sources for user %s", user_id)
            except Exception:
                logger.exception("Failed to start Shodan collectors for user %s", user_id)
        else:
            logger.info("No Shodan keys for user %s — Shodan collector not started", user_id)

        # --- Discord collector ---
        discord_keys = await collector_manager.get_keys(user_id, "discord")
        if discord_keys:
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Source).where(
                            Source.user_id == user_id,
                            Source.type == "discord",
                            Source.enabled.is_(True),
                        )
                    )
                    discord_sources = result.scalars().all()

                if discord_sources:
                    logger.info("Found %d enabled Discord sources for user %s", len(discord_sources), user_id)
                    existing_discord = self._discord_collectors.pop(user_id, None)
                    if existing_discord:
                        await existing_discord.stop()
                    discord_collector = DiscordCollector()
                    self._discord_collectors[user_id] = discord_collector
                    await discord_collector.start(user_id, discord_sources)
                else:
                    logger.info("No enabled Discord sources for user %s", user_id)
            except Exception:
                logger.exception("Failed to start Discord collectors for user %s", user_id)
        else:
            logger.info("No Discord keys for user %s — Discord collector not started", user_id)

        # --- Telegram collector ---
        telegram_keys = await collector_manager.get_keys(user_id, "telegram")
        if telegram_keys:
            try:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Source).where(
                            Source.user_id == user_id,
                            Source.type == "telegram",
                            Source.enabled.is_(True),
                        )
                    )
                    telegram_sources = result.scalars().all()

                if telegram_sources:
                    logger.info("Found %d enabled Telegram sources for user %s", len(telegram_sources), user_id)
                    existing_tg = self._telegram_collectors.pop(user_id, None)
                    if existing_tg:
                        await existing_tg.stop()
                    tg_collector = TelegramCollector()
                    self._telegram_collectors[user_id] = tg_collector
                    await tg_collector.start(user_id, telegram_sources)
                else:
                    logger.info("No enabled Telegram sources for user %s", user_id)
            except Exception:
                logger.exception("Failed to start Telegram collector for user %s", user_id)
        else:
            logger.info("No Telegram keys for user %s — Telegram collector not started", user_id)

        # --- AIS collector ---
        ais_keys = await collector_manager.get_keys(user_id, "ais")
        if ais_keys:
            api_key = ais_keys.get("api_key", "")
            if api_key:
                try:
                    await self.start_ais(api_key)
                    logger.info("AIS collector started for user %s", user_id)
                except Exception:
                    logger.exception("Failed to start AIS collector for user %s", user_id)
            else:
                logger.info("AIS keys for user %s missing 'api_key' field", user_id)
        else:
            logger.info("No AIS keys for user %s — AIS collector not started", user_id)

        # --- ACLED collector ---
        acled_keys = await collector_manager.get_keys(user_id, "acled")
        if acled_keys:
            api_key = acled_keys.get("api_key", "")
            email = acled_keys.get("email", "")
            if api_key and email:
                try:
                    await acled_collector.start(api_key, email)
                    logger.info("ACLED collector started for user %s", user_id)
                except Exception:
                    logger.exception("Failed to start ACLED collector for user %s", user_id)
            else:
                logger.info("ACLED keys for user %s missing api_key or email", user_id)
        else:
            logger.info("No ACLED keys for user %s — ACLED collector not started", user_id)

        # --- Cashtag collector (requires xAI key) ---
        x_keys_for_cashtag = await collector_manager.get_keys(user_id, "x")
        if x_keys_for_cashtag:
            try:
                from app.models.financial import Holding
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(Holding.ticker).where(Holding.user_id == user_id).distinct()
                    )
                    tickers = [row[0] for row in result.all()]

                if tickers:
                    logger.info("Starting cashtag collector for user %s with tickers: %s", user_id, tickers)
                    await self._cashtag_collector.start(user_id, tickers)
                else:
                    logger.info("No holdings for user %s — cashtag collector not started", user_id)
            except Exception:
                logger.exception("Failed to start cashtag collector for user %s", user_id)
        else:
            logger.info("No xAI keys for user %s — cashtag collector not started", user_id)

    async def stop_user_collectors(self, user_id: str) -> None:
        """Called on user logout — stop their collectors."""
        # X
        x_collector = self._x_collectors.pop(user_id, None)
        if x_collector:
            logger.info("Stopping X collector for user %s", user_id)
            try:
                await x_collector.stop()
            except Exception:
                logger.exception("Error stopping X collector for user %s", user_id)

        # Shodan
        shodan_collector = self._shodan_collectors.pop(user_id, None)
        if shodan_collector:
            logger.info("Stopping Shodan collector for user %s", user_id)
            try:
                await shodan_collector.stop()
            except Exception:
                logger.exception("Error stopping Shodan collector for user %s", user_id)

        # Discord
        discord_collector = self._discord_collectors.pop(user_id, None)
        if discord_collector:
            logger.info("Stopping Discord collector for user %s", user_id)
            try:
                await discord_collector.stop()
            except Exception:
                logger.exception("Error stopping Discord collector for user %s", user_id)

        # Telegram
        tg_collector = self._telegram_collectors.pop(user_id, None)
        if tg_collector:
            logger.info("Stopping Telegram collector for user %s", user_id)
            try:
                await tg_collector.stop()
            except Exception:
                logger.exception("Error stopping Telegram collector for user %s", user_id)

        # AIS
        try:
            await ais_collector.stop()
        except Exception:
            logger.exception("Error stopping AIS collector for user %s", user_id)

        # ACLED
        try:
            await acled_collector.stop()
        except Exception:
            logger.exception("Error stopping ACLED collector for user %s", user_id)

        # Cashtag
        try:
            await self._cashtag_collector.stop_user(user_id)
        except Exception:
            logger.exception("Error stopping cashtag collector for user %s", user_id)

    async def stop_all(self) -> None:
        """Called on shutdown — stop all collectors."""
        logger.info("Stopping all collectors")

        try:
            await self._rss_collector.stop()
        except Exception:
            logger.exception("Error stopping RSS collector")

        try:
            await self._reddit_collector.stop()
        except Exception:
            logger.exception("Error stopping Reddit collector")

        try:
            await self._firms_collector.stop()
        except Exception:
            logger.exception("Error stopping FIRMS collector")

        try:
            await self._flight_collector.stop()
        except Exception:
            logger.exception("Error stopping flight collector")

        try:
            await ais_collector.stop()
        except Exception:
            logger.exception("Error stopping AIS collector")

        try:
            await self._market_collector.stop()
        except Exception:
            logger.exception("Error stopping market collector")

        try:
            await self._cashtag_collector.stop()
        except Exception:
            logger.exception("Error stopping cashtag collector")

        for user_id, collector in list(self._x_collectors.items()):
            try:
                await collector.stop()
            except Exception:
                logger.exception("Error stopping X collector for user %s", user_id)
        self._x_collectors.clear()

        for user_id, collector in list(self._shodan_collectors.items()):
            try:
                await collector.stop()
            except Exception:
                logger.exception("Error stopping Shodan collector for user %s", user_id)
        self._shodan_collectors.clear()

        for user_id, collector in list(self._discord_collectors.items()):
            try:
                await collector.stop()
            except Exception:
                logger.exception("Error stopping Discord collector for user %s", user_id)
        self._discord_collectors.clear()

    def get_collector_status(self) -> dict[str, str]:
        """Return active/inactive status for each collector type."""
        return {
            "rss": "active" if self._rss_collector._tasks else "inactive",
            "reddit": "active" if self._reddit_collector._tasks else "inactive",
            "x": "active" if self._x_collectors else "inactive",
            "shodan": "active" if self._shodan_collectors else "inactive",
            "discord": "active" if self._discord_collectors else "inactive",
            "telegram": "active" if self._telegram_collectors else "inactive",
            "firms": "active" if (self._firms_collector._task and not self._firms_collector._task.done()) else "inactive",
            "flights": "active" if (self._flight_collector._task and not self._flight_collector._task.done()) else "inactive",
            "ais": "active" if (ais_collector._task and not ais_collector._task.done()) else "inactive",
            "market": "active" if (self._market_collector._task and not self._market_collector._task.done()) else "inactive",
            "cashtag": "active" if self._cashtag_collector._tasks else "inactive",
            "acled": "active" if (acled_collector._task and not acled_collector._task.done()) else "inactive",
        }


orchestrator = CollectorOrchestrator()

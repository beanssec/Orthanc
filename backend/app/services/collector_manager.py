from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from app.schemas.credentials import CredentialStatus

logger = logging.getLogger("orthanc.collector_manager")

# Number of consecutive failures before a source is auto-disabled
AUTO_DISABLE_THRESHOLD = 5


class CollectorManager:
    """Singleton that holds decrypted API keys in memory for active collectors."""

    _instance: Optional["CollectorManager"] = None
    _active_keys: dict[str, dict]  # user_id -> {provider: decrypted_keys}

    def __new__(cls) -> "CollectorManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._active_keys = {}
        return cls._instance

    async def unlock(self, user_id: str, provider: str, keys: dict) -> None:
        """Store decrypted keys for a provider in memory."""
        if user_id not in self._active_keys:
            self._active_keys[user_id] = {}
        self._active_keys[user_id][provider] = keys

    async def lock(self, user_id: str, provider: Optional[str] = None) -> None:
        """Remove keys from memory (all or a specific provider)."""
        if user_id not in self._active_keys:
            return
        if provider is None:
            del self._active_keys[user_id]
        else:
            self._active_keys[user_id].pop(provider, None)
            if not self._active_keys[user_id]:
                del self._active_keys[user_id]

    async def get_keys(self, user_id: str, provider: str) -> Optional[dict]:
        """Return decrypted keys for a provider, or None if not unlocked."""
        return self._active_keys.get(user_id, {}).get(provider)

    async def get_status(self, user_id: str) -> list[CredentialStatus]:
        """Return status for all known providers."""
        known_providers = ["telegram", "x", "shodan", "discord"]
        user_keys = self._active_keys.get(user_id, {})
        return [
            CredentialStatus(
                provider=p,
                configured=False,  # DB check happens in router
                collector_active=p in user_keys,
            )
            for p in known_providers
        ]

    def is_active(self, user_id: str, provider: str) -> bool:
        """Check if a provider's collector is active (keys loaded in memory)."""
        return provider in self._active_keys.get(user_id, {})

    # ── Source error tracking helpers ─────────────────────────────────────────

    async def record_source_success(self, source_id: str) -> None:
        """Reset error_count and update last_success for a source after a successful poll."""
        from app.db import AsyncSessionLocal
        from app.models.source import Source
        from sqlalchemy import select

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Source).where(Source.id == source_id))
                source = result.scalar_one_or_none()
                if source:
                    source.error_count = 0
                    source.last_success = datetime.now(tz=timezone.utc)
                    await session.commit()
        except Exception as exc:
            logger.warning("record_source_success failed for %s: %s", source_id, exc)

    async def record_source_error(self, source_id: str, error_message: str) -> bool:
        """
        Increment error_count for a source and record the error message.

        Returns True if the source was auto-disabled (error_count reached threshold).
        Resets error_count logic is handled via record_source_success on next success.
        """
        from app.db import AsyncSessionLocal
        from app.models.source import Source
        from sqlalchemy import select

        auto_disabled = False
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Source).where(Source.id == source_id))
                source = result.scalar_one_or_none()
                if source:
                    source.error_count = (source.error_count or 0) + 1
                    source.last_error = error_message[:1000]  # cap length
                    if source.error_count >= AUTO_DISABLE_THRESHOLD and source.enabled:
                        source.enabled = False
                        auto_disabled = True
                        logger.warning(
                            "Source %s (%s) auto-disabled after %d consecutive failures. "
                            "Last error: %s",
                            source_id,
                            source.handle,
                            source.error_count,
                            error_message[:200],
                        )
                    await session.commit()
        except Exception as exc:
            logger.warning("record_source_error failed for %s: %s", source_id, exc)
        return auto_disabled


collector_manager = CollectorManager()

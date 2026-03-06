from __future__ import annotations
from typing import Optional
from app.schemas.credentials import CredentialStatus


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
        known_providers = ["telegram", "x", "mapbox", "shodan", "discord"]
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


collector_manager = CollectorManager()

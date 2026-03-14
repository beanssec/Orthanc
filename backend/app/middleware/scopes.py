"""Scope-based access control foundation — Sprint 30 / Checkpoint 2.

This module provides a *clean dependency factory* that route authors can use
to require a specific scope.  The full RBAC system is intentionally deferred;
this layer gives a stable import contract so routes can be annotated today
and enforcement can be tightened incrementally.

Design
------
Scopes are stored on ``ApiKey.scopes`` (a Postgres text array).  JWT-
authenticated users implicitly hold **all** scopes (they are human operators
with full access).  Machine clients authenticated via API key are constrained
to their key's scope list.

Built-in scope constants (add more as features expand):

    SCOPE_READ_FEED        = "read:feed"
    SCOPE_READ_ENTITIES    = "read:entities"
    SCOPE_READ_NARRATIVES  = "read:narratives"
    SCOPE_READ_ALERTS      = "read:alerts"
    SCOPE_AGENT_READ       = "agent:read"        # umbrella read scope for /agent/*

Usage
-----
In a route that should require ``agent:read``::

    from app.middleware.scopes import require_scope, SCOPE_AGENT_READ

    @router.get("/agent/sitrep")
    async def sitrep(
        _: None = Depends(require_scope(SCOPE_AGENT_READ)),
        current_user: User = Depends(get_agent_auth),
        ...
    ):
        ...

Or combined in a single dependency::

    from app.middleware.scopes import ScopedAgentAuth

    @router.get("/agent/sitrep")
    async def sitrep(
        auth: ScopedAgentAuth = Depends(ScopedAgentAuth.for_scope(SCOPE_AGENT_READ)),
        ...
    ):
        user = auth.user
        ...

Note: ``require_scope`` currently only inspects ``request.state.api_key_scopes``
which is populated by the dual-auth dependency when API-key auth is used.
JWT users bypass scope checks (full access).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List

from fastapi import Depends, HTTPException, Request, status

from app.models import User

logger = logging.getLogger("orthanc.scopes")

# ── Canonical scope strings ───────────────────────────────────────────────────

SCOPE_READ_FEED = "read:feed"
SCOPE_READ_ENTITIES = "read:entities"
SCOPE_READ_NARRATIVES = "read:narratives"
SCOPE_READ_ALERTS = "read:alerts"
SCOPE_AGENT_READ = "agent:read"  # umbrella read scope for /agent/* endpoints

# All scopes implied by the umbrella agent:read scope
_AGENT_READ_IMPLIED: frozenset[str] = frozenset(
    {
        SCOPE_READ_FEED,
        SCOPE_READ_ENTITIES,
        SCOPE_READ_NARRATIVES,
        SCOPE_READ_ALERTS,
        SCOPE_AGENT_READ,
    }
)

# Sentinel: request.state attribute name used to pass scopes from auth → scope check
_REQUEST_STATE_SCOPES_ATTR = "api_key_scopes"
# Sentinel: JWT-authenticated requests are flagged so scope checks are skipped
_REQUEST_STATE_JWT_AUTH_ATTR = "jwt_authenticated"


def _get_effective_scopes(request: Request) -> List[str] | None:
    """Return the scope list attached to the current request, or None for JWT auth."""
    if getattr(request.state, _REQUEST_STATE_JWT_AUTH_ATTR, False):
        return None  # JWT auth → full access, skip scope checks
    return getattr(request.state, _REQUEST_STATE_SCOPES_ATTR, None)


def has_scope(request: Request, scope: str) -> bool:
    """Return True if the current request has the given scope.

    JWT-authenticated requests always return True.
    API-key requests are checked against their stored scope list; a key with
    ``agent:read`` is considered to also hold all implied read scopes.
    """
    effective_scopes = _get_effective_scopes(request)
    if effective_scopes is None:
        # JWT auth — unrestricted
        return True

    # Normalise: also expand agent:read umbrella
    expanded: set[str] = set(effective_scopes)
    if SCOPE_AGENT_READ in expanded:
        expanded |= _AGENT_READ_IMPLIED

    return scope in expanded


def require_scope(scope: str) -> Callable:
    """FastAPI dependency factory: raise 403 if the request lacks *scope*.

    Usage::

        @router.get("/agent/sitrep")
        async def sitrep(_: None = Depends(require_scope(SCOPE_AGENT_READ))):
            ...
    """
    async def _check(request: Request) -> None:
        if not has_scope(request, scope):
            logger.warning(
                "Scope check failed: required=%s effective=%s path=%s",
                scope,
                getattr(request.state, _REQUEST_STATE_SCOPES_ATTR, []),
                request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key missing required scope: {scope}",
            )

    return _check


# ── Convenience helpers called by dual-auth to stamp request state ────────────

def stamp_jwt_auth(request: Request) -> None:
    """Mark the request as JWT-authenticated (full scope access)."""
    setattr(request.state, _REQUEST_STATE_JWT_AUTH_ATTR, True)


def stamp_api_key_scopes(request: Request, scopes: List[str]) -> None:
    """Attach the API key's scope list to request state for downstream checks."""
    setattr(request.state, _REQUEST_STATE_SCOPES_ATTR, list(scopes))


# ── ScopedAgentAuth convenience wrapper ──────────────────────────────────────

@dataclass
class ScopedAgentAuth:
    """Holds the authenticated user plus a helper for scope introspection."""

    user: User
    scopes: List[str] = field(default_factory=list)
    jwt_auth: bool = False

    def can(self, scope: str) -> bool:
        """Return True if this auth context satisfies *scope*."""
        if self.jwt_auth:
            return True
        expanded: set[str] = set(self.scopes)
        if SCOPE_AGENT_READ in expanded:
            expanded |= _AGENT_READ_IMPLIED
        return scope in expanded

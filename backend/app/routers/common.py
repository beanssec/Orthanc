"""Common router utilities — TASK-79: standardized API error responses.

All routers should import and use `api_error` instead of raising bare
HTTPExceptions with plain string details.  This ensures every error response
has a consistent shape:

    {
        "detail":     "Human-readable message",
        "error_code": "SPECIFIC_SNAKE_CASE_CODE",
        "context":    {}   // optional extra data
    }

Usage
-----
    from app.routers.common import api_error

    raise api_error(404, "Narrative not found", "NARRATIVE_NOT_FOUND", {"id": str(narrative_id)})
    raise api_error(400, "Invalid filter value", "INVALID_FILTER")
    raise api_error(409, "Duplicate entry", "DUPLICATE_ENTRY")

Standard error codes (non-exhaustive)
--------------------------------------
    NOT_FOUND           — resource does not exist
    ALREADY_EXISTS      — unique constraint violation
    INVALID_PARAM       — bad/missing request parameter
    UNAUTHORIZED        — not authenticated
    FORBIDDEN           — authenticated but insufficient permission
    INTERNAL_ERROR      — unexpected server error
    RATE_LIMITED        — request rate exceeded
    DEPENDENCY_MISSING  — external service / credential not configured
    DUPLICATE_ENTRY     — record already present
    VALIDATION_ERROR    — request body/schema validation failure
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import HTTPException


def api_error(
    status_code: int,
    detail: str,
    error_code: str = "INTERNAL_ERROR",
    context: Optional[dict[str, Any]] = None,
) -> HTTPException:
    """Build a standardised HTTPException with structured detail payload.

    Returns an HTTPException (not raises) so callers can use ``raise api_error(...)``
    or inspect it before raising.

    Args:
        status_code: HTTP status code (e.g. 404, 400, 409).
        detail:      Human-readable error message.
        error_code:  Machine-readable snake_case error code (e.g. "NOT_FOUND").
        context:     Optional dict of additional contextual data.

    Returns:
        HTTPException with a dict detail payload.
    """
    payload: dict[str, Any] = {
        "detail": detail,
        "error_code": error_code.upper(),
        "context": context or {},
    }
    return HTTPException(status_code=status_code, detail=payload)


# ── Convenience shorthands ─────────────────────────────────────────────────────

def not_found(resource: str, identifier: Any = None) -> HTTPException:
    ctx = {"id": str(identifier)} if identifier is not None else {}
    return api_error(404, f"{resource} not found", "NOT_FOUND", ctx)


def bad_request(message: str, error_code: str = "INVALID_PARAM", context: Optional[dict] = None) -> HTTPException:
    return api_error(400, message, error_code, context)


def conflict(message: str, error_code: str = "ALREADY_EXISTS", context: Optional[dict] = None) -> HTTPException:
    return api_error(409, message, error_code, context)


def forbidden(message: str = "Insufficient permissions", context: Optional[dict] = None) -> HTTPException:
    return api_error(403, message, "FORBIDDEN", context)


def dependency_missing(service: str) -> HTTPException:
    return api_error(
        503,
        f"{service} is not configured or unavailable.",
        "DEPENDENCY_MISSING",
        {"service": service},
    )

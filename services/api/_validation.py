"""
Manual validation utilities for FastAPI route handlers.

Context:
    The venv's pydantic-core wheel was compiled for macOS (darwin) and
    therefore cannot load on this Linux host. The pure-Python fallback stub
    silently ignores all Pydantic field constraints (min_length, max_length,
    pattern, ge, le, type coercion). This module provides reusable guard
    functions that raise HTTPException(422) in place of the missing Pydantic
    enforcement.

Responsibilities:
- Provide constraint-checking helpers that mirror the most common Pydantic
  field constraint semantics.
- Raise HTTPException(422) with descriptive detail messages on violation.
- Be imported by any route handler that processes user-supplied strings,
  URLs, or numeric values against a contract with field constraints.

Does NOT:
- Replace Pydantic model parsing (field presence is still enforced by FastAPI).
- Validate nested JSON structures (use model-level validators for that).
- Contain business logic.

Error conditions:
- All helpers raise HTTPException(422) on constraint violation.

Usage:
    from services.api._validation import require_min_length, require_uri

    require_min_length(payload.rationale, field="rationale", min_len=20)
    require_uri(payload.evidence_link, field="evidence_link")

Note on future fix:
    When pydantic-core is reinstalled with a Linux wheel, these helpers become
    redundant. They are safe to leave in place (no-ops when called with valid
    data). To validate that pydantic constraints are now enforced, run:
        python -c "
        from pydantic import BaseModel, Field
        class T(BaseModel):
            name: str = Field(min_length=3)
        try:
            T(name='ab')
            print('STUB ACTIVE — constraints not enforced')
        except Exception:
            print('REAL pydantic-core — constraints enforced')
        "
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from fastapi import status
from fastapi.exceptions import HTTPException

# ---------------------------------------------------------------------------
# String length guards
# ---------------------------------------------------------------------------


def require_min_length(value: str, *, field: str, min_len: int) -> None:
    """
    Raise 422 if ``value`` is shorter than ``min_len`` characters.

    Args:
        value: The string value to check.
        field: Field name for the error message.
        min_len: Minimum required character count (inclusive).

    Raises:
        HTTPException 422: If len(value) < min_len.

    Example:
        require_min_length(payload.rationale, field="rationale", min_len=20)
    """
    if len(value) < min_len:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"'{field}' must be at least {min_len} characters (got {len(value)})."),
        )


def require_max_length(value: str, *, field: str, max_len: int) -> None:
    """
    Raise 422 if ``value`` exceeds ``max_len`` characters.

    Args:
        value: The string value to check.
        field: Field name for the error message.
        max_len: Maximum allowed character count (inclusive).

    Raises:
        HTTPException 422: If len(value) > max_len.

    Example:
        require_max_length(payload.name, field="name", max_len=255)
    """
    if len(value) > max_len:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"'{field}' must be at most {max_len} characters (got {len(value)})."),
        )


def require_non_empty(value: str | None, *, field: str) -> None:
    """
    Raise 422 if ``value`` is None, empty, or whitespace-only.

    Args:
        value: The string value to check.
        field: Field name for the error message.

    Raises:
        HTTPException 422: If value is None, empty, or whitespace-only.

    Example:
        require_non_empty(payload.name, field="name")
    """
    if not value or not value.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field}' is required and must not be empty.",
        )


# ---------------------------------------------------------------------------
# Pattern / format guards
# ---------------------------------------------------------------------------

_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def require_ulid(value: str, *, field: str) -> None:
    """
    Raise 422 if ``value`` is not a valid Crockford Base32 ULID.

    A ULID is exactly 26 characters from the Crockford Base32 alphabet
    (0-9, A-H, J-N, P-T, V-Z — excluding I, L, O, U).

    Args:
        value: The string value to check.
        field: Field name for the error message.

    Raises:
        HTTPException 422: If value is not a valid ULID.

    Example:
        require_ulid(payload.submitter_id, field="submitter_id")
    """
    if not value or not _ULID_RE.match(value.upper()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(f"'{field}' must be a valid ULID (26 Crockford Base32 chars). Got: {value!r}"),
        )


def require_uri(value: str, *, field: str, schemes: tuple[str, ...] = ("http", "https")) -> None:
    """
    Raise 422 if ``value`` is not an absolute URI with an allowed scheme
    and a non-root path.

    Used to enforce the SOC 2 Evidence of Review requirement: evidence_link
    must point to a specific resource (Jira ticket, Confluence page, etc.),
    not just a hostname.

    Args:
        value: The string value to check.
        field: Field name for the error message.
        schemes: Tuple of allowed URI schemes (default: http and https).

    Raises:
        HTTPException 422: If scheme is not in ``schemes`` or path is empty
            / root-only.

    Example:
        require_uri(payload.evidence_link, field="evidence_link")
    """
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field}' is required.",
        )
    parsed = urlparse(value)
    if parsed.scheme not in schemes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"'{field}' must use one of these schemes: "
                f"{', '.join(schemes)}. Got scheme: '{parsed.scheme}'."
            ),
        )
    path = parsed.path.rstrip("/")
    if not path:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"'{field}' must reference a specific resource path, not just "
                f"the host. Use a Jira ticket, Confluence doc, or issue URL."
            ),
        )


def require_pattern(value: str, *, field: str, pattern: str, description: str) -> None:
    r"""
    Raise 422 if ``value`` does not match the given regex ``pattern``.

    Args:
        value: The string value to check.
        field: Field name for the error message.
        pattern: Regular expression pattern string.
        description: Human-readable description of the expected format.

    Raises:
        HTTPException 422: If value does not match pattern.

    Example:
        require_pattern(version, field="version",
                        pattern=r"^\d+\.\d+\.\d+$",
                        description="semantic version (e.g. 1.2.3)")
    """
    if not re.match(pattern, value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field}' must be a valid {description}. Got: {value!r}",
        )


# ---------------------------------------------------------------------------
# Numeric guards
# ---------------------------------------------------------------------------


def require_ge(value: Any, *, field: str, minimum: int | float) -> None:
    """
    Raise 422 if ``value`` is less than ``minimum``.

    Args:
        value: Numeric value to check.
        field: Field name for the error message.
        minimum: Minimum allowed value (inclusive).

    Raises:
        HTTPException 422: If value < minimum.

    Example:
        require_ge(payload.page_size, field="page_size", minimum=1)
    """
    if value < minimum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field}' must be ≥ {minimum} (got {value}).",
        )


def require_le(value: Any, *, field: str, maximum: int | float) -> None:
    """
    Raise 422 if ``value`` exceeds ``maximum``.

    Args:
        value: Numeric value to check.
        field: Field name for the error message.
        maximum: Maximum allowed value (inclusive).

    Raises:
        HTTPException 422: If value > maximum.

    Example:
        require_le(payload.page_size, field="page_size", maximum=500)
    """
    if value > maximum:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field}' must be ≤ {maximum} (got {value}).",
        )

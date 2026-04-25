"""
Unit tests for frontend↔backend OAuth scope alignment (Tranche L —
2026-04-25).

Context
-------
The 2026-04-25 first-clean-install end-to-end test surfaced a hidden
schism: every gated frontend page returned 403 "Access Denied" with
messages like "You do not have the create_strategy permission" — even
for admin. Diagnosis:

    Backend  (services/api/auth.py:ROLE_SCOPES) issues OAuth-style
             scopes in JWTs:  strategies:write, runs:write,
             feeds:read, approvals:write, overrides:approve,
             audit:read, exports:read, live:trade, ...

    Frontend (frontend/src/router.tsx)         was checking with
             snake_case verb names:  create_strategy, view_runs,
             view_feeds, approve_promotion, manage_overrides,
             view_audit, export_data, activate_kill_switch

The two namespaces never overlap, so admin's JWT — which DID carry
the correct backend scopes — was rejected at every route guard.

Tranche L standardises on the backend OAuth-style names. This test
locks the alignment going forward: every scope literal that appears
in `frontend/src/router.tsx` (and other permission-checking
frontend code) MUST be a member of the union of backend
ROLE_SCOPES values. A future contributor who adds a route guarded
by a typo'd or non-existent scope fails this test before merging.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_AUTH_PATH: Path = _PROJECT_ROOT / "services" / "api" / "auth.py"
_ROUTER_PATH: Path = _PROJECT_ROOT / "frontend" / "src" / "router.tsx"
_ADMIN_LAYOUT_PATH: Path = (
    _PROJECT_ROOT / "frontend" / "src" / "pages" / "Admin" / "AdminLayout.tsx"
)


# ---------------------------------------------------------------------------
# Backend ROLE_SCOPES loader
# ---------------------------------------------------------------------------


def _load_backend_role_scopes() -> dict[str, list[str]]:
    """Import services/api/auth.py and return its ROLE_SCOPES dict.

    Avoids importing the api package (which would pull SQLAlchemy,
    httpx, the keycloak validator, etc.) by spec-loading the module
    file directly. ROLE_SCOPES is defined at module top-level after
    a small set of pure-stdlib imports, so this works without the
    full app graph.
    """
    if not _AUTH_PATH.is_file():
        pytest.fail(f"backend auth.py not found at {_AUTH_PATH}")
    # Read the file and extract ROLE_SCOPES via regex + eval. Importing
    # the module pulls in the entire FastAPI / pydantic / sqlalchemy
    # stack which is too heavy for a unit test and breaks if any of
    # those are unavailable in the test sandbox.
    text = _AUTH_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"ROLE_SCOPES\s*:\s*dict\[str,\s*list\[str\]\]\s*=\s*(\{.*?^\})",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not match:
        pytest.fail(
            "Could not locate ROLE_SCOPES dict literal in auth.py. "
            "If the definition was refactored, update this loader."
        )
    # Evaluate the dict literal in an empty namespace. This is safe
    # because the literal contains only string keys and string-list
    # values — no function calls, no imports.
    role_scopes: dict[str, list[str]] = eval(match.group(1), {"__builtins__": {}}, {})
    assert isinstance(role_scopes, dict) and role_scopes, "ROLE_SCOPES must be a non-empty dict"
    return role_scopes


def _all_backend_scopes(role_scopes: dict[str, list[str]]) -> frozenset[str]:
    """Return the union of every scope across every backend role."""
    return frozenset(scope for scopes in role_scopes.values() for scope in scopes)


# ---------------------------------------------------------------------------
# Frontend scope literal extraction
# ---------------------------------------------------------------------------


#: Matches the scope literal inside ``requiredScope="..."`` or
#: ``hasScope("...")`` in TSX / TS source.  Whitespace tolerant.
_REQUIRED_SCOPE_RE: re.Pattern[str] = re.compile(
    r"""(?:requiredScope|hasScope)\s*[=(]\s*["']([^"']+)["']"""
)


def _extract_scope_literals(path: Path) -> list[tuple[int, str]]:
    """Return [(line_number, scope_literal), ...] for a TS/TSX file."""
    if not path.is_file():
        return []
    results: list[tuple[int, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for match in _REQUIRED_SCOPE_RE.finditer(line):
            results.append((line_no, match.group(1)))
    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def backend_role_scopes() -> dict[str, list[str]]:
    return _load_backend_role_scopes()


@pytest.fixture(scope="module")
def backend_scopes(backend_role_scopes: dict[str, list[str]]) -> frozenset[str]:
    return _all_backend_scopes(backend_role_scopes)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backend_role_scopes_loads_and_admin_is_present(
    backend_role_scopes: dict[str, list[str]],
) -> None:
    """Sanity: ROLE_SCOPES contains the admin role with non-empty scopes."""
    assert "admin" in backend_role_scopes, (
        "ROLE_SCOPES must define the 'admin' role (the role seed_admin.py creates)."
    )
    assert backend_role_scopes["admin"], "admin role must have at least one scope"


def test_backend_admin_role_includes_admin_manage(
    backend_role_scopes: dict[str, list[str]],
) -> None:
    """The admin role must grant ``admin:manage`` (frontend admin layout uses it).

    AdminLayout.tsx:47 and router.tsx:298 both gate the admin sub-tree
    on ``admin:manage``. If no role grants that scope, no user — not
    even the seeded admin — can reach the admin pages.
    """
    assert "admin:manage" in backend_role_scopes["admin"], (
        "admin role must include 'admin:manage' scope. AdminLayout.tsx and "
        "router.tsx (line ~298) gate the entire admin sub-tree on it."
    )


def test_router_uses_only_known_backend_scopes(
    backend_scopes: frozenset[str],
) -> None:
    """Every requiredScope= in router.tsx must be a real backend scope.

    This is the regression guard for the 2026-04-25 schism. router.tsx
    used snake_case verb names (create_strategy, view_runs, etc.) that
    the backend never issues, so admin's JWT — which carried the
    correct backend scopes — was rejected at every gated page.
    """
    literals = _extract_scope_literals(_ROUTER_PATH)
    assert literals, f"No scope literals found in {_ROUTER_PATH}. Did the regex shape change?"
    unknown = [f"line {ln}: {scope!r}" for ln, scope in literals if scope not in backend_scopes]
    assert not unknown, (
        f"router.tsx references scopes the backend does NOT issue: {unknown!r}.\n"
        f"Backend scope vocabulary: {sorted(backend_scopes)!r}.\n"
        "Either (a) update the route guard to use a real scope, or (b) add the "
        "scope to ROLE_SCOPES in services/api/auth.py for at least one role."
    )


def test_admin_layout_uses_only_known_backend_scopes(
    backend_scopes: frozenset[str],
) -> None:
    """Same alignment for AdminLayout.tsx hasScope() guards."""
    literals = _extract_scope_literals(_ADMIN_LAYOUT_PATH)
    if not literals:
        pytest.skip(
            "AdminLayout.tsx has no scope literals (or the file moved); "
            "router.tsx test is sufficient coverage in that case."
        )
    unknown = [f"line {ln}: {scope!r}" for ln, scope in literals if scope not in backend_scopes]
    assert not unknown, (
        f"AdminLayout.tsx references unknown scopes: {unknown!r}. "
        f"Backend vocabulary: {sorted(backend_scopes)!r}."
    )


def test_admin_role_can_access_every_route_in_router(
    backend_role_scopes: dict[str, list[str]],
) -> None:
    """Admin must satisfy every requiredScope in router.tsx.

    The whole point of an "admin" role is that it can reach every
    page. If a route's required scope is real but admin doesn't have
    it, that's also a bug.
    """
    admin_scopes = frozenset(backend_role_scopes["admin"])
    literals = _extract_scope_literals(_ROUTER_PATH)
    unreachable = [f"line {ln}: {scope!r}" for ln, scope in literals if scope not in admin_scopes]
    assert not unreachable, (
        f"Admin role cannot satisfy these route guards: {unreachable!r}.\n"
        f"Admin scopes: {sorted(admin_scopes)!r}.\n"
        "Either grant the scope to admin in ROLE_SCOPES or relax the route guard."
    )

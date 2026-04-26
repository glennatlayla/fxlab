"""
Tests for strategy routes (POST /strategies, GET /strategies/{id}, POST /strategies/validate-dsl).

Verifies:
- Strategy creation returns 201 with validation metadata.
- DSL validation errors return 422.
- Strategy retrieval by ID returns parsed code.
- 404 on nonexistent strategy.
- Authentication enforcement on all endpoints.
- DSL validation endpoint returns structured results.
- List strategies with pagination.
- M2.C1: POST /strategies/import-ir accepts the 5 production IRs and
  rejects malformed bodies with 400 + the validation error path.

Example:
    pytest tests/unit/test_strategy_routes.py -v
"""

from __future__ import annotations

import copy
import io
import json
import logging
import os
from pathlib import Path as FsPath
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api.auth import ROLE_SCOPES, AuthenticatedUser

# ---------------------------------------------------------------------------
# Environment setup — must happen before app import
# ---------------------------------------------------------------------------

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-strategy-routes")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret")

from services.api.main import app  # noqa: E402
from services.api.routes.strategies import set_strategy_service  # noqa: E402

# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


class MockStrategyService:
    """
    Mock StrategyService for route testing.

    Configurable error injection for testing error responses.

    Attributes:
        raise_validation: If set, create_strategy raises ValidationError.
        raise_not_found: If set, get_strategy raises NotFoundError.
    """

    def __init__(self) -> None:
        self.raise_validation: str | None = None
        self.raise_not_found: bool = False
        self._strategies: list[dict] = []
        # Test hooks for the clone_strategy code path. ``raise_clone_*``
        # toggle injection of the corresponding domain error so the
        # route-level tests can drive each branch of the clone handler
        # without standing up the real service. Default behaviour is to
        # synthesise a clone the same way create_strategy synthesises a
        # row, so the happy-path test does not need any toggles set.
        self.raise_clone_not_found: bool = False
        self.raise_clone_conflict: bool = False
        self.raise_clone_validation: str | None = None

    def create_strategy(self, **kwargs) -> dict:
        from libs.contracts.errors import ValidationError

        if self.raise_validation:
            raise ValidationError(self.raise_validation)

        # Synthesize a unique-ish ULID-like ID per strategy so list/page
        # tests can create more than one row and still see distinct items.
        next_idx = len(self._strategies) + 1
        strategy = {
            "id": f"01HSTRAT{next_idx:018d}",
            "name": kwargs["name"],
            "code": "{}",
            "version": "0.1.0",
            "source": "draft_form",
            "created_by": kwargs["created_by"],
            "is_active": True,
            "row_version": 1,
            "created_at": f"2026-04-12T14:00:{next_idx:02d}+00:00",
            "updated_at": f"2026-04-12T14:00:{next_idx:02d}+00:00",
        }
        self._strategies.append(strategy)

        return {
            "strategy": strategy,
            "entry_validation": {
                "is_valid": True,
                "errors": [],
                "indicators_used": ["RSI"],
                "variables_used": [],
            },
            "exit_validation": {
                "is_valid": True,
                "errors": [],
                "indicators_used": ["RSI"],
                "variables_used": [],
            },
            "indicators_used": ["RSI"],
            "variables_used": ["price"],
        }

    def clone_strategy(
        self,
        source_id: str,
        *,
        new_name: str,
        requested_by: str,
    ) -> dict:
        """
        Mock clone_strategy that mirrors the production contract.

        Real semantics, not a stub:
        - When ``raise_clone_not_found`` is set, raise NotFoundError
          (route maps to 404).
        - When ``raise_clone_conflict`` is set, raise
          StrategyNameConflictError (route maps to 409).
        - When ``raise_clone_validation`` is set, raise ValidationError
          with the configured message (route maps to 422 — though in
          practice the route's Pydantic body validation catches empty
          names before this layer is reached).
        - Otherwise synthesise a fresh persisted-row dict the same way
          ``create_strategy`` does, append it to ``self._strategies`` so
          the list endpoints reflect the new row, and return it.
        """
        from libs.contracts.errors import (
            NotFoundError,
            StrategyNameConflictError,
            ValidationError,
        )

        if self.raise_clone_validation:
            raise ValidationError(self.raise_clone_validation)
        if self.raise_clone_not_found:
            raise NotFoundError(f"Strategy {source_id} not found")
        if self.raise_clone_conflict:
            raise StrategyNameConflictError(
                f"A strategy named {new_name!r} already exists",
                name=new_name,
            )

        next_idx = len(self._strategies) + 1
        clone = {
            "id": f"01HCLONE{next_idx:018d}",
            "name": new_name,
            "code": "{}",
            "version": "0.1.0",
            "source": "draft_form",
            "created_by": requested_by,
            "is_active": True,
            "row_version": 1,
            "created_at": f"2026-04-12T15:00:{next_idx:02d}+00:00",
            "updated_at": f"2026-04-12T15:00:{next_idx:02d}+00:00",
        }
        self._strategies.append(clone)
        return clone

    def get_strategy(self, strategy_id: str) -> dict:
        from libs.contracts.errors import NotFoundError

        if self.raise_not_found:
            raise NotFoundError(f"Strategy {strategy_id} not found")

        return {
            "id": strategy_id,
            "name": "Test Strategy",
            "code": '{"entry_condition": "RSI(14) < 30"}',
            "version": "0.1.0",
            "created_by": "01HTESTFAKE000000000000000",
            "is_active": True,
            "parsed_code": {"entry_condition": "RSI(14) < 30"},
            "created_at": "2026-04-12T14:00:00+00:00",
            "updated_at": "2026-04-12T14:00:00+00:00",
        }

    def get_with_parsed_ir(
        self,
        strategy_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict:
        """
        Mock M2.C4 GET-with-parsed-IR.

        Mirrors the production semantics: NotFoundError when configured,
        otherwise returns a draft_form-shaped record (parsed_ir is None,
        draft_fields carries the parsed code dict). Tests that exercise
        the ir_upload branch use the ``import_ir_test_env`` fixture
        which wires the real StrategyService against MockStrategyRepository.
        """
        from libs.contracts.errors import NotFoundError

        if self.raise_not_found:
            raise NotFoundError(f"Strategy {strategy_id} not found")

        return {
            "id": strategy_id,
            "name": "Test Strategy",
            "code": '{"entry_condition": "RSI(14) < 30"}',
            "version": "0.1.0",
            "created_by": "01HTESTFAKE000000000000000",
            "is_active": True,
            "row_version": 1,
            "source": "draft_form",
            "created_at": "2026-04-12T14:00:00+00:00",
            "updated_at": "2026-04-12T14:00:00+00:00",
            "parsed_ir": None,
            "draft_fields": {"entry_condition": "RSI(14) < 30"},
        }

    def list_strategies(self, **kwargs) -> dict:
        return {
            "strategies": self._strategies,
            "limit": kwargs.get("limit", 50),
            "offset": kwargs.get("offset", 0),
            "count": len(self._strategies),
        }

    def list_strategies_page(self, **kwargs):
        """
        Mock M2.D5 paginated browse-page method.

        Filters the in-memory list by source / name_contains so the
        route-level filter tests can exercise the parameter wiring
        without standing up the real ``StrategyService``. Returns a
        :class:`StrategyListPage` so the route's ``model_dump`` call
        sees the expected schema-validated value object.
        """
        from libs.contracts.strategy import StrategyListItem, StrategyListPage

        page = int(kwargs.get("page", 1))
        page_size = int(kwargs.get("page_size", 20))
        source_filter = kwargs.get("source_filter")
        name_contains = kwargs.get("name_contains")

        rows = list(self._strategies)
        if source_filter is not None:
            rows = [r for r in rows if r.get("source") == source_filter]
        if name_contains is not None and str(name_contains).strip():
            needle = str(name_contains).strip().lower()
            rows = [r for r in rows if needle in str(r.get("name", "")).lower()]

        total_count = len(rows)
        offset = max(0, (page - 1) * page_size)
        page_rows = rows[offset : offset + page_size]

        items: list[StrategyListItem] = []
        for r in page_rows:
            items.append(
                StrategyListItem(
                    id=str(r["id"]),
                    name=str(r["name"]),
                    source=str(r.get("source") or "draft_form"),
                    version=str(r.get("version") or "0.1.0"),
                    created_by=str(r["created_by"]),
                    created_at=str(r["created_at"]),
                    is_active=bool(r.get("is_active", True)),
                )
            )

        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0
        return StrategyListPage(
            strategies=items,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
        )

    def validate_ir(self, ir_text: str):
        """
        Mock validate_ir mirroring StrategyService.validate_ir's contract.

        Test hooks:
        - ``validate_ir_force_invalid`` (truthy) → return a deterministic
          invalid report so the route layer can be exercised against the
          422-style error envelope without standing up the real parser.
        - Default behaviour: if ``ir_text`` is empty / whitespace, return
          an invalid_json report; otherwise return a valid report with
          a parsed_ir derived from the input (best-effort json.loads,
          falling back to ``{}``). This keeps the happy-path test honest
          without requiring the real Pydantic schema.
        """
        from libs.contracts.strategy import StrategyValidationReport, ValidationIssue

        if getattr(self, "validate_ir_force_invalid", False):
            return StrategyValidationReport(
                valid=False,
                parsed_ir=None,
                errors=[
                    ValidationIssue(
                        path="/metadata/strategy_name",
                        code="schema_violation",
                        message="field required",
                    )
                ],
                warnings=[],
            )

        if not ir_text or not ir_text.strip():
            return StrategyValidationReport(
                valid=False,
                parsed_ir=None,
                errors=[
                    ValidationIssue(
                        path="/",
                        code="invalid_json",
                        message="IR text is empty.",
                    )
                ],
                warnings=[],
            )

        try:
            parsed = json.loads(ir_text)
            if not isinstance(parsed, dict):
                parsed = None
        except json.JSONDecodeError:
            return StrategyValidationReport(
                valid=False,
                parsed_ir=None,
                errors=[
                    ValidationIssue(
                        path="/",
                        code="invalid_json",
                        message="not valid json",
                    )
                ],
                warnings=[],
            )

        return StrategyValidationReport(
            valid=True,
            parsed_ir=parsed or {},
            errors=[],
            warnings=[],
        )

    def get_strategy_ir_json(self, strategy_id: str) -> str:
        """
        Mock get_strategy_ir_json mirroring StrategyService.get_strategy_ir_json.

        - When ``raise_not_found`` is set → raise NotFoundError (route
          maps to 404).
        - Otherwise return a deterministic IR JSON string so the route
          test can assert the body and Content-Disposition header.
        """
        from libs.contracts.errors import NotFoundError

        if self.raise_not_found:
            raise NotFoundError(f"Strategy {strategy_id} not found")
        return '{"strategy_name": "Test Strategy", "schema_version": "0.1-inferred"}'

    def validate_dsl_expression(self, expression: str) -> dict:
        if not expression or not expression.strip():
            return {
                "is_valid": False,
                "errors": [
                    {"message": "Empty expression", "line": 1, "column": 1, "suggestion": None}
                ],
                "indicators_used": [],
                "variables_used": [],
            }
        return {
            "is_valid": True,
            "errors": [],
            "indicators_used": ["RSI"],
            "variables_used": ["price"],
        }


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

_OPERATOR_USER = AuthenticatedUser(
    user_id="01HTESTFAKE000000000000000",
    email="trader@fxlab.test",
    role="operator",
    scopes=ROLE_SCOPES.get("operator", set()),
)


def _auth_headers() -> dict[str, str]:
    """Authorization headers using a test token."""
    return {"Authorization": "Bearer TEST_TOKEN"}


def _override_auth(application: Any) -> None:
    """Override get_current_user to return a test operator user."""
    from services.api.auth import get_current_user

    async def _fake_get_current_user() -> AuthenticatedUser:
        return _OPERATOR_USER

    application.dependency_overrides[get_current_user] = _fake_get_current_user


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy_test_env():
    """
    Set up a TestClient with mock StrategyService and auth override.

    Yields:
        Tuple of (TestClient, MockStrategyService, app).
    """
    mock_service = MockStrategyService()
    set_strategy_service(mock_service)
    _override_auth(app)

    client = TestClient(app)
    yield client, mock_service, app

    app.dependency_overrides.clear()
    set_strategy_service(None)


# ---------------------------------------------------------------------------
# Tests: POST /strategies
# ---------------------------------------------------------------------------


class TestCreateStrategyRoute:
    """Tests for POST /strategies."""

    def test_create_strategy_returns_201(self, strategy_test_env) -> None:
        """Valid creation returns 201 with strategy and validation metadata."""
        client, _, _app = strategy_test_env

        resp = client.post(
            "/strategies/",
            json={
                "name": "RSI Reversal",
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
                "instrument": "AAPL",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["strategy"]["name"] == "RSI Reversal"
        assert data["entry_validation"]["is_valid"] is True
        assert "RSI" in data["indicators_used"]

    def test_create_strategy_dsl_error_returns_422(self, strategy_test_env) -> None:
        """Invalid DSL should return 422."""
        client, mock_service, _ = strategy_test_env
        mock_service.raise_validation = "Entry condition: RSI requires 1 argument"

        resp = client.post(
            "/strategies/",
            json={
                "name": "Bad Strategy",
                "entry_condition": "RSI() < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_create_strategy_missing_name_returns_422(self, strategy_test_env) -> None:
        """Missing name should return 422 from Pydantic validation."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/",
            json={
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_create_strategy_requires_auth(self, strategy_test_env) -> None:
        """Request without auth should be rejected."""
        client, _, _app = strategy_test_env
        _app.dependency_overrides.clear()

        resp = client.post(
            "/strategies/",
            json={
                "name": "No Auth",
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
        )

        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Tests: GET /strategies/{id}
# ---------------------------------------------------------------------------


class TestGetStrategyRoute:
    """Tests for GET /strategies/{id} (M2.C4 response shape)."""

    def test_get_strategy_returns_200(self, strategy_test_env) -> None:
        """Existing strategy returns 200 wrapped under ``strategy``.

        M2.C4 changed the response envelope to ``{"strategy": {...}}``
        and added ``source``, ``parsed_ir``, ``draft_fields``.
        """
        client, _, _ = strategy_test_env

        resp = client.get("/strategies/01HSTRAT0000000000000001", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert "strategy" in data
        strategy = data["strategy"]
        assert strategy["name"] == "Test Strategy"
        assert strategy["source"] in ("draft_form", "ir_upload")
        # The legacy mock service returns a draft_form shape — assert
        # the M2.C4 surface is wired through correctly.
        assert strategy["parsed_ir"] is None
        assert strategy["draft_fields"] == {"entry_condition": "RSI(14) < 30"}

    def test_get_strategy_not_found_returns_404(self, strategy_test_env) -> None:
        """Nonexistent strategy returns 404."""
        client, mock_service, _ = strategy_test_env
        mock_service.raise_not_found = True

        resp = client.get("/strategies/01HNONEXISTENT0000000000", headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: POST /strategies/validate-dsl
# ---------------------------------------------------------------------------


class TestValidateDslRoute:
    """Tests for POST /strategies/validate-dsl."""

    def test_validate_valid_dsl(self, strategy_test_env) -> None:
        """Valid DSL returns is_valid=True."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-dsl",
            json={
                "expression": "RSI(14) < 30 AND price > SMA(200)",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_valid"] is True

    def test_validate_empty_dsl(self, strategy_test_env) -> None:
        """Empty DSL returns is_valid=False with errors."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-dsl",
            json={
                "expression": "",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_valid"] is False
        assert len(data["errors"]) > 0

    def test_validate_dsl_returns_indicators(self, strategy_test_env) -> None:
        """Validation result should include detected indicators."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-dsl",
            json={
                "expression": "RSI(14) < 30",
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "RSI" in data["indicators_used"]


# ---------------------------------------------------------------------------
# Tests: GET /strategies/ (list)
# ---------------------------------------------------------------------------


class TestListStrategiesRoute:
    """Tests for GET /strategies/."""

    def test_list_empty(self, strategy_test_env) -> None:
        """Empty list returns count 0."""
        client, _, _ = strategy_test_env

        resp = client.get("/strategies/", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_list_after_create(self, strategy_test_env) -> None:
        """After creating a strategy, list should include it."""
        client, _, _ = strategy_test_env

        client.post(
            "/strategies/",
            json={
                "name": "Listed Strategy",
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )

        resp = client.get("/strategies/", headers=_auth_headers())
        data = resp.json()
        assert data["count"] == 1


# ---------------------------------------------------------------------------
# Tests: GET /strategies/?page=&page_size=... (M2.D5 paginated browse page)
# ---------------------------------------------------------------------------


class TestListStrategiesPagedRoute:
    """
    Tests for the M2.D5 paginated envelope on ``GET /strategies/``.

    The new envelope is opted into by supplying ``?page=`` (any 1-based
    integer). When omitted, the legacy ``{strategies, limit, offset,
    count}`` envelope is preserved (covered by
    :class:`TestListStrategiesRoute`).

    These tests verify:
      * Empty result → ``total_count == 0`` and ``strategies == []``.
      * Pagination math (page/page_size/total_count/total_pages) is
        correct across multiple pages.
      * ``source`` query param filters the result set.
      * ``name_contains`` query param applies a case-insensitive
        substring match.
      * ``page_size`` is bounded above by the schema cap (200).
      * Auth is enforced (the route inherits the ``strategies:write``
        scope from the rest of the file).
    """

    def _seed_strategy(
        self,
        client: TestClient,
        name: str,
    ) -> str:
        """Create a strategy via the existing POST endpoint.

        Returns the new strategy id so tests can assert per-row state
        without reaching into the mock service's internals.
        """
        resp = client.post(
            "/strategies/",
            json={
                "name": name,
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        return body["strategy"]["id"]

    def test_paged_empty_returns_total_count_zero(self, strategy_test_env) -> None:
        """Empty store returns total_count=0 with the new envelope."""
        client, _, _ = strategy_test_env

        resp = client.get("/strategies/?page=1&page_size=20", headers=_auth_headers())

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["strategies"] == []
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total_count"] == 0
        assert data["total_pages"] == 0
        # Legacy compatibility — ``count`` mirrors page-level size.
        assert data["count"] == 0

    def test_paged_returns_envelope_with_total_count(self, strategy_test_env) -> None:
        """Non-empty result populates the envelope including total_pages."""
        client, _, _ = strategy_test_env
        for i in range(3):
            self._seed_strategy(client, f"Strategy {i}")

        resp = client.get("/strategies/?page=1&page_size=20", headers=_auth_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total_count"] == 3
        assert data["total_pages"] == 1
        assert data["count"] == 3
        assert len(data["strategies"]) == 3
        for row in data["strategies"]:
            # Pinned row schema — the frontend grid relies on these keys.
            for key in ("id", "name", "source", "version", "created_by", "created_at", "is_active"):
                assert key in row, f"missing {key} in row {row}"

    def test_paged_pagination_math_across_pages(self, strategy_test_env) -> None:
        """page + page_size correctly partition the dataset."""
        client, _, _ = strategy_test_env
        for i in range(5):
            self._seed_strategy(client, f"S{i}")

        # Page 1 of 2 (page_size=2): 2 rows, total_count=5, total_pages=3.
        resp = client.get("/strategies/?page=1&page_size=2", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 2
        assert data["total_count"] == 5
        assert data["total_pages"] == 3
        assert len(data["strategies"]) == 2

        # Page 3: last page, single row.
        resp = client.get("/strategies/?page=3&page_size=2", headers=_auth_headers())
        data = resp.json()
        assert data["page"] == 3
        assert len(data["strategies"]) == 1
        assert data["total_pages"] == 3

        # Page 4: out-of-range, empty rows but total_count + total_pages
        # still populated so the UI can disable the Next button.
        resp = client.get("/strategies/?page=4&page_size=2", headers=_auth_headers())
        data = resp.json()
        assert data["page"] == 4
        assert data["strategies"] == []
        assert data["total_count"] == 5
        assert data["total_pages"] == 3

    def test_paged_filter_by_source(self, strategy_test_env) -> None:
        """``source=draft_form`` filters to draft-form strategies only."""
        client, mock_service, _ = strategy_test_env
        # Seed two draft_form rows via POST, then inject one ir_upload
        # row directly through the mock so we can exercise both branches.
        self._seed_strategy(client, "draft one")
        self._seed_strategy(client, "draft two")
        mock_service._strategies.append(
            {
                "id": "01HSTRATIRUPLOAD000000001",
                "name": "ir uploaded",
                "code": "{}",
                "version": "1.0.0",
                "source": "ir_upload",
                "created_by": _OPERATOR_USER.user_id,
                "is_active": True,
                "row_version": 1,
                "created_at": "2026-04-12T14:00:99+00:00",
                "updated_at": "2026-04-12T14:00:99+00:00",
            }
        )

        # Filter to ir_upload only.
        resp = client.get(
            "/strategies/?page=1&page_size=20&source=ir_upload", headers=_auth_headers()
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert len(data["strategies"]) == 1
        assert data["strategies"][0]["source"] == "ir_upload"
        assert data["strategies"][0]["name"] == "ir uploaded"

        # Filter to draft_form only.
        resp = client.get(
            "/strategies/?page=1&page_size=20&source=draft_form", headers=_auth_headers()
        )
        data = resp.json()
        assert data["total_count"] == 2
        for row in data["strategies"]:
            assert row["source"] == "draft_form"

    def test_paged_filter_by_name_contains_is_case_insensitive(self, strategy_test_env) -> None:
        """``name_contains`` matches case-insensitively against the name column."""
        client, _, _ = strategy_test_env
        self._seed_strategy(client, "Bollinger Reversal")
        self._seed_strategy(client, "RSI Mean Reversion")
        self._seed_strategy(client, "Momentum Breakout")

        resp = client.get(
            "/strategies/?page=1&page_size=20&name_contains=BOLLINGER",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert data["strategies"][0]["name"] == "Bollinger Reversal"

        # No matches → empty list, total 0.
        resp = client.get(
            "/strategies/?page=1&page_size=20&name_contains=zzz_no_match",
            headers=_auth_headers(),
        )
        data = resp.json()
        assert data["total_count"] == 0
        assert data["strategies"] == []

    def test_paged_invalid_source_filter_returns_422(self, strategy_test_env) -> None:
        """A source value outside the regex returns 422 (FastAPI validation)."""
        client, _, _ = strategy_test_env

        resp = client.get(
            "/strategies/?page=1&page_size=20&source=garbage", headers=_auth_headers()
        )
        assert resp.status_code == 422

    def test_paged_page_size_above_cap_returns_422(self, strategy_test_env) -> None:
        """``page_size`` above the cap (200) is a 422."""
        client, _, _ = strategy_test_env

        resp = client.get("/strategies/?page=1&page_size=999", headers=_auth_headers())
        assert resp.status_code == 422

    def test_paged_requires_auth(self, strategy_test_env) -> None:
        """Request without auth is rejected before the service runs."""
        client, _, _app = strategy_test_env
        _app.dependency_overrides.clear()

        resp = client.get("/strategies/?page=1&page_size=20")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Tests: POST /strategies/import-ir (M2.C1)
# ---------------------------------------------------------------------------

#: Five production IR files shipped under ``Strategy Repo/`` — pinned
#: explicitly so a future repo addition does not silently change the
#: contract test surface (the M2.C1 acceptance is "each of the 5
#: repo IR files", not "every file we happen to have").
_REPO_IR_FILES: tuple[str, ...] = (
    "Strategy Repo/fxlab_chan_next3_strategy_pack/FX_SingleAsset_MeanReversion_H1.strategy_ir.json",
    "Strategy Repo/fxlab_chan_next3_strategy_pack/FX_TimeSeriesMomentum_Breakout_D1.strategy_ir.json",
    "Strategy Repo/fxlab_chan_next3_strategy_pack/FX_TurnOfMonth_USDSeasonality_D1.strategy_ir.json",
    "Strategy Repo/fxlab_kathy_lien_public_strategy_pack/FX_DoubleBollinger_TrendZone.strategy_ir.json",
    "Strategy Repo/fxlab_kathy_lien_public_strategy_pack/FX_MTF_DailyTrend_H1Pullback.strategy_ir.json",
)


def _load_repo_ir(rel_path: str) -> dict[str, Any]:
    """
    Load a strategy_ir.json from the repo by repository-relative path.

    Args:
        rel_path: Path relative to the project root.

    Returns:
        Parsed JSON dict.
    """
    # tests/unit/test_strategy_routes.py → up two levels = project root.
    project_root = FsPath(__file__).resolve().parents[2]
    full = project_root / rel_path
    with full.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def import_ir_test_env():
    """
    TestClient + real ``StrategyService`` wired to ``MockStrategyRepository``.

    The M2.C1 contract test must exercise the actual ``StrategyIR``
    Pydantic validation — substituting a hand-rolled mock service
    here would defeat the whole acceptance criterion. Wiring the real
    service against the mock repo lets us assert persistence
    behaviour (source flag, IR JSON in code, generated strategy_id)
    without a database.
    """
    from libs.contracts.mocks.mock_strategy_repository import MockStrategyRepository
    from services.api.routes.strategies import set_strategy_service
    from services.api.services.strategy_service import StrategyService

    repo = MockStrategyRepository()
    real_service = StrategyService(strategy_repo=repo)
    set_strategy_service(real_service)
    _override_auth(app)

    client = TestClient(app)
    yield client, repo

    app.dependency_overrides.clear()
    set_strategy_service(None)


class TestImportStrategyIR:
    """
    Contract tests for ``POST /strategies/import-ir`` (M2.C1).

    Acceptance (workplan lines 608-610):
    - posting each of the 5 repo IR files returns 201 with a new
      ``strategy_id``;
    - posting a malformed IR (missing artifact_type) returns 400 with
      the validation error path in the response body;
    - the structured audit log entry ``event=strategy_imported
      strategy_id=... source=ir_upload`` is emitted on success.
    """

    @pytest.mark.parametrize("ir_path", _REPO_IR_FILES)
    def test_import_repo_ir_returns_201(self, import_ir_test_env, ir_path: str) -> None:
        """Each of the 5 production IRs imports cleanly with 201."""
        client, repo = import_ir_test_env

        ir_body = _load_repo_ir(ir_path)
        # Send as multipart upload — the same shape the frontend
        # M2.D1 file-drop panel will use.
        resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    os.path.basename(ir_path),
                    json.dumps(ir_body).encode("utf-8"),
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "strategy" in data
        strategy = data["strategy"]
        # strategy_id is non-empty (ULID, 26 chars in this codebase)
        assert strategy["id"], "expected non-empty strategy_id on import"
        assert len(strategy["id"]) == 26
        assert strategy["source"] == "ir_upload"
        assert strategy["name"] == ir_body["metadata"]["strategy_name"]
        # Repository was actually written through (not a stub).
        assert repo.count() == 1
        persisted = repo.get_by_id(strategy["id"])
        assert persisted is not None
        # Persisted code is the canonical IR JSON — round-trips back to
        # the original dict (key order doesn't matter, values do).
        assert json.loads(persisted["code"]) == ir_body

    def test_import_malformed_ir_returns_400_with_error_path(self, import_ir_test_env) -> None:
        """Missing ``artifact_type`` returns 400 + the field path in detail."""
        client, repo = import_ir_test_env

        ir_body = _load_repo_ir(_REPO_IR_FILES[0])
        bad = copy.deepcopy(ir_body)
        del bad["artifact_type"]  # pin the failure to a known path

        resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    "broken.strategy_ir.json",
                    json.dumps(bad).encode("utf-8"),
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 400, resp.text
        body = resp.json()
        # FastAPI HTTPException renders {"detail": "..."}
        assert "detail" in body
        # The Pydantic error path for the missing field is exactly
        # "artifact_type" — assert the path appears in the response so
        # callers can locate the offending field per acceptance.
        assert "artifact_type" in body["detail"], body
        # Nothing was persisted on a 400.
        assert repo.count() == 0

    def test_import_invalid_json_returns_400(self, import_ir_test_env) -> None:
        """A non-JSON upload returns 400 with a clear message."""
        client, repo = import_ir_test_env

        resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    "garbage.json",
                    b"this is not json {",
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 400
        assert "JSON" in resp.json()["detail"]
        assert repo.count() == 0

    def test_import_emits_audit_log_on_success(
        self,
        import_ir_test_env,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A successful import emits ``event=strategy_imported`` per CLAUDE.md §8.

        structlog in this codebase is configured to render directly to
        stdout rather than route through the stdlib logging tree, so
        ``caplog`` does not see structlog calls. The structurally-
        correct way to assert the audit emission is therefore to spy
        on the route module's bound logger and verify the call shape
        is exactly what the workplan pins.
        """
        client, _repo = import_ir_test_env
        from services.api.routes import strategies as strategies_module

        captured: list[tuple[str, dict[str, Any]]] = []
        original_info = strategies_module.logger.info

        def _spy_info(event: str, /, **kwargs: Any) -> Any:
            captured.append((event, kwargs))
            return original_info(event, **kwargs)

        monkeypatch.setattr(strategies_module.logger, "info", _spy_info)

        ir_body = _load_repo_ir(_REPO_IR_FILES[0])
        resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    "audit.strategy_ir.json",
                    json.dumps(ir_body).encode("utf-8"),
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )

        assert resp.status_code == 201
        strategy_id = resp.json()["strategy"]["id"]

        # The audit line is the one whose event name matches exactly
        # the workplan's pin: ``strategy_imported``.
        audit_calls = [(ev, kw) for (ev, kw) in captured if ev == "strategy_imported"]
        assert len(audit_calls) == 1, (
            f"expected exactly one strategy_imported audit log line; got {captured}"
        )
        _event, kwargs = audit_calls[0]
        assert kwargs["strategy_id"] == strategy_id
        assert kwargs["source"] == "ir_upload"
        # CLAUDE.md §8 required structured fields:
        assert "user_id" in kwargs
        assert "correlation_id" in kwargs
        assert kwargs["component"] == "strategies"
        # Silence ruff about unused logging import.
        _ = logging

    def test_import_requires_auth(self, import_ir_test_env) -> None:
        """Request without auth is rejected (no service call)."""
        client, repo = import_ir_test_env
        # Drop the auth override so the real require_scope dependency runs.
        app.dependency_overrides.clear()

        ir_body = _load_repo_ir(_REPO_IR_FILES[0])
        resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    "noauth.strategy_ir.json",
                    json.dumps(ir_body).encode("utf-8"),
                    "application/json",
                ),
            },
        )

        assert resp.status_code in (401, 403, 422)
        assert repo.count() == 0


# Silence unused-import check for io (kept for symmetry with future
# multi-part stream tests under M2.C2).
_ = io


# ---------------------------------------------------------------------------
# Tests: GET /strategies/{id} round-trip with parsed IR (M2.C4)
# ---------------------------------------------------------------------------


class TestGetStrategyParsedIRRoundTrip:
    """
    M2.C4 acceptance: the 5 imported repo strategies each round-trip
    through GET /strategies/{id} with deep-equal IR bodies.

    Workflow per IR:
      1. POST /strategies/import-ir with the IR file (M2.C1) → 201
      2. Extract strategy_id from response.
      3. GET /strategies/{strategy_id} → 200
      4. Assert response.json()["strategy"]["source"] == "ir_upload".
      5. Assert response.json()["strategy"]["parsed_ir"] deep-equals
         the original IR JSON (canonicalised via sort_keys to absorb
         field-ordering noise — values must match exactly).
    """

    @pytest.mark.parametrize("ir_path", _REPO_IR_FILES)
    def test_get_returns_parsed_ir_round_trip(
        self,
        import_ir_test_env,
        ir_path: str,
    ) -> None:
        """Each of the 5 production IRs round-trips through GET endpoint."""
        client, _repo = import_ir_test_env

        ir_body = _load_repo_ir(ir_path)

        # 1) Import via POST /strategies/import-ir (M2.C1 endpoint).
        import_resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    os.path.basename(ir_path),
                    json.dumps(ir_body).encode("utf-8"),
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )
        assert import_resp.status_code == 201, import_resp.text
        strategy_id = import_resp.json()["strategy"]["id"]

        # 2) GET the strategy back.
        get_resp = client.get(f"/strategies/{strategy_id}", headers=_auth_headers())
        assert get_resp.status_code == 200, get_resp.text

        body = get_resp.json()
        assert "strategy" in body
        strategy = body["strategy"]

        # 3) Source flag is the M2.C1 provenance pin.
        assert strategy["source"] == "ir_upload"
        assert strategy["draft_fields"] is None

        # 4) parsed_ir deep-equals the original IR JSON. Compare via
        #    sort_keys-canonicalised JSON so any unintended field
        #    reordering at the model_dump layer would still match — the
        #    contract is value equality, not Python dict identity.
        returned_ir = strategy["parsed_ir"]
        assert returned_ir is not None, "expected parsed_ir for source=ir_upload"
        assert json.dumps(returned_ir, sort_keys=True) == json.dumps(ir_body, sort_keys=True), (
            f"IR round-trip mismatch for {ir_path}: parsed_ir does not deep-equal upload"
        )

        # 5) Other persistence columns are present and well-typed.
        assert strategy["id"] == strategy_id
        assert strategy["name"] == ir_body["metadata"]["strategy_name"]
        assert strategy["version"] == ir_body["metadata"]["strategy_version"]
        assert isinstance(strategy["row_version"], int)
        assert strategy["is_active"] is True
        assert strategy["created_at"]
        assert strategy["updated_at"]

    def test_get_with_unknown_id_returns_404(self, import_ir_test_env) -> None:
        """A non-existent strategy_id returns 404 (real service path)."""
        client, _repo = import_ir_test_env

        resp = client.get(
            "/strategies/01HFAKEFAKEFAKEFAKEFAKEFAKE",
            headers=_auth_headers(),
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_get_includes_source_field_explicitly(
        self,
        import_ir_test_env,
    ) -> None:
        """The ``source`` column from migration 0025 surfaces verbatim."""
        client, _repo = import_ir_test_env

        ir_body = _load_repo_ir(_REPO_IR_FILES[0])
        import_resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    "src.strategy_ir.json",
                    json.dumps(ir_body).encode("utf-8"),
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )
        strategy_id = import_resp.json()["strategy"]["id"]

        get_resp = client.get(f"/strategies/{strategy_id}", headers=_auth_headers())
        assert get_resp.status_code == 200
        # The frontend dispatches off this field; assert it's both
        # present and exactly the expected literal value.
        assert "source" in get_resp.json()["strategy"]
        assert get_resp.json()["strategy"]["source"] == "ir_upload"

    def test_get_round_trip_preserves_all_top_level_ir_keys(
        self,
        import_ir_test_env,
    ) -> None:
        """No top-level IR key is silently dropped during round-trip."""
        client, _repo = import_ir_test_env

        ir_body = _load_repo_ir(_REPO_IR_FILES[0])
        import_resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    "keys.strategy_ir.json",
                    json.dumps(ir_body).encode("utf-8"),
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )
        strategy_id = import_resp.json()["strategy"]["id"]

        get_resp = client.get(f"/strategies/{strategy_id}", headers=_auth_headers())
        returned_ir = get_resp.json()["strategy"]["parsed_ir"]

        # Symmetric difference must be empty — neither side may contain
        # a key the other lacks. This is stricter than a deep-equal
        # because Python's == treats {"a": None} == {} as False, but
        # a buggy Pydantic dump could still match overall while losing
        # an optional field. This guards that case.
        assert set(returned_ir.keys()) == set(ir_body.keys()), (
            f"top-level key set differs: missing={set(ir_body) - set(returned_ir)}, "
            f"extra={set(returned_ir) - set(ir_body)}"
        )

    def test_get_requires_auth(self, import_ir_test_env) -> None:
        """Request without auth is rejected before the service runs."""
        client, _repo = import_ir_test_env

        # Import once (with the override still in place) so a real ID
        # exists, then drop the override and assert auth is enforced.
        ir_body = _load_repo_ir(_REPO_IR_FILES[0])
        import_resp = client.post(
            "/strategies/import-ir",
            files={
                "file": (
                    "auth.strategy_ir.json",
                    json.dumps(ir_body).encode("utf-8"),
                    "application/json",
                ),
            },
            headers=_auth_headers(),
        )
        strategy_id = import_resp.json()["strategy"]["id"]

        app.dependency_overrides.clear()
        resp = client.get(f"/strategies/{strategy_id}")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Tests: GET /strategies/{strategy_id}/runs (recent runs section)
# ---------------------------------------------------------------------------


@pytest.fixture()
def strategy_runs_test_env():
    """
    TestClient + real :class:`ResearchRunService` wired to
    :class:`MockResearchRunRepository`.

    The recent-runs endpoint reuses the runs router's
    ``set_research_run_service`` registration (the strategies router
    re-uses the same DI to avoid wiring the service twice). We build a
    real service against the mock repo so the route exercises the actual
    persistence projection logic, not a hand-rolled fake.

    Yields:
        Tuple of (TestClient, MockResearchRunRepository, ResearchRunService).
    """
    from datetime import datetime, timezone

    from libs.contracts.mocks.mock_research_run_repository import (
        MockResearchRunRepository,
    )
    from services.api.routes.runs import set_research_run_service
    from services.api.services.research_run_service import ResearchRunService

    repo = MockResearchRunRepository()
    service = ResearchRunService(repo=repo)
    set_research_run_service(service)
    _override_auth(app)

    # Pin a deterministic "now" reference that tests can use to build
    # successive created_at timestamps without colliding.
    repo._reference_now = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)  # type: ignore[attr-defined]

    client = TestClient(app)
    yield client, repo, service

    app.dependency_overrides.clear()
    set_research_run_service(None)  # type: ignore[arg-type]


def _seed_run(
    repo,
    *,
    run_id: str,
    strategy_id: str,
    status: str = "queued",
    created_offset_seconds: int = 0,
) -> None:
    """
    Insert a research run into the mock repository with explicit timing.

    Each call increments the seed time by ``created_offset_seconds`` so
    callers can control the newest-first ordering deterministically.

    Args:
        repo: The :class:`MockResearchRunRepository` instance.
        run_id: ULID for the run.
        strategy_id: ULID of the strategy this run belongs to.
        status: Lifecycle status to seed (defaults to QUEUED).
        created_offset_seconds: Seconds to add to the fixture's reference
            time when stamping ``created_at``. Larger numbers = newer.
    """
    from datetime import timedelta
    from decimal import Decimal

    from libs.contracts.research_run import (
        ResearchRunConfig,
        ResearchRunRecord,
        ResearchRunStatus,
        ResearchRunType,
    )

    base = repo._reference_now  # set by the fixture
    created_at = base + timedelta(seconds=created_offset_seconds)
    config = ResearchRunConfig(
        run_type=ResearchRunType.BACKTEST,
        strategy_id=strategy_id,
        symbols=["EURUSD"],
        initial_equity=Decimal("100000"),
    )
    record = ResearchRunRecord(
        id=run_id,
        config=config,
        status=ResearchRunStatus(status),
        created_by="01HTESTFAKE000000000000000",
        created_at=created_at,
        updated_at=created_at,
    )
    repo.create(record)


class TestListStrategyRunsRoute:
    """
    Tests for ``GET /strategies/{strategy_id}/runs``.

    Verifies:
      * Empty store returns ``total_count == 0`` and ``runs == []``.
      * Non-empty store returns one row per run, newest first.
      * Pagination math (``page`` / ``page_size`` / ``total_count`` /
        ``total_pages``) is correct across multiple pages.
      * ``page_size`` above the schema cap returns 422 (FastAPI's ``le``
        validator).
      * The audit log line ``event=strategy_runs_browsed`` is emitted
        per CLAUDE.md §8.
      * Auth is enforced (the route inherits ``strategies:write`` from
        the rest of the strategies router).
    """

    def test_empty_history_returns_total_count_zero(self, strategy_runs_test_env) -> None:
        """A strategy with no runs returns an empty page envelope."""
        client, _repo, _service = strategy_runs_test_env

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/runs?page=1&page_size=20",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["runs"] == []
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total_count"] == 0
        assert data["total_pages"] == 0

    def test_returns_runs_newest_first_with_summary_metrics(self, strategy_runs_test_env) -> None:
        """Non-empty result populates the envelope; row schema is pinned."""
        client, repo, _service = strategy_runs_test_env

        strategy_id = "01HSTRAT0000000000000001"
        # Seed three runs with monotonically increasing created_at so we
        # can assert the newest-first ordering is honoured.
        _seed_run(
            repo,
            run_id="01HRUN0000000000000000001",
            strategy_id=strategy_id,
            status="queued",
            created_offset_seconds=0,
        )
        _seed_run(
            repo,
            run_id="01HRUN0000000000000000002",
            strategy_id=strategy_id,
            status="queued",
            created_offset_seconds=10,
        )
        _seed_run(
            repo,
            run_id="01HRUN0000000000000000003",
            strategy_id=strategy_id,
            status="queued",
            created_offset_seconds=20,
        )

        resp = client.get(
            f"/strategies/{strategy_id}/runs?page=1&page_size=20",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total_count"] == 3
        assert data["total_pages"] == 1
        assert len(data["runs"]) == 3

        # Newest-first ordering: created_offset 20 > 10 > 0.
        assert [r["id"] for r in data["runs"]] == [
            "01HRUN0000000000000000003",
            "01HRUN0000000000000000002",
            "01HRUN0000000000000000001",
        ]

        for row in data["runs"]:
            # Pinned row schema — the frontend table relies on these keys.
            for key in ("id", "status", "started_at", "completed_at", "summary_metrics"):
                assert key in row, f"missing {key} in row {row}"
            for metric_key in ("total_return_pct", "sharpe_ratio", "win_rate", "trade_count"):
                assert metric_key in row["summary_metrics"], (
                    f"missing summary_metrics.{metric_key} in row {row}"
                )
            # Runs without a result body have null metrics + 0 trades.
            assert row["summary_metrics"]["total_return_pct"] is None
            assert row["summary_metrics"]["sharpe_ratio"] is None
            assert row["summary_metrics"]["win_rate"] is None
            assert row["summary_metrics"]["trade_count"] == 0

    def test_pagination_partitions_dataset(self, strategy_runs_test_env) -> None:
        """page + page_size correctly partition the dataset."""
        client, repo, _service = strategy_runs_test_env
        strategy_id = "01HSTRAT0000000000000001"
        for i in range(5):
            _seed_run(
                repo,
                run_id=f"01HRUN000000000000000000{i}",
                strategy_id=strategy_id,
                status="queued",
                created_offset_seconds=i,
            )

        # Page 1 of 3 (page_size=2): 2 rows, total_count=5, total_pages=3.
        resp = client.get(
            f"/strategies/{strategy_id}/runs?page=1&page_size=2",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 5
        assert data["total_pages"] == 3
        assert len(data["runs"]) == 2

        # Page 3: last page, single row.
        resp = client.get(
            f"/strategies/{strategy_id}/runs?page=3&page_size=2",
            headers=_auth_headers(),
        )
        data = resp.json()
        assert data["page"] == 3
        assert len(data["runs"]) == 1
        assert data["total_pages"] == 3

        # Page 4: out-of-range, empty rows but totals still populated.
        resp = client.get(
            f"/strategies/{strategy_id}/runs?page=4&page_size=2",
            headers=_auth_headers(),
        )
        data = resp.json()
        assert data["page"] == 4
        assert data["runs"] == []
        assert data["total_count"] == 5
        assert data["total_pages"] == 3

    def test_filters_to_strategy_id(self, strategy_runs_test_env) -> None:
        """Runs for other strategies are excluded from the response."""
        client, repo, _service = strategy_runs_test_env
        target = "01HSTRAT0000000000000001"
        other = "01HSTRAT0000000000000002"
        _seed_run(
            repo,
            run_id="01HRUN0000000000000000001",
            strategy_id=target,
            status="queued",
            created_offset_seconds=0,
        )
        _seed_run(
            repo,
            run_id="01HRUN0000000000000000002",
            strategy_id=other,
            status="queued",
            created_offset_seconds=10,
        )
        _seed_run(
            repo,
            run_id="01HRUN0000000000000000003",
            strategy_id=target,
            status="queued",
            created_offset_seconds=20,
        )

        resp = client.get(f"/strategies/{target}/runs", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 2
        assert {r["id"] for r in data["runs"]} == {
            "01HRUN0000000000000000001",
            "01HRUN0000000000000000003",
        }

    def test_page_size_above_cap_returns_422(self, strategy_runs_test_env) -> None:
        """``page_size`` above the cap (200) is a 422."""
        client, _repo, _service = strategy_runs_test_env

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/runs?page=1&page_size=999",
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    def test_page_zero_returns_422(self, strategy_runs_test_env) -> None:
        """``page=0`` violates the ``ge=1`` validator."""
        client, _repo, _service = strategy_runs_test_env

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/runs?page=0&page_size=20",
            headers=_auth_headers(),
        )
        assert resp.status_code == 422

    def test_emits_audit_log_on_success(
        self,
        strategy_runs_test_env,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A successful list emits ``event=strategy_runs_browsed`` per CLAUDE.md §8."""
        client, _repo, _service = strategy_runs_test_env
        from services.api.routes import strategies as strategies_module

        captured: list[tuple[str, dict[str, Any]]] = []
        original_info = strategies_module.logger.info

        def _spy_info(event: str, /, **kwargs: Any) -> Any:
            captured.append((event, kwargs))
            return original_info(event, **kwargs)

        monkeypatch.setattr(strategies_module.logger, "info", _spy_info)

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/runs?page=1&page_size=20",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200, resp.text

        audit_calls = [c for c in captured if c[0] == "strategy_runs_browsed"]
        assert len(audit_calls) == 1, (
            f"expected exactly one strategy_runs_browsed audit line, got {len(audit_calls)}: "
            f"{[c[0] for c in captured]}"
        )
        _event, kwargs = audit_calls[0]
        assert kwargs["strategy_id"] == "01HSTRAT0000000000000001"
        assert kwargs["page"] == 1
        assert kwargs["page_size"] == 20
        # CLAUDE.md §8 required structured fields:
        assert "user_id" in kwargs
        assert "correlation_id" in kwargs
        assert kwargs["component"] == "strategies"

    def test_requires_auth(self, strategy_runs_test_env) -> None:
        """Request without auth is rejected before the service runs."""
        client, _repo, _service = strategy_runs_test_env
        app.dependency_overrides.clear()

        resp = client.get("/strategies/01HSTRAT0000000000000001/runs?page=1&page_size=20")
        assert resp.status_code in (401, 403, 422)

    def test_returns_503_when_service_not_configured(self, strategy_runs_test_env) -> None:
        """The route returns 503 when the research-run service is unwired."""
        client, _repo, _service = strategy_runs_test_env
        # Drop the service registration to simulate the unbootstrapped state.
        from services.api.routes.runs import set_research_run_service

        set_research_run_service(None)  # type: ignore[arg-type]

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/runs?page=1&page_size=20",
            headers=_auth_headers(),
        )
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Tests: POST /strategies/{strategy_id}/clone
# ---------------------------------------------------------------------------


class TestCloneStrategyRoute:
    """
    Tests for POST /strategies/{strategy_id}/clone.

    Acceptance per the brief:
    - 201 happy path with the cloned Strategy contract.
    - 404 source-not-found.
    - 409 name-collision (StrategyNameConflictError → HTTP 409).
    - 422 invalid body (empty new_name).
    - 401/403 on missing/insufficient auth.
    """

    def test_clone_returns_201_with_cloned_strategy(self, strategy_test_env) -> None:
        """Happy path: 201 with the cloned strategy in the response body."""
        client, mock_service, _ = strategy_test_env
        # Seed a source row so the clone has something to copy from. The
        # mock service synthesises a row on create so we can grab its id.
        seed = client.post(
            "/strategies/",
            json={
                "name": "Source Strategy",
                "entry_condition": "RSI(14) < 30",
                "exit_condition": "RSI(14) > 70",
            },
            headers=_auth_headers(),
        )
        assert seed.status_code == 201
        source_id = seed.json()["strategy"]["id"]

        resp = client.post(
            f"/strategies/{source_id}/clone",
            json={"new_name": "Source Strategy (copy)"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "strategy" in body
        clone = body["strategy"]
        assert clone["name"] == "Source Strategy (copy)"
        assert clone["id"] != source_id
        assert clone["row_version"] == 1
        assert clone["is_active"] is True
        # The clone is attributed to the operator who clicked the button,
        # mirrored as ``created_by`` in the response.
        assert clone["created_by"] == _OPERATOR_USER.user_id

    def test_clone_returns_404_when_source_missing(self, strategy_test_env) -> None:
        """A NotFoundError from the service maps to HTTP 404."""
        client, mock_service, _ = strategy_test_env
        mock_service.raise_clone_not_found = True

        resp = client.post(
            "/strategies/01HMISSING0000000000000001/clone",
            json={"new_name": "Whatever"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_clone_returns_409_on_name_collision(self, strategy_test_env) -> None:
        """A StrategyNameConflictError from the service maps to HTTP 409."""
        client, mock_service, _ = strategy_test_env
        mock_service.raise_clone_conflict = True

        resp = client.post(
            "/strategies/01HSTRAT0000000000000001/clone",
            json={"new_name": "Already Taken"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 409, resp.text
        # The detail body should mention the colliding name so the UI
        # can render an inline error without re-deriving the message.
        assert "already exists" in resp.json()["detail"].lower()

    def test_clone_with_empty_new_name_returns_422(self, strategy_test_env) -> None:
        """Pydantic body validation rejects an empty ``new_name``."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/01HSTRAT0000000000000001/clone",
            json={"new_name": ""},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_clone_with_overlong_new_name_returns_422(self, strategy_test_env) -> None:
        """A new_name above 255 chars is rejected by the request schema."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/01HSTRAT0000000000000001/clone",
            json={"new_name": "x" * 256},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_clone_requires_auth(self, strategy_test_env) -> None:
        """Request without auth is rejected before the service runs."""
        client, _, _app = strategy_test_env
        _app.dependency_overrides.clear()

        resp = client.post(
            "/strategies/01HSTRAT0000000000000001/clone",
            json={"new_name": "Whatever"},
        )

        assert resp.status_code in (401, 403, 422)

    def test_clone_rejects_user_without_strategies_write_scope(self, strategy_test_env) -> None:
        """A user lacking ``strategies:write`` is rejected with 403."""
        client, _, _app = strategy_test_env
        # Override the auth dependency with a user that holds NO scopes —
        # they are authenticated, but require_scope("strategies:write")
        # raises 403.
        from services.api.auth import get_current_user

        viewer = AuthenticatedUser(
            user_id="01HVEWERFAKE00000000000000",
            email="viewer@fxlab.test",
            role="viewer",
            scopes=set(),
        )

        async def _viewer() -> AuthenticatedUser:
            return viewer

        _app.dependency_overrides[get_current_user] = _viewer

        resp = client.post(
            "/strategies/01HSTRAT0000000000000001/clone",
            json={"new_name": "Whatever"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: POST /strategies/validate-ir (no-save validation)
# ---------------------------------------------------------------------------


class TestValidateStrategyIrRoute:
    """Tests for ``POST /strategies/validate-ir``.

    The endpoint always returns 200 — both pass and fail share the same
    HTTP status because the request itself succeeded; the IR's validity
    is the report payload. Only auth (401/403) and malformed bodies
    (422) yield non-2xx responses.
    """

    def test_validate_ir_valid_returns_200_with_valid_true(self, strategy_test_env) -> None:
        """A valid IR text returns 200 with valid=true and parsed_ir populated."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-ir",
            json={"ir_text": '{"foo": 1, "bar": "baz"}'},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["parsed_ir"] == {"foo": 1, "bar": "baz"}
        assert body["errors"] == []
        assert body["warnings"] == []

    def test_validate_ir_invalid_returns_200_with_errors(self, strategy_test_env) -> None:
        """A schema-violating IR returns 200 with structured errors."""
        client, mock_service, _ = strategy_test_env
        # Force the mock to return the invalid envelope so the route's
        # error-rendering path is exercised regardless of how minimal
        # the mock's default validate_ir is.
        mock_service.validate_ir_force_invalid = True

        resp = client.post(
            "/strategies/validate-ir",
            json={"ir_text": '{"missing_required_fields": true}'},
            headers=_auth_headers(),
        )

        # 200 — the request succeeded; the report carries the verdict.
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["parsed_ir"] is None
        assert len(body["errors"]) >= 1
        first = body["errors"][0]
        # Stable fields the frontend renders inline.
        assert "path" in first
        assert "code" in first
        assert "message" in first

    def test_validate_ir_invalid_json_returns_200_with_invalid_json_code(
        self, strategy_test_env
    ) -> None:
        """Malformed JSON in the textarea returns 200 with code=invalid_json."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-ir",
            json={"ir_text": "{not json}"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is False
        assert body["errors"][0]["code"] == "invalid_json"
        assert body["errors"][0]["path"] == "/"

    def test_validate_ir_empty_body_returns_422(self, strategy_test_env) -> None:
        """An empty request body is rejected by the request schema."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-ir",
            json={},
            headers=_auth_headers(),
        )

        # FastAPI's Pydantic validation surfaces a 422 for the missing
        # ir_text field BEFORE the handler runs.
        assert resp.status_code == 422

    def test_validate_ir_empty_string_returns_422(self, strategy_test_env) -> None:
        """An empty ir_text string fails request-schema validation (min_length=1)."""
        client, _, _ = strategy_test_env

        resp = client.post(
            "/strategies/validate-ir",
            json={"ir_text": ""},
            headers=_auth_headers(),
        )

        assert resp.status_code == 422

    def test_validate_ir_requires_auth(self, strategy_test_env) -> None:
        """Request without auth is rejected before the handler runs."""
        client, _, _app = strategy_test_env
        _app.dependency_overrides.clear()

        resp = client.post(
            "/strategies/validate-ir",
            json={"ir_text": "{}"},
        )

        assert resp.status_code in (401, 403, 422)

    def test_validate_ir_rejects_user_without_strategies_write_scope(
        self, strategy_test_env
    ) -> None:
        """A user without ``strategies:write`` is rejected with 403."""
        client, _, _app = strategy_test_env
        from services.api.auth import get_current_user

        viewer = AuthenticatedUser(
            user_id="01HVEWERFAKE00000000000001",
            email="viewer@fxlab.test",
            role="viewer",
            scopes=set(),
        )

        async def _viewer() -> AuthenticatedUser:
            return viewer

        _app.dependency_overrides[get_current_user] = _viewer

        resp = client.post(
            "/strategies/validate-ir",
            json={"ir_text": "{}"},
            headers=_auth_headers(),
        )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /strategies/{strategy_id}/ir.json (download)
# ---------------------------------------------------------------------------


class TestDownloadStrategyIrJsonRoute:
    """Tests for ``GET /strategies/{strategy_id}/ir.json`` (download endpoint)."""

    def test_download_happy_path_returns_json_with_attachment_header(
        self, strategy_test_env
    ) -> None:
        """A valid strategy returns 200 + JSON body + Content-Disposition."""
        client, _, _ = strategy_test_env

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/ir.json",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        # Content-Type is application/json (the body is JSON, not a
        # binary blob).
        assert "application/json" in resp.headers["content-type"]
        # Content-Disposition is the download trigger; filename embeds
        # the strategy name + the canonical .strategy_ir.json suffix.
        cd = resp.headers["content-disposition"]
        assert cd.startswith("attachment;")
        assert ".strategy_ir.json" in cd
        # Body parses as JSON (the contract is a JSON file).
        body = json.loads(resp.text)
        assert isinstance(body, dict)

    def test_download_filename_uses_strategy_name(self, strategy_test_env) -> None:
        """The Content-Disposition filename hint embeds the strategy's display name."""
        client, _, _ = strategy_test_env

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/ir.json",
            headers=_auth_headers(),
        )

        assert resp.status_code == 200
        # The mock returns "Test Strategy" — sanitisation keeps the
        # space and the alphanumerics, so the filename hint contains
        # "Test Strategy.strategy_ir.json".
        cd = resp.headers["content-disposition"]
        assert "Test Strategy.strategy_ir.json" in cd

    def test_download_unknown_strategy_returns_404(self, strategy_test_env) -> None:
        """A missing strategy id returns 404."""
        client, mock_service, _ = strategy_test_env
        mock_service.raise_not_found = True

        resp = client.get(
            "/strategies/01HMISSING0000000000000001/ir.json",
            headers=_auth_headers(),
        )

        assert resp.status_code == 404

    def test_download_requires_auth(self, strategy_test_env) -> None:
        """Request without auth is rejected before the handler runs."""
        client, _, _app = strategy_test_env
        _app.dependency_overrides.clear()

        resp = client.get("/strategies/01HSTRAT0000000000000001/ir.json")

        assert resp.status_code in (401, 403, 422)

    def test_download_rejects_user_without_strategies_write_scope(self, strategy_test_env) -> None:
        """A user without ``strategies:write`` is rejected with 403."""
        client, _, _app = strategy_test_env
        from services.api.auth import get_current_user

        viewer = AuthenticatedUser(
            user_id="01HVEWERFAKE00000000000002",
            email="viewer@fxlab.test",
            role="viewer",
            scopes=set(),
        )

        async def _viewer() -> AuthenticatedUser:
            return viewer

        _app.dependency_overrides[get_current_user] = _viewer

        resp = client.get(
            "/strategies/01HSTRAT0000000000000001/ir.json",
            headers=_auth_headers(),
        )

        assert resp.status_code == 403

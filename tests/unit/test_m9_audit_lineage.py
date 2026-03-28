"""
Unit tests for M9: Symbol Lineage & Audit Explorer Backend.

Coverage:
- MockAuditExplorerRepository  — behavioural parity with AuditExplorerRepositoryInterface
- MockSymbolLineageRepository  — behavioural parity with SymbolLineageRepositoryInterface
- GET /audit                   — filtered audit event list (actor, action_type, target_type, target_id, limit)
- GET /audit/{audit_event_id}  — single audit event by ULID; 404 on unknown
- GET /symbols/{symbol}/lineage — symbol data provenance; 404 on unknown symbol

All tests MUST FAIL before GREEN (S4) and MUST PASS after GREEN.

Known lessons:
    LL-007: Use str="" (not Optional[str]) for object_id / object_type / next_cursor.
    LL-008: Route handlers use JSONResponse + model_dump(); no response_model=.
    LL-010: Explicit int() cast on Query() parameters before repository calls.
    LL-012: model_construct() to bypass pydantic-core cross-arch Optional[Enum] failure.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from libs.contracts.audit_explorer import AuditEventRecord, AuditExplorerResponse
from libs.contracts.errors import NotFoundError
from libs.contracts.mocks.mock_audit_explorer_repository import (
    MockAuditExplorerRepository,
)
from libs.contracts.mocks.mock_symbol_lineage_repository import (
    MockSymbolLineageRepository,
)
from libs.contracts.symbol_lineage import (
    SymbolFeedRef,
    SymbolLineageResponse,
    SymbolRunRef,
)

# ---------------------------------------------------------------------------
# Shared test data constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)

_AUDIT_ULID_1 = "01HQAUDIT0AAAAAAAAAAAAAAAA1"
_AUDIT_ULID_2 = "01HQAUDIT0BBBBBBBBBBBBBBB2"
_AUDIT_ULID_3 = "01HQAUDIT0CCCCCCCCCCCCCCC3"
_AUDIT_ULID_MISSING = "01HQAUDIT0XXXXXXXXXXXXXXX9"

_RUN_ULID_1 = "01HQRUN0AAAAAAAAAAAAAAAA01"
_RUN_ULID_2 = "01HQRUN0BBBBBBBBBBBBBBB02"

_FEED_ULID_1 = "01HQFEED0AAAAAAAAAAAAAAAA1"
_FEED_ULID_2 = "01HQFEED0BBBBBBBBBBBBBBB2"

_ACTOR_ANALYST = "analyst@fxlab.io"
_ACTOR_SYSTEM = "system:scheduler"


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_audit_record(
    audit_id: str = _AUDIT_ULID_1,
    actor: str = _ACTOR_ANALYST,
    action: str = "run.started",
    object_id: str = _RUN_ULID_1,
    object_type: str = "run",
    correlation_id: str = "corr-001",
) -> AuditEventRecord:
    """
    Build a minimal AuditEventRecord for tests.

    Uses str="" defaults for optional string fields (LL-007).
    Direct construction is safe because no Optional[str-Enum] fields exist here.
    """
    return AuditEventRecord(
        id=audit_id,
        actor=actor,
        action=action,
        object_id=object_id,
        object_type=object_type,
        correlation_id=correlation_id,
        event_metadata={},
        created_at=_NOW,
    )


def _make_symbol_lineage(
    symbol: str = "AAPL",
    feed_ids: list[str] | None = None,
    run_ids: list[str] | None = None,
) -> SymbolLineageResponse:
    """
    Build a minimal SymbolLineageResponse for tests.

    Args:
        symbol:   Instrument ticker.
        feed_ids: List of feed ULIDs to include as SymbolFeedRef objects.
        run_ids:  List of run ULIDs to include as SymbolRunRef objects.
    """
    feeds = [
        SymbolFeedRef(
            feed_id=fid,
            feed_name=f"feed_{fid[-4:]}",
            first_seen=_NOW,
        )
        for fid in (feed_ids or [])
    ]
    runs = [
        SymbolRunRef(run_id=rid, started_at=_NOW)
        for rid in (run_ids or [])
    ]
    return SymbolLineageResponse(
        symbol=symbol,
        feeds=feeds,
        runs=runs,
        generated_at=_NOW,
    )


# ---------------------------------------------------------------------------
# MockAuditExplorerRepository Tests
# ---------------------------------------------------------------------------


class TestMockAuditExplorerRepository:
    """
    Verify MockAuditExplorerRepository honours the AuditExplorerRepositoryInterface contract.

    Tests cover:
    - list() with no filters returns all records.
    - list() actor filter narrows results.
    - list() action_type prefix filter narrows results.
    - list() target_type filter narrows results.
    - list() target_id filter narrows results.
    - list() combined filters narrow correctly (AND semantics).
    - list() limit caps the result set.
    - find_by_id() returns the correct record.
    - find_by_id() raises NotFoundError for unknown ID.
    - clear() removes all stored records.
    - count() reflects current store size.
    """

    def test_list_returns_all_records_when_no_filters(self) -> None:
        """
        GIVEN three saved AuditEventRecords
        WHEN list() is called with no filter arguments
        THEN all three are returned.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1))
        repo.save(_make_audit_record(_AUDIT_ULID_2, actor=_ACTOR_SYSTEM))
        repo.save(_make_audit_record(_AUDIT_ULID_3, action="approve_promotion"))
        result = repo.list(correlation_id="c")
        assert len(result) == 3

    def test_list_filters_by_actor(self) -> None:
        """
        GIVEN two records — one with actor=analyst, one with actor=system
        WHEN list(actor="analyst@fxlab.io") is called
        THEN only the analyst record is returned.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1, actor=_ACTOR_ANALYST))
        repo.save(_make_audit_record(_AUDIT_ULID_2, actor=_ACTOR_SYSTEM))
        result = repo.list(actor=_ACTOR_ANALYST, correlation_id="c")
        assert len(result) == 1
        assert result[0].actor == _ACTOR_ANALYST

    def test_list_filters_by_action_type_prefix(self) -> None:
        """
        GIVEN records with actions 'run.started', 'run.completed', 'approve_promotion'
        WHEN list(action_type="run") is called
        THEN only 'run.*' records are returned.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1, action="run.started"))
        repo.save(_make_audit_record(_AUDIT_ULID_2, action="run.completed"))
        repo.save(_make_audit_record(_AUDIT_ULID_3, action="approve_promotion"))
        result = repo.list(action_type="run", correlation_id="c")
        assert len(result) == 2
        for r in result:
            assert r.action.startswith("run"), f"Unexpected action: {r.action}"

    def test_list_filters_by_target_type(self) -> None:
        """
        GIVEN records with object_type 'run' and 'strategy'
        WHEN list(target_type="run") is called
        THEN only 'run' records are returned.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1, object_type="run"))
        repo.save(
            _make_audit_record(_AUDIT_ULID_2, object_type="strategy", action="strategy.created")
        )
        result = repo.list(target_type="run", correlation_id="c")
        assert len(result) == 1
        assert result[0].object_type == "run"

    def test_list_filters_by_target_id(self) -> None:
        """
        GIVEN two records pointing to different object_ids
        WHEN list(target_id=_RUN_ULID_1) is called
        THEN only the record with object_id=_RUN_ULID_1 is returned.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1, object_id=_RUN_ULID_1))
        repo.save(_make_audit_record(_AUDIT_ULID_2, object_id=_RUN_ULID_2))
        result = repo.list(target_id=_RUN_ULID_1, correlation_id="c")
        assert len(result) == 1
        assert result[0].object_id == _RUN_ULID_1

    def test_list_combined_filters_use_and_semantics(self) -> None:
        """
        GIVEN records that each satisfy only one of two filter conditions
        WHEN list() is called with both filters
        THEN no records are returned (AND semantics — must satisfy both).
        """
        repo = MockAuditExplorerRepository()
        # Record 1: correct actor, wrong action_type
        repo.save(_make_audit_record(_AUDIT_ULID_1, actor=_ACTOR_ANALYST, action="approve_promotion"))
        # Record 2: correct action_type, wrong actor
        repo.save(_make_audit_record(_AUDIT_ULID_2, actor=_ACTOR_SYSTEM, action="run.started"))
        result = repo.list(actor=_ACTOR_ANALYST, action_type="run", correlation_id="c")
        assert result == [], f"Expected no results for mismatched AND filters, got: {result}"

    def test_list_limit_caps_results(self) -> None:
        """
        GIVEN five saved records
        WHEN list(limit=2) is called
        THEN at most 2 records are returned.
        """
        repo = MockAuditExplorerRepository()
        for i, uid in enumerate(
            [
                _AUDIT_ULID_1,
                _AUDIT_ULID_2,
                _AUDIT_ULID_3,
                "01HQAUDIT0DDDDDDDDDDDDDD4",
                "01HQAUDIT0EEEEEEEEEEEEEEE5",
            ]
        ):
            repo.save(_make_audit_record(uid))
        result = repo.list(limit=2, correlation_id="c")
        assert len(result) <= 2

    def test_list_returns_empty_for_empty_repository(self) -> None:
        """
        GIVEN an empty repository
        WHEN list() is called
        THEN an empty list is returned.
        """
        repo = MockAuditExplorerRepository()
        assert repo.list(correlation_id="c") == []

    def test_find_by_id_returns_correct_record(self) -> None:
        """
        GIVEN a saved AuditEventRecord with _AUDIT_ULID_1
        WHEN find_by_id(_AUDIT_ULID_1) is called
        THEN the matching record is returned.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1, actor=_ACTOR_ANALYST))
        result = repo.find_by_id(_AUDIT_ULID_1, correlation_id="c")
        assert result.id == _AUDIT_ULID_1
        assert result.actor == _ACTOR_ANALYST

    def test_find_by_id_raises_not_found_for_unknown_id(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_by_id is called with an unknown ID
        THEN NotFoundError is raised.
        """
        repo = MockAuditExplorerRepository()
        with pytest.raises(NotFoundError, match=_AUDIT_ULID_MISSING):
            repo.find_by_id(_AUDIT_ULID_MISSING, correlation_id="c")

    def test_clear_removes_all_records(self) -> None:
        """
        GIVEN a populated repository
        WHEN clear() is called
        THEN count() returns 0.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1))
        repo.save(_make_audit_record(_AUDIT_ULID_2))
        repo.clear()
        assert repo.count() == 0

    def test_count_reflects_saved_records(self) -> None:
        """
        GIVEN two records saved
        WHEN count() is called
        THEN 2 is returned.
        """
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1))
        repo.save(_make_audit_record(_AUDIT_ULID_2))
        assert repo.count() == 2


# ---------------------------------------------------------------------------
# MockSymbolLineageRepository Tests
# ---------------------------------------------------------------------------


class TestMockSymbolLineageRepository:
    """
    Verify MockSymbolLineageRepository honours the SymbolLineageRepositoryInterface contract.

    Tests cover:
    - find_by_symbol() returns the correct SymbolLineageResponse.
    - find_by_symbol() raises NotFoundError for unknown symbols.
    - save() overwrites duplicate symbol keys.
    - clear() removes all stored records.
    - count() reflects current store size.
    """

    def test_find_by_symbol_returns_correct_record(self) -> None:
        """
        GIVEN a saved SymbolLineageResponse for 'AAPL'
        WHEN find_by_symbol('AAPL') is called
        THEN the matching response is returned.
        """
        repo = MockSymbolLineageRepository()
        lineage = _make_symbol_lineage("AAPL", feed_ids=[_FEED_ULID_1])
        repo.save(lineage)
        result = repo.find_by_symbol("AAPL", correlation_id="c")
        assert result.symbol == "AAPL"
        assert len(result.feeds) == 1
        assert result.feeds[0].feed_id == _FEED_ULID_1

    def test_find_by_symbol_raises_not_found_for_unknown_symbol(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_by_symbol('UNKNOWN') is called
        THEN NotFoundError is raised.
        """
        repo = MockSymbolLineageRepository()
        with pytest.raises(NotFoundError, match="UNKNOWN"):
            repo.find_by_symbol("UNKNOWN", correlation_id="c")

    def test_save_overwrites_existing_symbol(self) -> None:
        """
        GIVEN a saved SymbolLineageResponse for 'AAPL' with one feed
        WHEN a second save() is called for 'AAPL' with two feeds
        THEN find_by_symbol returns the updated response.
        """
        repo = MockSymbolLineageRepository()
        repo.save(_make_symbol_lineage("AAPL", feed_ids=[_FEED_ULID_1]))
        repo.save(_make_symbol_lineage("AAPL", feed_ids=[_FEED_ULID_1, _FEED_ULID_2]))
        result = repo.find_by_symbol("AAPL", correlation_id="c")
        assert len(result.feeds) == 2

    def test_clear_removes_all_records(self) -> None:
        """
        GIVEN two symbols saved
        WHEN clear() is called
        THEN count() returns 0 and find_by_symbol raises NotFoundError.
        """
        repo = MockSymbolLineageRepository()
        repo.save(_make_symbol_lineage("AAPL"))
        repo.save(_make_symbol_lineage("GOOG"))
        repo.clear()
        assert repo.count() == 0
        with pytest.raises(NotFoundError):
            repo.find_by_symbol("AAPL", correlation_id="c")

    def test_count_reflects_saved_records(self) -> None:
        """
        GIVEN two symbols saved
        WHEN count() is called
        THEN 2 is returned.
        """
        repo = MockSymbolLineageRepository()
        repo.save(_make_symbol_lineage("AAPL"))
        repo.save(_make_symbol_lineage("MSFT"))
        assert repo.count() == 2


# ---------------------------------------------------------------------------
# GET /audit — audit explorer list endpoint tests
# ---------------------------------------------------------------------------


class TestAuditExplorerEndpoint:
    """
    Unit tests for GET /audit.

    The endpoint must:
    - Return 200 with 'events', 'next_cursor', 'total_count', 'generated_at' keys.
    - Return all events when no query parameters are provided.
    - Filter by actor query parameter.
    - Filter by target_type query parameter.
    - Return empty events list when repository is empty.
    - Respect limit query parameter.

    FAILS: enhanced audit.py route (get_audit_explorer_repository DI provider)
           does not exist until GREEN (S4).
    """

    @pytest.fixture
    def audit_repo(self) -> MockAuditExplorerRepository:
        """Repository with three audit records covering different actors and types."""
        repo = MockAuditExplorerRepository()
        repo.save(_make_audit_record(_AUDIT_ULID_1, actor=_ACTOR_ANALYST, action="run.started", object_type="run"))
        repo.save(
            _make_audit_record(
                _AUDIT_ULID_2,
                actor=_ACTOR_SYSTEM,
                action="run.completed",
                object_type="run",
            )
        )
        repo.save(
            _make_audit_record(
                _AUDIT_ULID_3,
                actor=_ACTOR_ANALYST,
                action="approve_promotion",
                object_type="promotion_request",
            )
        )
        return repo

    @pytest.fixture
    def client(self, audit_repo: MockAuditExplorerRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.audit import get_audit_explorer_repository

        app.dependency_overrides[get_audit_explorer_repository] = lambda: audit_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_audit_list_returns_200(self, client: TestClient) -> None:
        """
        GIVEN audit records in the repository
        WHEN GET /audit is requested
        THEN 200 is returned.

        FAILS: enhanced audit.py does not exist until GREEN.
        """
        resp = client.get("/audit")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

    def test_audit_list_contains_required_keys(self, client: TestClient) -> None:
        """
        GIVEN audit records in the repository
        WHEN GET /audit is requested
        THEN response contains 'events', 'next_cursor', 'total_count', 'generated_at'.
        """
        resp = client.get("/audit")
        body = resp.json()
        for key in ("events", "next_cursor", "total_count", "generated_at"):
            assert key in body, f"Missing key '{key}': {body}"

    def test_audit_list_returns_all_records_with_no_filters(
        self, client: TestClient
    ) -> None:
        """
        GIVEN three records in the repository
        WHEN GET /audit is requested with no query parameters
        THEN total_count is 3 and events list has 3 items.
        """
        resp = client.get("/audit")
        body = resp.json()
        assert body["total_count"] == 3, f"total_count wrong: {body}"
        assert len(body["events"]) == 3, f"events length wrong: {body}"

    def test_audit_list_filters_by_actor_query_param(self, client: TestClient) -> None:
        """
        GIVEN three records where 2 have actor=analyst@fxlab.io
        WHEN GET /audit?actor=analyst@fxlab.io is requested
        THEN total_count is 2.
        """
        resp = client.get("/audit", params={"actor": _ACTOR_ANALYST})
        body = resp.json()
        assert body["total_count"] == 2, f"Expected 2 analyst records: {body}"
        assert len(body["events"]) == 2
        for ev in body["events"]:
            assert ev["actor"] == _ACTOR_ANALYST, f"Wrong actor: {ev}"

    def test_audit_list_filters_by_target_type_query_param(
        self, client: TestClient
    ) -> None:
        """
        GIVEN three records where 2 have object_type='run'
        WHEN GET /audit?target_type=run is requested
        THEN total_count is 2.
        """
        resp = client.get("/audit", params={"target_type": "run"})
        body = resp.json()
        assert body["total_count"] == 2, f"Expected 2 run records: {body}"

    def test_audit_list_empty_repository_returns_zero_count(self) -> None:
        """
        GIVEN no records in the repository
        WHEN GET /audit is requested
        THEN events is [] and total_count is 0.

        FAILS: enhanced audit.py does not exist until GREEN.
        """
        from services.api.main import app
        from services.api.routes.audit import get_audit_explorer_repository

        empty_repo = MockAuditExplorerRepository()
        app.dependency_overrides[get_audit_explorer_repository] = lambda: empty_repo
        tc = TestClient(app)
        try:
            resp = tc.get("/audit")
            body = resp.json()
            assert resp.status_code == 200
            assert body.get("events") == []
            assert body.get("total_count") == 0
        finally:
            app.dependency_overrides.clear()

    def test_audit_list_each_event_has_required_fields(
        self, client: TestClient
    ) -> None:
        """
        GIVEN records in the repository
        WHEN GET /audit is requested
        THEN each event has all required AuditEventRecord fields.
        """
        resp = client.get("/audit")
        body = resp.json()
        required = ("id", "actor", "action", "object_id", "object_type", "created_at")
        for ev in body["events"]:
            for field in required:
                assert field in ev, f"Missing field '{field}' in event: {ev}"


# ---------------------------------------------------------------------------
# GET /audit/{audit_event_id} — single audit event endpoint tests
# ---------------------------------------------------------------------------


class TestAuditEventDetailEndpoint:
    """
    Unit tests for GET /audit/{audit_event_id}.

    The endpoint must:
    - Return 200 with all AuditEventRecord fields for a known ID.
    - Return 404 for an unknown ID.
    - Propagate actor, action, object_id, object_type, correlation_id correctly.

    FAILS: enhanced audit.py with find_by_id route does not exist until GREEN (S4).
    """

    @pytest.fixture
    def audit_repo_single(self) -> MockAuditExplorerRepository:
        """Repository with a single audit record."""
        repo = MockAuditExplorerRepository()
        repo.save(
            _make_audit_record(
                _AUDIT_ULID_1,
                actor=_ACTOR_ANALYST,
                action="approve_promotion",
                object_id=_RUN_ULID_1,
                object_type="promotion_request",
                correlation_id="corr-xyz",
            )
        )
        return repo

    @pytest.fixture
    def client(self, audit_repo_single: MockAuditExplorerRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.audit import get_audit_explorer_repository

        app.dependency_overrides[get_audit_explorer_repository] = (
            lambda: audit_repo_single
        )
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_audit_detail_returns_200_for_known_id(self, client: TestClient) -> None:
        """
        GIVEN a saved record with _AUDIT_ULID_1
        WHEN GET /audit/{_AUDIT_ULID_1} is requested
        THEN 200 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client.get(f"/audit/{_AUDIT_ULID_1}")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

    def test_audit_detail_contains_required_fields(self, client: TestClient) -> None:
        """
        GIVEN a saved record with _AUDIT_ULID_1
        WHEN GET /audit/{_AUDIT_ULID_1} is requested
        THEN response body contains all required AuditEventRecord fields.
        """
        resp = client.get(f"/audit/{_AUDIT_ULID_1}")
        body = resp.json()
        for field in ("id", "actor", "action", "object_id", "object_type", "created_at"):
            assert field in body, f"Missing field '{field}': {body}"

    def test_audit_detail_fields_match_saved_record(self, client: TestClient) -> None:
        """
        GIVEN a saved record with specific actor and action
        WHEN GET /audit/{_AUDIT_ULID_1} is requested
        THEN returned actor and action match the saved values.
        """
        resp = client.get(f"/audit/{_AUDIT_ULID_1}")
        body = resp.json()
        assert body["actor"] == _ACTOR_ANALYST, f"actor mismatch: {body}"
        assert body["action"] == "approve_promotion", f"action mismatch: {body}"
        assert body["object_id"] == _RUN_ULID_1, f"object_id mismatch: {body}"
        assert body["object_type"] == "promotion_request", f"object_type mismatch: {body}"

    def test_audit_detail_returns_404_for_unknown_id(self, client: TestClient) -> None:
        """
        GIVEN no record with _AUDIT_ULID_MISSING
        WHEN GET /audit/{_AUDIT_ULID_MISSING} is requested
        THEN 404 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client.get(f"/audit/{_AUDIT_ULID_MISSING}")
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# GET /symbols/{symbol}/lineage — symbol lineage endpoint tests
# ---------------------------------------------------------------------------


class TestSymbolLineageEndpoint:
    """
    Unit tests for GET /symbols/{symbol}/lineage.

    The endpoint must:
    - Return 200 with 'symbol', 'feeds', 'runs', 'generated_at' keys for a known symbol.
    - Return 404 for an unknown symbol.
    - Correctly serialize SymbolFeedRef and SymbolRunRef objects.
    - Return empty feeds and runs lists for a symbol with no associations.

    FAILS: services/api/routes/symbol_lineage.py does not exist until GREEN (S4).
    """

    @pytest.fixture
    def lineage_repo(self) -> MockSymbolLineageRepository:
        """Repository with AAPL lineage (two feeds, one run)."""
        repo = MockSymbolLineageRepository()
        repo.save(
            _make_symbol_lineage(
                "AAPL",
                feed_ids=[_FEED_ULID_1, _FEED_ULID_2],
                run_ids=[_RUN_ULID_1],
            )
        )
        return repo

    @pytest.fixture
    def client(self, lineage_repo: MockSymbolLineageRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.symbol_lineage import get_symbol_lineage_repository

        app.dependency_overrides[get_symbol_lineage_repository] = lambda: lineage_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_symbol_lineage_returns_200_for_known_symbol(
        self, client: TestClient
    ) -> None:
        """
        GIVEN AAPL lineage is saved
        WHEN GET /symbols/AAPL/lineage is requested
        THEN 200 is returned.

        FAILS: route does not exist until GREEN.
        """
        resp = client.get("/symbols/AAPL/lineage")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )

    def test_symbol_lineage_contains_required_keys(self, client: TestClient) -> None:
        """
        GIVEN AAPL lineage is saved
        WHEN GET /symbols/AAPL/lineage is requested
        THEN response contains 'symbol', 'feeds', 'runs', 'generated_at'.
        """
        resp = client.get("/symbols/AAPL/lineage")
        body = resp.json()
        for key in ("symbol", "feeds", "runs", "generated_at"):
            assert key in body, f"Missing key '{key}': {body}"

    def test_symbol_lineage_symbol_field_matches(self, client: TestClient) -> None:
        """
        GIVEN AAPL lineage is saved
        WHEN GET /symbols/AAPL/lineage is requested
        THEN 'symbol' field in response is 'AAPL'.
        """
        resp = client.get("/symbols/AAPL/lineage")
        body = resp.json()
        assert body["symbol"] == "AAPL", f"symbol field wrong: {body}"

    def test_symbol_lineage_feeds_list_has_correct_count(
        self, client: TestClient
    ) -> None:
        """
        GIVEN AAPL lineage with two feeds
        WHEN GET /symbols/AAPL/lineage is requested
        THEN 'feeds' list has 2 items.
        """
        resp = client.get("/symbols/AAPL/lineage")
        body = resp.json()
        assert len(body["feeds"]) == 2, f"Expected 2 feeds: {body}"

    def test_symbol_lineage_feeds_have_required_fields(
        self, client: TestClient
    ) -> None:
        """
        GIVEN AAPL lineage with feeds
        WHEN GET /symbols/AAPL/lineage is requested
        THEN each feed has 'feed_id', 'feed_name', 'first_seen' fields.
        """
        resp = client.get("/symbols/AAPL/lineage")
        body = resp.json()
        for feed in body["feeds"]:
            for field in ("feed_id", "feed_name", "first_seen"):
                assert field in feed, f"Missing field '{field}' in feed: {feed}"

    def test_symbol_lineage_runs_list_has_correct_count(
        self, client: TestClient
    ) -> None:
        """
        GIVEN AAPL lineage with one run
        WHEN GET /symbols/AAPL/lineage is requested
        THEN 'runs' list has 1 item.
        """
        resp = client.get("/symbols/AAPL/lineage")
        body = resp.json()
        assert len(body["runs"]) == 1, f"Expected 1 run: {body}"

    def test_symbol_lineage_runs_have_required_fields(
        self, client: TestClient
    ) -> None:
        """
        GIVEN AAPL lineage with runs
        WHEN GET /symbols/AAPL/lineage is requested
        THEN each run has 'run_id' and 'started_at' fields.
        """
        resp = client.get("/symbols/AAPL/lineage")
        body = resp.json()
        for run in body["runs"]:
            for field in ("run_id", "started_at"):
                assert field in run, f"Missing field '{field}' in run: {run}"

    def test_symbol_lineage_returns_404_for_unknown_symbol(
        self, client: TestClient
    ) -> None:
        """
        GIVEN no lineage saved for 'UNKNOWN'
        WHEN GET /symbols/UNKNOWN/lineage is requested
        THEN 404 is returned.

        FAILS: route does not exist until GREEN.
        """
        resp = client.get("/symbols/UNKNOWN/lineage")
        assert resp.status_code == 404, (
            f"Expected 404, got {resp.status_code}: {resp.text}"
        )

    def test_symbol_lineage_empty_feeds_and_runs_when_none_saved(self) -> None:
        """
        GIVEN a symbol saved with no feeds and no runs
        WHEN GET /symbols/{symbol}/lineage is requested
        THEN feeds is [] and runs is [].

        FAILS: route does not exist until GREEN.
        """
        from services.api.main import app
        from services.api.routes.symbol_lineage import get_symbol_lineage_repository

        bare_repo = MockSymbolLineageRepository()
        bare_repo.save(_make_symbol_lineage("BARE"))
        app.dependency_overrides[get_symbol_lineage_repository] = lambda: bare_repo
        tc = TestClient(app)
        try:
            resp = tc.get("/symbols/BARE/lineage")
            body = resp.json()
            assert resp.status_code == 200
            assert body.get("feeds") == []
            assert body.get("runs") == []
        finally:
            app.dependency_overrides.clear()

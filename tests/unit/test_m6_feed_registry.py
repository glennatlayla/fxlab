"""
Unit tests for M6: Feed Registry + Versioned Config + Connectivity Tests.

Coverage:
- GET /feeds              — paginated feed list endpoint
- GET /feeds/{feed_id}    — feed detail with version history + connectivity tests
- GET /feed-health        — health summary for all registered feeds
- MockFeedRepository      — behavioural parity with FeedRepositoryInterface
- MockFeedHealthRepository — behavioural parity with FeedHealthRepositoryInterface

All tests MUST FAIL on a stub implementation and MUST PASS after the GREEN step.

Fixtures used (from tests/conftest.py):
- correlation_id: fresh ULID string

LL-007 note: Use model_construct() for Pydantic models with Optional[str] fields.
             Use model_dump() + JSONResponse in route handlers (LL-008 pattern).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from libs.contracts.errors import NotFoundError
from libs.contracts.feed import (
    ConnectivityStatus,
    FeedConfigVersion,
    FeedConnectivityResult,
    FeedDetailResponse,
    FeedListResponse,
    FeedResponse,
)
from libs.contracts.feed_health import Anomaly, AnomalyType, FeedHealthReport, FeedHealthStatus
from libs.contracts.mocks.mock_feed_health_repository import MockFeedHealthRepository
from libs.contracts.mocks.mock_feed_repository import MockFeedRepository

# ---------------------------------------------------------------------------
# Shared test data constants
# ---------------------------------------------------------------------------

_FEED_ULID_1 = "01HQFEEDAAAAAAAAAAAAAAAAA1"
_FEED_ULID_2 = "01HQFEEDBBBBBBBBBBBBBBBBBB"
_FEED_ULID_3 = "01HQFEEDCCCCCCCCCCCCCCCCCC"
_USER_ULID = "01HQUUUUUUUUUUUUUUUUUUUUUU"
_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)


def _make_feed_response(
    feed_id: str = _FEED_ULID_1,
    name: str = "binance-btcusd",
    provider: str = "Binance",
    is_active: bool = True,
    is_quarantined: bool = False,
) -> FeedResponse:
    """Build a minimal valid FeedResponse for tests."""
    return FeedResponse(
        id=feed_id,
        name=name,
        provider=provider,
        config={"symbol": "BTC/USD", "interval": "1m"},
        is_active=is_active,
        is_quarantined=is_quarantined,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_feed_detail(
    feed_id: str = _FEED_ULID_1,
    name: str = "binance-btcusd",
    with_versions: bool = True,
    with_connectivity: bool = True,
) -> FeedDetailResponse:
    """Build a FeedDetailResponse with optional version history and connectivity tests."""
    feed = _make_feed_response(feed_id=feed_id, name=name)

    # LL-007: use model_construct() for models with Optional[str] fields
    # (change_summary and error_message) to bypass pydantic-core stub failure.
    versions = (
        [
            FeedConfigVersion.model_construct(
                version=1,
                config={"symbol": "BTC/USD", "interval": "5m"},
                created_at=_NOW,
                created_by=_USER_ULID,
                change_summary="Initial config",
            ),
            FeedConfigVersion.model_construct(
                version=2,
                config={"symbol": "BTC/USD", "interval": "1m"},
                created_at=_NOW,
                created_by=_USER_ULID,
                change_summary="Reduced interval to 1m",
            ),
        ]
        if with_versions
        else []
    )

    connectivity = (
        [
            FeedConnectivityResult.model_construct(
                id="01HQCONNAAAAAAAAAAAAAAAAA1",
                feed_id=feed_id,
                tested_at=_NOW,
                status=ConnectivityStatus.OK,
                latency_ms=42,
                error_message=None,
            )
        ]
        if with_connectivity
        else []
    )

    return FeedDetailResponse(
        feed=feed,
        version_history=versions,
        connectivity_tests=connectivity,
    )


def _make_health_report(
    feed_id: str = _FEED_ULID_1,
    status: FeedHealthStatus = FeedHealthStatus.HEALTHY,
) -> FeedHealthReport:
    """Build a minimal FeedHealthReport for tests."""
    return FeedHealthReport(
        feed_id=feed_id,
        status=status,
        last_update=_NOW,
        recent_anomalies=[],
    )


# ---------------------------------------------------------------------------
# MockFeedRepository — behavioural tests
# ---------------------------------------------------------------------------


class TestMockFeedRepository:
    """
    Verify MockFeedRepository honours the FeedRepositoryInterface contract.

    These tests serve dual duty: they specify required behaviour AND validate
    the mock so it stays in sync with the real repository.
    """

    def test_save_and_find_by_id_round_trips_detail(self) -> None:
        """
        GIVEN a freshly saved FeedDetailResponse
        WHEN find_by_id is called with its feed id
        THEN the same detail is returned.
        """
        repo = MockFeedRepository()
        detail = _make_feed_detail()
        repo.save(detail)
        found = repo.find_by_id(_FEED_ULID_1, correlation_id="corr-1")
        assert found.feed.id == _FEED_ULID_1
        assert found.feed.name == "binance-btcusd"

    def test_find_by_id_raises_not_found_for_unknown_id(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_by_id is called with any id
        THEN NotFoundError is raised.
        """
        repo = MockFeedRepository()
        with pytest.raises(NotFoundError, match=_FEED_ULID_1):
            repo.find_by_id(_FEED_ULID_1, correlation_id="corr-1")

    def test_list_returns_all_feeds_without_pagination(self) -> None:
        """
        GIVEN three saved feeds
        WHEN list() is called with a large limit
        THEN all three are returned.
        """
        repo = MockFeedRepository()
        for fid, name in [
            (_FEED_ULID_1, "feed-a"),
            (_FEED_ULID_2, "feed-b"),
            (_FEED_ULID_3, "feed-c"),
        ]:
            repo.save(_make_feed_detail(feed_id=fid, name=name))

        resp = repo.list(limit=100, offset=0, correlation_id="corr-1")
        assert resp.total_count == 3
        assert len(resp.feeds) == 3

    def test_list_paginates_with_limit(self) -> None:
        """
        GIVEN three saved feeds
        WHEN list() is called with limit=2 offset=0
        THEN two feeds are returned and total_count is 3.
        """
        repo = MockFeedRepository()
        for fid, name in [
            (_FEED_ULID_1, "feed-a"),
            (_FEED_ULID_2, "feed-b"),
            (_FEED_ULID_3, "feed-c"),
        ]:
            repo.save(_make_feed_detail(feed_id=fid, name=name))

        resp = repo.list(limit=2, offset=0, correlation_id="corr-1")
        assert resp.total_count == 3
        assert len(resp.feeds) == 2
        assert resp.limit == 2
        assert resp.offset == 0

    def test_list_paginates_with_offset(self) -> None:
        """
        GIVEN three saved feeds
        WHEN list() is called with limit=10 offset=2
        THEN one feed is returned.
        """
        repo = MockFeedRepository()
        for fid, name in [
            (_FEED_ULID_1, "feed-a"),
            (_FEED_ULID_2, "feed-b"),
            (_FEED_ULID_3, "feed-c"),
        ]:
            repo.save(_make_feed_detail(feed_id=fid, name=name))

        resp = repo.list(limit=10, offset=2, correlation_id="corr-1")
        assert resp.total_count == 3
        assert len(resp.feeds) == 1

    def test_find_by_id_returns_version_history(self) -> None:
        """
        GIVEN a feed saved with two version history entries
        WHEN find_by_id is called
        THEN version_history has two entries in the correct order.
        """
        repo = MockFeedRepository()
        repo.save(_make_feed_detail(_FEED_ULID_1, with_versions=True))
        detail = repo.find_by_id(_FEED_ULID_1, correlation_id="corr-1")
        assert len(detail.version_history) == 2
        assert detail.version_history[0].version == 1
        assert detail.version_history[1].version == 2

    def test_find_by_id_returns_connectivity_tests(self) -> None:
        """
        GIVEN a feed saved with one connectivity test result
        WHEN find_by_id is called
        THEN connectivity_tests has one entry with status OK.
        """
        repo = MockFeedRepository()
        repo.save(_make_feed_detail(_FEED_ULID_1, with_connectivity=True))
        detail = repo.find_by_id(_FEED_ULID_1, correlation_id="corr-1")
        assert len(detail.connectivity_tests) == 1
        assert detail.connectivity_tests[0].status == ConnectivityStatus.OK

    def test_count_reflects_saved_feeds(self) -> None:
        """
        GIVEN two saved feeds
        WHEN count() is called
        THEN it returns 2.
        """
        repo = MockFeedRepository()
        repo.save(_make_feed_detail(_FEED_ULID_1))
        repo.save(_make_feed_detail(_FEED_ULID_2, name="other-feed"))
        assert repo.count() == 2

    def test_clear_empties_store(self) -> None:
        """
        GIVEN a repository with saved feeds
        WHEN clear() is called
        THEN count() returns 0 and find_by_id raises NotFoundError.
        """
        repo = MockFeedRepository()
        repo.save(_make_feed_detail(_FEED_ULID_1))
        repo.clear()
        assert repo.count() == 0
        with pytest.raises(NotFoundError):
            repo.find_by_id(_FEED_ULID_1, correlation_id="corr-1")

    def test_save_with_empty_id_raises_value_error(self) -> None:
        """
        GIVEN a FeedDetailResponse with an empty feed.id
        WHEN save() is called
        THEN ValueError is raised.
        """
        repo = MockFeedRepository()
        bad_feed = FeedResponse(
            id="",
            name="bad",
            provider="X",
            config={},
            is_active=True,
            is_quarantined=False,
            created_at=_NOW,
            updated_at=_NOW,
        )
        bad_detail = FeedDetailResponse(feed=bad_feed)
        with pytest.raises(ValueError):
            repo.save(bad_detail)

    def test_all_returns_every_saved_detail(self) -> None:
        """
        GIVEN two saved feeds
        WHEN all() is called
        THEN both FeedDetailResponse objects are returned.
        """
        repo = MockFeedRepository()
        repo.save(_make_feed_detail(_FEED_ULID_1, name="feed-a"))
        repo.save(_make_feed_detail(_FEED_ULID_2, name="feed-b"))
        all_details = repo.all()
        assert len(all_details) == 2
        ids = {d.feed.id for d in all_details}
        assert _FEED_ULID_1 in ids
        assert _FEED_ULID_2 in ids


# ---------------------------------------------------------------------------
# MockFeedHealthRepository — behavioural tests
# ---------------------------------------------------------------------------


class TestMockFeedHealthRepository:
    """
    Verify MockFeedHealthRepository honours the FeedHealthRepositoryInterface.
    """

    def test_save_and_get_health_round_trips(self) -> None:
        """
        GIVEN a saved FeedHealthReport
        WHEN get_health_by_feed_id is called
        THEN the same report is returned.
        """
        repo = MockFeedHealthRepository()
        report = _make_health_report(_FEED_ULID_1, FeedHealthStatus.HEALTHY)
        repo.save(report)
        found = repo.get_health_by_feed_id(_FEED_ULID_1, correlation_id="corr-1")
        assert found.feed_id == _FEED_ULID_1
        assert found.status == FeedHealthStatus.HEALTHY

    def test_get_health_raises_not_found_for_unknown_feed(self) -> None:
        """
        GIVEN an empty repository
        WHEN get_health_by_feed_id is called
        THEN NotFoundError is raised.
        """
        repo = MockFeedHealthRepository()
        with pytest.raises(NotFoundError, match=_FEED_ULID_1):
            repo.get_health_by_feed_id(_FEED_ULID_1, correlation_id="corr-1")

    def test_get_all_health_returns_all_reports(self) -> None:
        """
        GIVEN two saved health reports
        WHEN get_all_health is called
        THEN both are returned in the FeedHealthListResponse.
        """
        repo = MockFeedHealthRepository()
        repo.save(_make_health_report(_FEED_ULID_1, FeedHealthStatus.HEALTHY))
        repo.save(_make_health_report(_FEED_ULID_2, FeedHealthStatus.DEGRADED))
        summary = repo.get_all_health(correlation_id="corr-1")
        assert len(summary.feeds) == 2

    def test_get_all_health_includes_generated_at(self) -> None:
        """
        GIVEN any repository state
        WHEN get_all_health is called
        THEN the response includes a generated_at UTC timestamp.
        """
        repo = MockFeedHealthRepository()
        summary = repo.get_all_health(correlation_id="corr-1")
        assert isinstance(summary.generated_at, datetime)
        assert summary.generated_at.tzinfo is not None

    def test_get_all_health_returns_empty_list_when_no_reports(self) -> None:
        """
        GIVEN an empty repository
        WHEN get_all_health is called
        THEN feeds list is empty and response is still valid.
        """
        repo = MockFeedHealthRepository()
        summary = repo.get_all_health(correlation_id="corr-1")
        assert summary.feeds == []

    def test_count_reflects_saved_reports(self) -> None:
        """
        GIVEN two saved reports
        WHEN count() is called
        THEN it returns 2.
        """
        repo = MockFeedHealthRepository()
        repo.save(_make_health_report(_FEED_ULID_1))
        repo.save(_make_health_report(_FEED_ULID_2))
        assert repo.count() == 2

    def test_clear_empties_store(self) -> None:
        """
        GIVEN a repository with saved reports
        WHEN clear() is called
        THEN count() returns 0.
        """
        repo = MockFeedHealthRepository()
        repo.save(_make_health_report(_FEED_ULID_1))
        repo.clear()
        assert repo.count() == 0


# ---------------------------------------------------------------------------
# GET /feeds — route handler tests
# ---------------------------------------------------------------------------


class TestFeedsListEndpoint:
    """
    Unit tests for GET /feeds.

    The endpoint must:
    - Return 200 with a feeds list and total_count.
    - Support limit and offset query parameters for pagination.
    - Delegate all data access to the injected FeedRepositoryInterface.
    """

    @pytest.fixture
    def repo(self) -> MockFeedRepository:
        """Provide a pre-populated in-memory repository."""
        r = MockFeedRepository()
        r.save(_make_feed_detail(_FEED_ULID_1, name="binance-btcusd"))
        r.save(_make_feed_detail(_FEED_ULID_2, name="alpaca-ethusd"))
        return r

    @pytest.fixture
    def client(self, repo: MockFeedRepository) -> TestClient:
        """Build a TestClient with the feed repo dependency overridden."""
        from services.api.main import app
        from services.api.routes.feeds import get_feed_repository

        app.dependency_overrides[get_feed_repository] = lambda: repo
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_get_feeds_returns_200(self, client: TestClient) -> None:
        """
        GIVEN two registered feeds
        WHEN GET /feeds is requested
        THEN 200 is returned.

        FAILS: feeds.py stub does not use FeedRepositoryInterface.
        """
        resp = client.get("/feeds")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_get_feeds_returns_feeds_list(self, client: TestClient) -> None:
        """
        GIVEN two registered feeds
        WHEN GET /feeds is requested
        THEN response contains a 'feeds' key with 2 items.

        FAILS: stub returns {}.
        """
        resp = client.get("/feeds")
        body = resp.json()
        assert "feeds" in body, f"Expected 'feeds' key in response: {body}"
        assert len(body["feeds"]) == 2

    def test_get_feeds_returns_total_count(self, client: TestClient) -> None:
        """
        GIVEN two registered feeds
        WHEN GET /feeds is requested
        THEN total_count == 2.
        """
        resp = client.get("/feeds")
        body = resp.json()
        assert body.get("total_count") == 2

    def test_get_feeds_supports_limit(self, client: TestClient) -> None:
        """
        GIVEN two registered feeds
        WHEN GET /feeds?limit=1 is requested
        THEN one feed is returned and total_count is still 2.
        """
        resp = client.get("/feeds?limit=1")
        body = resp.json()
        assert len(body["feeds"]) == 1
        assert body["total_count"] == 2

    def test_get_feeds_supports_offset(self, client: TestClient) -> None:
        """
        GIVEN two registered feeds
        WHEN GET /feeds?offset=1 is requested
        THEN one feed is returned.
        """
        resp = client.get("/feeds?offset=1")
        body = resp.json()
        assert len(body["feeds"]) == 1

    def test_get_feeds_each_item_has_required_fields(self, client: TestClient) -> None:
        """
        GIVEN registered feeds
        WHEN GET /feeds is requested
        THEN each item contains id, name, provider, is_active, is_quarantined.
        """
        resp = client.get("/feeds")
        body = resp.json()
        required = {"id", "name", "provider", "is_active", "is_quarantined"}
        for item in body["feeds"]:
            missing = required - set(item.keys())
            assert not missing, f"Item missing fields: {missing}"

    def test_get_feeds_empty_repository_returns_empty_list(self) -> None:
        """
        GIVEN an empty feed repository
        WHEN GET /feeds is requested
        THEN feeds is [] and total_count is 0.
        """
        from services.api.main import app
        from services.api.routes.feeds import get_feed_repository

        empty_repo = MockFeedRepository()
        app.dependency_overrides[get_feed_repository] = lambda: empty_repo
        client = TestClient(app)
        try:
            resp = client.get("/feeds")
            body = resp.json()
            assert body["feeds"] == []
            assert body["total_count"] == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /feeds/{feed_id} — feed detail endpoint tests
# ---------------------------------------------------------------------------


class TestFeedDetailEndpoint:
    """
    Unit tests for GET /feeds/{feed_id}.

    The endpoint must:
    - Return 200 with feed metadata, version_history, and connectivity_tests.
    - Return 404 when the feed_id does not exist.
    - Delegate all data access to the injected FeedRepositoryInterface.
    """

    @pytest.fixture
    def repo(self) -> MockFeedRepository:
        r = MockFeedRepository()
        r.save(_make_feed_detail(_FEED_ULID_1, name="binance-btcusd"))
        return r

    @pytest.fixture
    def client(self, repo: MockFeedRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.feeds import get_feed_repository

        app.dependency_overrides[get_feed_repository] = lambda: repo
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_get_feed_detail_returns_200(self, client: TestClient) -> None:
        """
        GIVEN a known feed_id
        WHEN GET /feeds/{feed_id} is requested
        THEN 200 is returned.

        FAILS: stub does not have this endpoint.
        """
        resp = client.get(f"/feeds/{_FEED_ULID_1}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_get_feed_detail_returns_feed_fields(self, client: TestClient) -> None:
        """
        GIVEN a known feed_id
        WHEN GET /feeds/{feed_id} is requested
        THEN response contains a 'feed' key with expected fields.
        """
        resp = client.get(f"/feeds/{_FEED_ULID_1}")
        body = resp.json()
        assert "feed" in body, f"Expected 'feed' key: {body}"
        assert body["feed"]["id"] == _FEED_ULID_1
        assert body["feed"]["name"] == "binance-btcusd"

    def test_get_feed_detail_returns_version_history(self, client: TestClient) -> None:
        """
        GIVEN a feed saved with two config versions
        WHEN GET /feeds/{feed_id} is requested
        THEN response contains 'version_history' with 2 entries.
        """
        resp = client.get(f"/feeds/{_FEED_ULID_1}")
        body = resp.json()
        assert "version_history" in body, f"Expected 'version_history' key: {body}"
        assert len(body["version_history"]) == 2

    def test_get_feed_detail_version_history_has_required_fields(self, client: TestClient) -> None:
        """
        GIVEN a feed with version history
        WHEN GET /feeds/{feed_id} is requested
        THEN each version entry has version, config, created_at, created_by.
        """
        resp = client.get(f"/feeds/{_FEED_ULID_1}")
        body = resp.json()
        for v in body["version_history"]:
            for field in ("version", "config", "created_at", "created_by"):
                assert field in v, f"Version entry missing field '{field}': {v}"

    def test_get_feed_detail_returns_connectivity_tests(self, client: TestClient) -> None:
        """
        GIVEN a feed saved with one connectivity test result
        WHEN GET /feeds/{feed_id} is requested
        THEN response contains 'connectivity_tests' with 1 entry.
        """
        resp = client.get(f"/feeds/{_FEED_ULID_1}")
        body = resp.json()
        assert "connectivity_tests" in body, f"Expected 'connectivity_tests' key: {body}"
        assert len(body["connectivity_tests"]) == 1

    def test_get_feed_detail_connectivity_has_required_fields(self, client: TestClient) -> None:
        """
        GIVEN a feed with connectivity test results
        WHEN GET /feeds/{feed_id} is requested
        THEN each test entry has id, feed_id, tested_at, status.
        """
        resp = client.get(f"/feeds/{_FEED_ULID_1}")
        body = resp.json()
        for t in body["connectivity_tests"]:
            for field in ("id", "feed_id", "tested_at", "status"):
                assert field in t, f"Connectivity entry missing field '{field}': {t}"

    def test_get_feed_detail_unknown_id_returns_404(self, client: TestClient) -> None:
        """
        GIVEN a feed_id not in the registry
        WHEN GET /feeds/{feed_id} is requested
        THEN 404 is returned.
        """
        resp = client.get(f"/feeds/{_FEED_ULID_3}")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# GET /feed-health — health summary endpoint tests
# ---------------------------------------------------------------------------


class TestFeedHealthEndpoint:
    """
    Unit tests for GET /feed-health.

    The endpoint must:
    - Return 200 with a 'feeds' list and 'generated_at' timestamp.
    - Return one health entry per registered feed.
    - Delegate all data access to the injected FeedHealthRepositoryInterface.
    - Never compute health state locally (spec requirement).
    """

    @pytest.fixture
    def health_repo(self) -> MockFeedHealthRepository:
        r = MockFeedHealthRepository()
        r.save(_make_health_report(_FEED_ULID_1, FeedHealthStatus.HEALTHY))
        r.save(_make_health_report(_FEED_ULID_2, FeedHealthStatus.DEGRADED))
        return r

    @pytest.fixture
    def client(self, health_repo: MockFeedHealthRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.feed_health import get_feed_health_repository

        app.dependency_overrides[get_feed_health_repository] = lambda: health_repo
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_get_feed_health_returns_200(self, client: TestClient) -> None:
        """
        GIVEN two feeds with health reports
        WHEN GET /feed-health is requested
        THEN 200 is returned.

        FAILS: stub does not use FeedHealthRepositoryInterface.
        """
        resp = client.get("/feed-health")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_get_feed_health_returns_feeds_list(self, client: TestClient) -> None:
        """
        GIVEN two health reports
        WHEN GET /feed-health is requested
        THEN response contains 'feeds' key with 2 entries.

        FAILS: stub returns empty list always.
        """
        resp = client.get("/feed-health")
        body = resp.json()
        assert "feeds" in body, f"Expected 'feeds' key: {body}"
        assert len(body["feeds"]) == 2

    def test_get_feed_health_returns_generated_at(self, client: TestClient) -> None:
        """
        GIVEN any state
        WHEN GET /feed-health is requested
        THEN response contains a 'generated_at' timestamp string.
        """
        resp = client.get("/feed-health")
        body = resp.json()
        assert "generated_at" in body, f"Expected 'generated_at' key: {body}"
        assert isinstance(body["generated_at"], str)

    def test_get_feed_health_each_entry_has_required_fields(self, client: TestClient) -> None:
        """
        GIVEN feeds with health reports
        WHEN GET /feed-health is requested
        THEN each entry contains feed_id and status.
        """
        resp = client.get("/feed-health")
        body = resp.json()
        for entry in body["feeds"]:
            assert "feed_id" in entry, f"Entry missing 'feed_id': {entry}"
            assert "status" in entry, f"Entry missing 'status': {entry}"

    def test_get_feed_health_reflects_correct_statuses(self, client: TestClient) -> None:
        """
        GIVEN one healthy and one degraded feed
        WHEN GET /feed-health is requested
        THEN response contains both statuses.
        """
        resp = client.get("/feed-health")
        body = resp.json()
        statuses = {e["status"] for e in body["feeds"]}
        assert "healthy" in statuses
        assert "degraded" in statuses

    def test_get_feed_health_empty_repository_returns_empty_list(self) -> None:
        """
        GIVEN an empty health repository
        WHEN GET /feed-health is requested
        THEN feeds is [].
        """
        from services.api.main import app
        from services.api.routes.feed_health import get_feed_health_repository

        empty_repo = MockFeedHealthRepository()
        app.dependency_overrides[get_feed_health_repository] = lambda: empty_repo
        client = TestClient(app)
        try:
            resp = client.get("/feed-health")
            body = resp.json()
            assert body["feeds"] == []
        finally:
            app.dependency_overrides.clear()

    def test_get_feed_health_with_anomalies_serializes_correctly(
        self,
    ) -> None:
        """
        GIVEN a health report containing one anomaly with datetime fields
        WHEN GET /feed-health is requested
        THEN anomaly datetime fields are serialised as ISO strings.

        Exercises the anomaly serialization loop in _serialize_health_report()
        (lines 89-94 in feed_health.py).
        """
        from services.api.main import app
        from services.api.routes.feed_health import get_feed_health_repository

        anomaly = Anomaly(
            id="01HQANOM0000000000000000A1",
            feed_id=_FEED_ULID_1,
            anomaly_type=AnomalyType.GAP,
            detected_at=_NOW,
            start_time=_NOW,
            end_time=_NOW,
            severity="high",
            message="gap detected in BTC/USD feed",
        )
        report = FeedHealthReport(
            feed_id=_FEED_ULID_1,
            status=FeedHealthStatus.DEGRADED,
            last_update=_NOW,
            recent_anomalies=[anomaly],
        )
        anomaly_repo = MockFeedHealthRepository()
        anomaly_repo.save(report)
        app.dependency_overrides[get_feed_health_repository] = lambda: anomaly_repo
        anomaly_client = TestClient(app)
        try:
            resp = anomaly_client.get("/feed-health")
            body = resp.json()
            assert resp.status_code == 200
            feeds = body["feeds"]
            assert len(feeds) == 1
            anomalies = feeds[0].get("recent_anomalies", [])
            assert len(anomalies) == 1
            # Datetime fields must be serialised to ISO strings (not raw objects)
            assert isinstance(anomalies[0]["detected_at"], str)
            assert isinstance(anomalies[0]["start_time"], str)
            assert isinstance(anomalies[0]["end_time"], str)
        finally:
            app.dependency_overrides.clear()

    def test_get_feed_health_default_provider_returns_200(self) -> None:
        """
        GIVEN the app's default dependency provider (no override)
        WHEN GET /feed-health is requested
        THEN 200 is returned (bootstrap stub returns empty list).

        Covers lines 59-61 in feed_health.py (the MockFeedHealthRepository
        import inside get_feed_health_repository()).
        """
        from services.api.main import app

        app.dependency_overrides.clear()  # ensure no leftover overrides
        bare_client = TestClient(app)
        resp = bare_client.get("/feed-health")
        assert resp.status_code == 200
        body = resp.json()
        assert "feeds" in body

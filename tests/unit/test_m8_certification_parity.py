"""
Unit tests for M8: Verification + Gaps + Anomalies + Certification.

Coverage:
- MockCertificationRepository  — behavioural parity with CertificationRepositoryInterface
- MockParityRepository         — behavioural parity with ParityRepositoryInterface
- GET /data/certification      — certification report endpoint
- GET /parity/events           — parity event list endpoint

All tests MUST FAIL before GREEN and MUST PASS after GREEN.

LL-007 note: Use model_construct() for Pydantic models that contain Optional[str] fields
             (e.g. CertificationEvent.blocked_reason is str = "" so it is safe here, but
              certified_at / expires_at are Optional[datetime] which is also fine).
LL-008 note: Route handlers must use JSONResponse + model_dump() (no response_model=).
LL-012 note: Optional[str-Enum] fields require model_construct(); str-Enums are fine directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from libs.contracts.certification import CertificationEvent, CertificationStatus
from libs.contracts.errors import NotFoundError
from libs.contracts.mocks.mock_certification_repository import (
    MockCertificationRepository,
)
from libs.contracts.mocks.mock_parity_repository import MockParityRepository
from libs.contracts.parity import ParityEvent, ParityEventSeverity

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}

# ---------------------------------------------------------------------------
# Shared test data constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)

_FEED_ULID_1 = "01HQFEED0AAAAAAAAAAAAAAAA1"
_FEED_ULID_2 = "01HQFEED0BBBBBBBBBBBBBBB2"
_FEED_ULID_MISSING = "01HQFEED0XXXXXXXXXXXXXXX9"

_PARITY_ULID_1 = "01HQPARITY00000000000AAAA1"
_PARITY_ULID_2 = "01HQPARITY00000000000BBBB2"
_PARITY_ULID_MISSING = "01HQPARITY00000000000XXXX9"


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_cert_event(
    feed_id: str = _FEED_ULID_1,
    feed_name: str = "AAPL_1m_primary",
    status: CertificationStatus = CertificationStatus.CERTIFIED,
    blocked_reason: str = "",
) -> CertificationEvent:
    """Build a minimal CertificationEvent for tests.

    Uses model_construct() as a defensive measure for Optional datetime fields,
    even though CertificationEvent.blocked_reason is str (not Optional[str]).
    """
    return CertificationEvent.model_construct(
        feed_id=feed_id,
        feed_name=feed_name,
        status=status,
        blocked_reason=blocked_reason,
        certified_at=_NOW,
        expires_at=None,
        generated_at=_NOW,
    )


def _make_parity_event(
    event_id: str = _PARITY_ULID_1,
    instrument: str = "AAPL",
    severity: ParityEventSeverity = ParityEventSeverity.WARNING,
    delta: float = 0.05,
) -> ParityEvent:
    """Build a minimal ParityEvent for tests."""
    return ParityEvent(
        id=event_id,
        feed_id_official=_FEED_ULID_1,
        feed_id_shadow=_FEED_ULID_2,
        instrument=instrument,
        timestamp=_NOW,
        delta=delta,
        delta_pct=abs(delta) / 100.0,
        severity=severity,
        detected_at=_NOW,
    )


# ---------------------------------------------------------------------------
# MockCertificationRepository Tests
# ---------------------------------------------------------------------------


class TestMockCertificationRepository:
    """
    Verify MockCertificationRepository honours the CertificationRepositoryInterface contract.
    """

    def test_list_returns_all_saved_events(self) -> None:
        """
        GIVEN two saved CertificationEvents
        WHEN list() is called
        THEN both are returned.
        """
        repo = MockCertificationRepository()
        repo.save(_make_cert_event(_FEED_ULID_1))
        repo.save(_make_cert_event(_FEED_ULID_2, feed_name="GOOG_1m_primary"))
        result = repo.list(correlation_id="c")
        assert len(result) == 2

    def test_list_returns_empty_for_empty_repository(self) -> None:
        """
        GIVEN an empty repository
        WHEN list() is called
        THEN an empty list is returned.
        """
        repo = MockCertificationRepository()
        assert repo.list(correlation_id="c") == []

    def test_find_by_feed_id_returns_correct_event(self) -> None:
        """
        GIVEN a saved CertificationEvent for _FEED_ULID_1
        WHEN find_by_feed_id(_FEED_ULID_1) is called
        THEN the matching event is returned.
        """
        repo = MockCertificationRepository()
        repo.save(_make_cert_event(_FEED_ULID_1, feed_name="AAPL_1m_primary"))
        result = repo.find_by_feed_id(_FEED_ULID_1, correlation_id="c")
        assert result.feed_id == _FEED_ULID_1
        assert result.feed_name == "AAPL_1m_primary"

    def test_find_by_feed_id_raises_not_found_for_unknown_feed(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_by_feed_id is called with an unknown feed_id
        THEN NotFoundError is raised.
        """
        repo = MockCertificationRepository()
        with pytest.raises(NotFoundError, match=_FEED_ULID_MISSING):
            repo.find_by_feed_id(_FEED_ULID_MISSING, correlation_id="c")

    def test_clear_removes_all_events(self) -> None:
        """
        GIVEN a populated repository
        WHEN clear() is called
        THEN count() returns 0.
        """
        repo = MockCertificationRepository()
        repo.save(_make_cert_event(_FEED_ULID_1))
        repo.clear()
        assert repo.count() == 0


# ---------------------------------------------------------------------------
# MockParityRepository Tests
# ---------------------------------------------------------------------------


class TestMockParityRepository:
    """
    Verify MockParityRepository honours the ParityRepositoryInterface contract.
    """

    def test_list_returns_all_saved_events(self) -> None:
        """
        GIVEN two saved ParityEvents
        WHEN list() is called
        THEN both are returned.
        """
        repo = MockParityRepository()
        repo.save(_make_parity_event(_PARITY_ULID_1))
        repo.save(_make_parity_event(_PARITY_ULID_2, instrument="GOOG"))
        result = repo.list(correlation_id="c")
        assert len(result) == 2

    def test_list_returns_empty_for_empty_repository(self) -> None:
        """
        GIVEN an empty repository
        WHEN list() is called
        THEN an empty list is returned.
        """
        repo = MockParityRepository()
        assert repo.list(correlation_id="c") == []

    def test_find_by_id_returns_correct_event(self) -> None:
        """
        GIVEN a saved ParityEvent with _PARITY_ULID_1
        WHEN find_by_id(_PARITY_ULID_1) is called
        THEN the matching event is returned.
        """
        repo = MockParityRepository()
        repo.save(_make_parity_event(_PARITY_ULID_1, instrument="MSFT"))
        result = repo.find_by_id(_PARITY_ULID_1, correlation_id="c")
        assert result.id == _PARITY_ULID_1
        assert result.instrument == "MSFT"

    def test_find_by_id_raises_not_found_for_unknown_id(self) -> None:
        """
        GIVEN an empty repository
        WHEN find_by_id is called with an unknown ID
        THEN NotFoundError is raised.
        """
        repo = MockParityRepository()
        with pytest.raises(NotFoundError, match=_PARITY_ULID_MISSING):
            repo.find_by_id(_PARITY_ULID_MISSING, correlation_id="c")

    def test_clear_removes_all_events(self) -> None:
        """
        GIVEN a populated repository
        WHEN clear() is called
        THEN count() returns 0.
        """
        repo = MockParityRepository()
        repo.save(_make_parity_event(_PARITY_ULID_1))
        repo.clear()
        assert repo.count() == 0


# ---------------------------------------------------------------------------
# GET /data/certification — certification report endpoint tests
# ---------------------------------------------------------------------------


class TestDataCertificationEndpoint:
    """
    Unit tests for GET /data/certification.

    The endpoint must:
    - Return 200 with 'certifications', 'total_count', 'blocked_count',
      'certified_count', and 'generated_at' keys.
    - Accurately count blocked and certified feeds.
    - Return an empty certification list when no feeds are registered.

    FAILS: stub route does not exist until GREEN.
    """

    @pytest.fixture
    def cert_repo_mixed(self) -> MockCertificationRepository:
        """Repository with two certified and one blocked feed."""
        repo = MockCertificationRepository()
        repo.save(_make_cert_event(_FEED_ULID_1, status=CertificationStatus.CERTIFIED))
        repo.save(
            _make_cert_event(
                _FEED_ULID_2,
                feed_name="GOOG_1m_primary",
                status=CertificationStatus.BLOCKED,
                blocked_reason="Gap detected: 2026-03-25 12:00–14:00 UTC",
            )
        )
        repo.save(
            _make_cert_event(
                "01HQFEED0CCCCCCCCCCCCCCC3",
                feed_name="TSLA_1m_primary",
                status=CertificationStatus.CERTIFIED,
            )
        )
        return repo

    @pytest.fixture
    def client_mixed(self, cert_repo_mixed: MockCertificationRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.data_certification import get_certification_repository

        app.dependency_overrides[get_certification_repository] = lambda: cert_repo_mixed
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_certification_returns_200(self, client_mixed: TestClient) -> None:
        """
        GIVEN feeds in the certification repository
        WHEN GET /data/certification is requested
        THEN 200 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client_mixed.get("/data/certification", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_certification_contains_required_keys(self, client_mixed: TestClient) -> None:
        """
        GIVEN feeds in the repository
        WHEN GET /data/certification is requested
        THEN response contains 'certifications', 'total_count', 'blocked_count',
             'certified_count', and 'generated_at'.
        """
        resp = client_mixed.get("/data/certification", headers=AUTH_HEADERS)
        body = resp.json()
        for key in (
            "certifications",
            "total_count",
            "blocked_count",
            "certified_count",
            "generated_at",
        ):
            assert key in body, f"Missing key '{key}': {body}"

    def test_certification_counts_are_correct(self, client_mixed: TestClient) -> None:
        """
        GIVEN 2 certified and 1 blocked feed
        WHEN GET /data/certification is requested
        THEN total_count=3, blocked_count=1, certified_count=2.
        """
        resp = client_mixed.get("/data/certification", headers=AUTH_HEADERS)
        body = resp.json()
        assert body["total_count"] == 3, f"total_count wrong: {body}"
        assert body["blocked_count"] == 1, f"blocked_count wrong: {body}"
        assert body["certified_count"] == 2, f"certified_count wrong: {body}"

    def test_certification_certifications_list_has_correct_length(
        self, client_mixed: TestClient
    ) -> None:
        """
        GIVEN 3 feeds in the repository
        WHEN GET /data/certification is requested
        THEN 'certifications' list has 3 items.
        """
        resp = client_mixed.get("/data/certification", headers=AUTH_HEADERS)
        body = resp.json()
        assert len(body["certifications"]) == 3, f"Expected 3 certifications: {body}"

    def test_certification_empty_repository_returns_zero_counts(self) -> None:
        """
        GIVEN no feeds in the repository
        WHEN GET /data/certification is requested
        THEN certifications is [] and all counts are 0.

        FAILS: endpoint does not exist until GREEN.
        """
        from services.api.main import app
        from services.api.routes.data_certification import get_certification_repository

        empty_repo = MockCertificationRepository()
        app.dependency_overrides[get_certification_repository] = lambda: empty_repo
        tc = TestClient(app)
        try:
            resp = tc.get("/data/certification", headers=AUTH_HEADERS)
            body = resp.json()
            assert resp.status_code == 200
            assert body.get("certifications") == []
            assert body.get("total_count") == 0
            assert body.get("blocked_count") == 0
            assert body.get("certified_count") == 0
        finally:
            app.dependency_overrides.clear()

    def test_certification_blocked_feed_has_reason(self, client_mixed: TestClient) -> None:
        """
        GIVEN a BLOCKED feed with a non-empty blocked_reason
        WHEN GET /data/certification is requested
        THEN the blocked event in 'certifications' has a non-empty blocked_reason.
        """
        resp = client_mixed.get("/data/certification", headers=AUTH_HEADERS)
        body = resp.json()
        blocked = [c for c in body["certifications"] if c["status"] == "BLOCKED"]
        assert len(blocked) == 1, f"Expected 1 blocked feed: {body}"
        assert blocked[0]["blocked_reason"], f"Expected non-empty blocked_reason: {blocked[0]}"


# ---------------------------------------------------------------------------
# GET /parity/events — parity event list endpoint tests
# ---------------------------------------------------------------------------


class TestParityEventsEndpoint:
    """
    Unit tests for GET /parity/events.

    The endpoint must:
    - Return 200 with 'events', 'total_count', and 'generated_at' keys.
    - Return all parity events from the repository.
    - Return an empty events list when no events are registered.
    - Correctly serialize all required ParityEvent fields.

    FAILS: stub route does not exist until GREEN.
    """

    @pytest.fixture
    def parity_repo(self) -> MockParityRepository:
        """Repository with one WARNING and one CRITICAL parity event."""
        repo = MockParityRepository()
        repo.save(
            _make_parity_event(_PARITY_ULID_1, severity=ParityEventSeverity.WARNING, delta=0.05)
        )
        repo.save(
            _make_parity_event(
                _PARITY_ULID_2,
                instrument="GOOG",
                severity=ParityEventSeverity.CRITICAL,
                delta=2.50,
            )
        )
        return repo

    @pytest.fixture
    def client(self, parity_repo: MockParityRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.parity import get_parity_repository

        app.dependency_overrides[get_parity_repository] = lambda: parity_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_parity_events_returns_200(self, client: TestClient) -> None:
        """
        GIVEN parity events in the repository
        WHEN GET /parity/events is requested
        THEN 200 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client.get("/parity/events", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_parity_events_contains_required_keys(self, client: TestClient) -> None:
        """
        GIVEN parity events in the repository
        WHEN GET /parity/events is requested
        THEN response contains 'events', 'total_count', and 'generated_at'.
        """
        resp = client.get("/parity/events", headers=AUTH_HEADERS)
        body = resp.json()
        for key in ("events", "total_count", "generated_at"):
            assert key in body, f"Missing key '{key}': {body}"

    def test_parity_events_returns_correct_count(self, client: TestClient) -> None:
        """
        GIVEN 2 parity events in the repository
        WHEN GET /parity/events is requested
        THEN total_count is 2 and events list has 2 items.
        """
        resp = client.get("/parity/events", headers=AUTH_HEADERS)
        body = resp.json()
        assert body["total_count"] == 2, f"total_count wrong: {body}"
        assert len(body["events"]) == 2, f"events length wrong: {body}"

    def test_parity_events_each_event_has_required_fields(self, client: TestClient) -> None:
        """
        GIVEN parity events in the repository
        WHEN GET /parity/events is requested
        THEN each event contains all required ParityEvent fields.
        """
        resp = client.get("/parity/events", headers=AUTH_HEADERS)
        body = resp.json()
        required = (
            "id",
            "feed_id_official",
            "feed_id_shadow",
            "instrument",
            "timestamp",
            "delta",
            "delta_pct",
            "severity",
            "detected_at",
        )
        for event in body["events"]:
            for field in required:
                assert field in event, f"Missing field '{field}' in event: {event}"

    def test_parity_events_empty_repository_returns_empty_list(self) -> None:
        """
        GIVEN no parity events in the repository
        WHEN GET /parity/events is requested
        THEN events is [] and total_count is 0.

        FAILS: endpoint does not exist until GREEN.
        """
        from services.api.main import app
        from services.api.routes.parity import get_parity_repository

        empty_repo = MockParityRepository()
        app.dependency_overrides[get_parity_repository] = lambda: empty_repo
        tc = TestClient(app)
        try:
            resp = tc.get("/parity/events", headers=AUTH_HEADERS)
            body = resp.json()
            assert resp.status_code == 200
            assert body.get("events") == []
            assert body.get("total_count") == 0
        finally:
            app.dependency_overrides.clear()

    def test_parity_events_critical_event_has_correct_severity(self, client: TestClient) -> None:
        """
        GIVEN a CRITICAL parity event for GOOG
        WHEN GET /parity/events is requested
        THEN the GOOG event has severity 'CRITICAL'.
        """
        resp = client.get("/parity/events", headers=AUTH_HEADERS)
        body = resp.json()
        goog_events = [e for e in body["events"] if e["instrument"] == "GOOG"]
        assert len(goog_events) == 1, f"Expected 1 GOOG event: {body}"
        assert goog_events[0]["severity"] == "CRITICAL", f"Expected CRITICAL: {goog_events[0]}"

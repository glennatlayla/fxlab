"""
Unit tests for M10: Parity Service — Extended Querying + Summary.

Coverage:
- MockParityRepository (M10 extensions)
    - list() no-filter backward-compat
    - list() severity filter
    - list() instrument filter
    - list() feed_id filter (official OR shadow)
    - list() combined AND filters
    - summarize() per-instrument aggregates
    - summarize() empty repository
- GET /parity/events (extended with query params)
    - backward-compat no-filter
    - filter by severity
    - filter by instrument
    - empty list when no match
- GET /parity/events/{event_id} (new)
    - 200 with all fields for known ID
    - 404 for unknown ID
- GET /parity/summary (new)
    - 200 with summaries, total_event_count, generated_at
    - correct per-instrument counts
    - worst_severity correct
    - empty repository → empty summaries, zero count

All tests MUST FAIL before GREEN (S4) and MUST PASS after GREEN.

Known lessons:
    LL-007: ParityInstrumentSummary.worst_severity is str="" not Optional[str].
    LL-008: Route handlers use JSONResponse; no response_model=.
    LL-010: Explicit int() on Query() params before repo calls.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from libs.contracts.mocks.mock_parity_repository import MockParityRepository
from libs.contracts.parity import ParityEvent, ParityEventSeverity

AUTH_HEADERS = {"Authorization": "Bearer TEST_TOKEN"}

# ---------------------------------------------------------------------------
# Shared test data constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=timezone.utc)

_PARITY_ULID_1 = "01HQPARITY10000000000AAAA1"
_PARITY_ULID_2 = "01HQPARITY10000000000BBBB2"
_PARITY_ULID_3 = "01HQPARITY10000000000CCCC3"
_PARITY_ULID_4 = "01HQPARITY10000000000DDDD4"
_PARITY_ULID_MISSING = "01HQPARITY1XXXXXXXXXXXXXXX9"

_FEED_ULID_OFF = "01HQFEED0AAAAAAAAAAAAAAAA1"
_FEED_ULID_SHADOW = "01HQFEED0BBBBBBBBBBBBBBB2"
_FEED_ULID_OTHER = "01HQFEED0CCCCCCCCCCCCCCC3"


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_event(
    event_id: str = _PARITY_ULID_1,
    instrument: str = "AAPL",
    severity: ParityEventSeverity = ParityEventSeverity.WARNING,
    delta: float = 0.05,
    feed_id_official: str = _FEED_ULID_OFF,
    feed_id_shadow: str = _FEED_ULID_SHADOW,
) -> ParityEvent:
    """
    Build a minimal ParityEvent for tests.

    Args:
        event_id:         ULID for the parity event.
        instrument:       Instrument/ticker.
        severity:         ParityEventSeverity member.
        delta:            Absolute delta value.
        feed_id_official: Official feed ULID.
        feed_id_shadow:   Shadow feed ULID.

    Returns:
        ParityEvent instance.
    """
    return ParityEvent(
        id=event_id,
        feed_id_official=feed_id_official,
        feed_id_shadow=feed_id_shadow,
        instrument=instrument,
        timestamp=_NOW,
        delta=delta,
        delta_pct=abs(delta) / 100.0,
        severity=severity,
        detected_at=_NOW,
    )


# ---------------------------------------------------------------------------
# MockParityRepository M10 extension tests
# ---------------------------------------------------------------------------


class TestMockParityRepositoryM10:
    """
    Verify MockParityRepository M10 extensions honour the updated contract.

    Tests cover:
    - list() backward-compat (no filters → all events).
    - list() severity filter.
    - list() instrument filter.
    - list() feed_id filter matches either official or shadow.
    - list() combined AND filters.
    - summarize() per-instrument aggregates.
    - summarize() empty repository returns empty list.
    """

    def test_list_no_filters_returns_all_events(self) -> None:
        """
        GIVEN three events in the repository
        WHEN list() is called with no filter args
        THEN all three are returned (backward-compat).
        """
        repo = MockParityRepository()
        repo.save(_make_event(_PARITY_ULID_1))
        repo.save(_make_event(_PARITY_ULID_2, instrument="GOOG"))
        repo.save(_make_event(_PARITY_ULID_3, instrument="MSFT"))
        result = repo.list(correlation_id="c")
        assert len(result) == 3

    def test_list_filters_by_severity_critical(self) -> None:
        """
        GIVEN one WARNING and one CRITICAL event
        WHEN list(severity="CRITICAL") is called
        THEN only the CRITICAL event is returned.
        """
        repo = MockParityRepository()
        repo.save(_make_event(_PARITY_ULID_1, severity=ParityEventSeverity.WARNING))
        repo.save(_make_event(_PARITY_ULID_2, severity=ParityEventSeverity.CRITICAL))
        result = repo.list(severity="CRITICAL", correlation_id="c")
        assert len(result) == 1
        assert result[0].severity == ParityEventSeverity.CRITICAL

    def test_list_filters_by_instrument(self) -> None:
        """
        GIVEN events for AAPL and GOOG
        WHEN list(instrument="AAPL") is called
        THEN only AAPL events are returned.
        """
        repo = MockParityRepository()
        repo.save(_make_event(_PARITY_ULID_1, instrument="AAPL"))
        repo.save(_make_event(_PARITY_ULID_2, instrument="GOOG"))
        result = repo.list(instrument="AAPL", correlation_id="c")
        assert len(result) == 1
        assert result[0].instrument == "AAPL"

    def test_list_filters_by_feed_id_matches_official(self) -> None:
        """
        GIVEN an event where feed_id_official=_FEED_ULID_OFF
        WHEN list(feed_id=_FEED_ULID_OFF) is called
        THEN the event is returned.
        """
        repo = MockParityRepository()
        repo.save(_make_event(_PARITY_ULID_1, feed_id_official=_FEED_ULID_OFF))
        result = repo.list(feed_id=_FEED_ULID_OFF, correlation_id="c")
        assert len(result) == 1

    def test_list_filters_by_feed_id_matches_shadow(self) -> None:
        """
        GIVEN an event where feed_id_shadow=_FEED_ULID_SHADOW
        WHEN list(feed_id=_FEED_ULID_SHADOW) is called
        THEN the event is returned.
        """
        repo = MockParityRepository()
        repo.save(_make_event(_PARITY_ULID_1, feed_id_shadow=_FEED_ULID_SHADOW))
        result = repo.list(feed_id=_FEED_ULID_SHADOW, correlation_id="c")
        assert len(result) == 1

    def test_list_feed_id_filter_excludes_unrelated_event(self) -> None:
        """
        GIVEN an event that involves neither _FEED_ULID_OFF nor _FEED_ULID_OTHER
        WHEN list(feed_id=_FEED_ULID_OTHER) is called
        THEN no events are returned.
        """
        repo = MockParityRepository()
        # Event uses different feeds that don't match _FEED_ULID_OTHER
        repo.save(
            _make_event(
                _PARITY_ULID_1,
                feed_id_official=_FEED_ULID_OFF,
                feed_id_shadow=_FEED_ULID_SHADOW,
            )
        )
        result = repo.list(feed_id=_FEED_ULID_OTHER, correlation_id="c")
        assert result == []

    def test_list_combined_and_filters(self) -> None:
        """
        GIVEN two CRITICAL events — one AAPL, one GOOG
        WHEN list(severity="CRITICAL", instrument="AAPL") is called
        THEN only the AAPL CRITICAL event is returned.
        """
        repo = MockParityRepository()
        repo.save(
            _make_event(_PARITY_ULID_1, instrument="AAPL", severity=ParityEventSeverity.CRITICAL)
        )
        repo.save(
            _make_event(_PARITY_ULID_2, instrument="GOOG", severity=ParityEventSeverity.CRITICAL)
        )
        result = repo.list(severity="CRITICAL", instrument="AAPL", correlation_id="c")
        assert len(result) == 1
        assert result[0].instrument == "AAPL"

    def test_summarize_computes_per_instrument_counts(self) -> None:
        """
        GIVEN 2 AAPL events (1 CRITICAL, 1 WARNING) and 1 GOOG INFO event
        WHEN summarize() is called
        THEN two ParityInstrumentSummary entries are returned with correct counts.
        """
        repo = MockParityRepository()
        repo.save(
            _make_event(_PARITY_ULID_1, instrument="AAPL", severity=ParityEventSeverity.CRITICAL)
        )
        repo.save(
            _make_event(_PARITY_ULID_2, instrument="AAPL", severity=ParityEventSeverity.WARNING)
        )
        repo.save(_make_event(_PARITY_ULID_3, instrument="GOOG", severity=ParityEventSeverity.INFO))
        summaries = repo.summarize(correlation_id="c")
        by_instrument = {s.instrument: s for s in summaries}
        assert "AAPL" in by_instrument, f"AAPL missing from summaries: {summaries}"
        assert "GOOG" in by_instrument, f"GOOG missing from summaries: {summaries}"
        aapl = by_instrument["AAPL"]
        assert aapl.event_count == 2
        assert aapl.critical_count == 1
        assert aapl.warning_count == 1
        assert aapl.info_count == 0
        assert aapl.worst_severity == "CRITICAL"
        goog = by_instrument["GOOG"]
        assert goog.event_count == 1
        assert goog.info_count == 1
        assert goog.worst_severity == "INFO"

    def test_summarize_empty_repository_returns_empty_list(self) -> None:
        """
        GIVEN an empty repository
        WHEN summarize() is called
        THEN an empty list is returned.
        """
        repo = MockParityRepository()
        result = repo.summarize(correlation_id="c")
        assert result == []

    def test_summarize_worst_severity_is_critical_when_mixed(self) -> None:
        """
        GIVEN an instrument with INFO, WARNING, and CRITICAL events
        WHEN summarize() is called
        THEN worst_severity is "CRITICAL".
        """
        repo = MockParityRepository()
        repo.save(_make_event(_PARITY_ULID_1, instrument="TSLA", severity=ParityEventSeverity.INFO))
        repo.save(
            _make_event(_PARITY_ULID_2, instrument="TSLA", severity=ParityEventSeverity.WARNING)
        )
        repo.save(
            _make_event(_PARITY_ULID_3, instrument="TSLA", severity=ParityEventSeverity.CRITICAL)
        )
        summaries = repo.summarize(correlation_id="c")
        tsla = next(s for s in summaries if s.instrument == "TSLA")
        assert tsla.worst_severity == "CRITICAL"


# ---------------------------------------------------------------------------
# GET /parity/events (extended with query params) tests
# ---------------------------------------------------------------------------


class TestParityEventsEndpointExtended:
    """
    Unit tests for the M10-extended GET /parity/events endpoint.

    The endpoint must:
    - Remain backward-compatible (no params → all events).
    - Filter by ?severity=CRITICAL.
    - Filter by ?instrument=AAPL.
    - Return empty list when no events match the filter.
    - Each event has all required ParityEvent fields.

    FAILS: parity.py does not accept filter query params until GREEN (S4).
    """

    @pytest.fixture
    def mixed_repo(self) -> MockParityRepository:
        """Repo with AAPL (WARNING), AAPL (CRITICAL), GOOG (INFO)."""
        repo = MockParityRepository()
        repo.save(
            _make_event(_PARITY_ULID_1, instrument="AAPL", severity=ParityEventSeverity.WARNING)
        )
        repo.save(
            _make_event(_PARITY_ULID_2, instrument="AAPL", severity=ParityEventSeverity.CRITICAL)
        )
        repo.save(_make_event(_PARITY_ULID_3, instrument="GOOG", severity=ParityEventSeverity.INFO))
        return repo

    @pytest.fixture
    def client(self, mixed_repo: MockParityRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.parity import get_parity_repository

        app.dependency_overrides[get_parity_repository] = lambda: mixed_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_no_filter_returns_all_events(self, client: TestClient) -> None:
        """
        GIVEN 3 events
        WHEN GET /parity/events (no params) is requested
        THEN all 3 are returned (backward-compat).
        """
        resp = client.get("/parity/events", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 3

    def test_severity_filter_returns_only_critical(self, client: TestClient) -> None:
        """
        GIVEN 1 CRITICAL and 2 non-CRITICAL events
        WHEN GET /parity/events?severity=CRITICAL is requested
        THEN only 1 event is returned.

        FAILS: endpoint does not accept severity param until GREEN.
        """
        resp = client.get("/parity/events", params={"severity": "CRITICAL"}, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 1
        assert body["events"][0]["severity"] == "CRITICAL"

    def test_instrument_filter_returns_only_matching(self, client: TestClient) -> None:
        """
        GIVEN 2 AAPL and 1 GOOG event
        WHEN GET /parity/events?instrument=AAPL is requested
        THEN 2 events are returned.

        FAILS: endpoint does not accept instrument param until GREEN.
        """
        resp = client.get("/parity/events", params={"instrument": "AAPL"}, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 2
        for ev in body["events"]:
            assert ev["instrument"] == "AAPL"

    def test_filter_with_no_match_returns_empty_list(self, client: TestClient) -> None:
        """
        GIVEN no TSLA events in the repository
        WHEN GET /parity/events?instrument=TSLA is requested
        THEN events is [] and total_count is 0.
        """
        resp = client.get("/parity/events", params={"instrument": "TSLA"}, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_count"] == 0
        assert body["events"] == []

    def test_events_each_have_required_fields(self, client: TestClient) -> None:
        """
        GIVEN events in the repository
        WHEN GET /parity/events is requested
        THEN each event has all required ParityEvent fields.
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
        for ev in body["events"]:
            for field in required:
                assert field in ev, f"Missing field '{field}' in event: {ev}"


# ---------------------------------------------------------------------------
# GET /parity/events/{event_id} — single event detail tests
# ---------------------------------------------------------------------------


class TestParityEventDetailEndpoint:
    """
    Unit tests for GET /parity/events/{parity_event_id}.

    The endpoint must:
    - Return 200 with all ParityEvent fields for a known ID.
    - Return 404 for an unknown ID.
    - Correctly reflect saved values (instrument, severity, delta, etc.).

    FAILS: detail endpoint does not exist in parity.py until GREEN (S4).
    """

    @pytest.fixture
    def single_repo(self) -> MockParityRepository:
        """Repo with a single known CRITICAL AAPL event."""
        repo = MockParityRepository()
        repo.save(
            _make_event(
                _PARITY_ULID_1,
                instrument="AAPL",
                severity=ParityEventSeverity.CRITICAL,
                delta=1.25,
            )
        )
        return repo

    @pytest.fixture
    def client(self, single_repo: MockParityRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.parity import get_parity_repository

        app.dependency_overrides[get_parity_repository] = lambda: single_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_detail_returns_200_for_known_id(self, client: TestClient) -> None:
        """
        GIVEN an event with _PARITY_ULID_1
        WHEN GET /parity/events/{_PARITY_ULID_1} is requested
        THEN 200 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client.get(f"/parity/events/{_PARITY_ULID_1}", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_detail_contains_required_fields(self, client: TestClient) -> None:
        """
        GIVEN a saved event
        WHEN GET /parity/events/{id} is requested
        THEN all required ParityEvent fields are in the response body.
        """
        resp = client.get(f"/parity/events/{_PARITY_ULID_1}", headers=AUTH_HEADERS)
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
        for field in required:
            assert field in body, f"Missing field '{field}': {body}"

    def test_detail_values_match_saved_event(self, client: TestClient) -> None:
        """
        GIVEN a CRITICAL AAPL event with delta=1.25
        WHEN GET /parity/events/{_PARITY_ULID_1} is requested
        THEN instrument, severity, and delta match the saved values.
        """
        resp = client.get(f"/parity/events/{_PARITY_ULID_1}", headers=AUTH_HEADERS)
        body = resp.json()
        assert body["instrument"] == "AAPL", f"instrument wrong: {body}"
        assert body["severity"] == "CRITICAL", f"severity wrong: {body}"
        assert body["delta"] == pytest.approx(1.25), f"delta wrong: {body}"

    def test_detail_returns_404_for_unknown_id(self, client: TestClient) -> None:
        """
        GIVEN no event with _PARITY_ULID_MISSING
        WHEN GET /parity/events/{_PARITY_ULID_MISSING} is requested
        THEN 404 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client.get(f"/parity/events/{_PARITY_ULID_MISSING}", headers=AUTH_HEADERS)
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# GET /parity/summary — per-instrument aggregate endpoint tests
# ---------------------------------------------------------------------------


class TestParitySummaryEndpoint:
    """
    Unit tests for GET /parity/summary.

    The endpoint must:
    - Return 200 with 'summaries', 'total_event_count', 'generated_at' keys.
    - Provide one summary entry per unique instrument.
    - Correctly compute event_count, critical_count, warning_count, info_count.
    - Report worst_severity correctly.
    - Return empty summaries list and zero total_event_count when repo is empty.
    - Each summary entry has all required ParityInstrumentSummary fields.

    FAILS: GET /parity/summary does not exist in parity.py until GREEN (S4).
    """

    @pytest.fixture
    def summary_repo(self) -> MockParityRepository:
        """
        Repository with:
        - AAPL: 1 CRITICAL + 1 WARNING (2 events, worst=CRITICAL)
        - GOOG: 1 INFO (1 event, worst=INFO)
        """
        repo = MockParityRepository()
        repo.save(
            _make_event(_PARITY_ULID_1, instrument="AAPL", severity=ParityEventSeverity.CRITICAL)
        )
        repo.save(
            _make_event(_PARITY_ULID_2, instrument="AAPL", severity=ParityEventSeverity.WARNING)
        )
        repo.save(_make_event(_PARITY_ULID_3, instrument="GOOG", severity=ParityEventSeverity.INFO))
        return repo

    @pytest.fixture
    def client(self, summary_repo: MockParityRepository) -> TestClient:
        from services.api.main import app
        from services.api.routes.parity import get_parity_repository

        app.dependency_overrides[get_parity_repository] = lambda: summary_repo
        tc = TestClient(app)
        yield tc
        app.dependency_overrides.clear()

    def test_summary_returns_200(self, client: TestClient) -> None:
        """
        GIVEN events in the repository
        WHEN GET /parity/summary is requested
        THEN 200 is returned.

        FAILS: endpoint does not exist until GREEN.
        """
        resp = client.get("/parity/summary", headers=AUTH_HEADERS)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_summary_contains_required_keys(self, client: TestClient) -> None:
        """
        GIVEN events in the repository
        WHEN GET /parity/summary is requested
        THEN response contains 'summaries', 'total_event_count', 'generated_at'.
        """
        resp = client.get("/parity/summary", headers=AUTH_HEADERS)
        body = resp.json()
        for key in ("summaries", "total_event_count", "generated_at"):
            assert key in body, f"Missing key '{key}': {body}"

    def test_summary_has_one_entry_per_instrument(self, client: TestClient) -> None:
        """
        GIVEN events for 2 instruments (AAPL, GOOG)
        WHEN GET /parity/summary is requested
        THEN summaries list has 2 entries.
        """
        resp = client.get("/parity/summary", headers=AUTH_HEADERS)
        body = resp.json()
        assert len(body["summaries"]) == 2, f"Expected 2 summaries: {body}"

    def test_summary_total_event_count_is_correct(self, client: TestClient) -> None:
        """
        GIVEN 3 events total
        WHEN GET /parity/summary is requested
        THEN total_event_count is 3.
        """
        resp = client.get("/parity/summary", headers=AUTH_HEADERS)
        body = resp.json()
        assert body["total_event_count"] == 3, f"total_event_count wrong: {body}"

    def test_summary_aapl_counts_are_correct(self, client: TestClient) -> None:
        """
        GIVEN AAPL has 1 CRITICAL + 1 WARNING
        WHEN GET /parity/summary is requested
        THEN AAPL summary has event_count=2, critical_count=1, warning_count=1, worst_severity=CRITICAL.
        """
        resp = client.get("/parity/summary", headers=AUTH_HEADERS)
        body = resp.json()
        aapl = next((s for s in body["summaries"] if s["instrument"] == "AAPL"), None)
        assert aapl is not None, f"AAPL not in summaries: {body}"
        assert aapl["event_count"] == 2
        assert aapl["critical_count"] == 1
        assert aapl["warning_count"] == 1
        assert aapl["info_count"] == 0
        assert aapl["worst_severity"] == "CRITICAL"

    def test_summary_each_entry_has_required_fields(self, client: TestClient) -> None:
        """
        GIVEN events in the repository
        WHEN GET /parity/summary is requested
        THEN each summary entry has all required ParityInstrumentSummary fields.
        """
        resp = client.get("/parity/summary", headers=AUTH_HEADERS)
        body = resp.json()
        required = (
            "instrument",
            "event_count",
            "critical_count",
            "warning_count",
            "info_count",
            "worst_severity",
        )
        for entry in body["summaries"]:
            for field in required:
                assert field in entry, f"Missing field '{field}' in entry: {entry}"

    def test_summary_empty_repository_returns_zero_count(self) -> None:
        """
        GIVEN no events in the repository
        WHEN GET /parity/summary is requested
        THEN summaries is [] and total_event_count is 0.

        FAILS: endpoint does not exist until GREEN.
        """
        from services.api.main import app
        from services.api.routes.parity import get_parity_repository

        empty_repo = MockParityRepository()
        app.dependency_overrides[get_parity_repository] = lambda: empty_repo
        tc = TestClient(app)
        try:
            resp = tc.get("/parity/summary", headers=AUTH_HEADERS)
            body = resp.json()
            assert resp.status_code == 200
            assert body.get("summaries") == []
            assert body.get("total_event_count") == 0
        finally:
            app.dependency_overrides.clear()

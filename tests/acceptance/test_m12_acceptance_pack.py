"""
Acceptance tests for M12: Operator API Docs + Acceptance Pack.

Coverage:
- OpenAPI schema is accessible and contains all Phase 3 endpoints.
- All Phase 3 endpoints return the documented HTTP status codes for the
  happy path (2xx) and canonical error paths (404/422).
- Endpoint response shapes include the required top-level keys.
- Routes: results, readiness, promotions, approvals, audit, queues, feeds,
          feed-health, parity, symbols/lineage, artifacts, health, observability.

Purpose:
    These tests serve as the living contract between the backend API layer and
    the planned Phase 3 UX.  They must all pass before M12 is considered DONE.
    They document the API surface without requiring the UI to be built.

Known lessons:
    LL-008: Route handlers use JSONResponse + dict; no response_model=.
    LL-013: Check all endpoint paths in both unit and acceptance tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api.main import app

# ---------------------------------------------------------------------------
# Shared client fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> TestClient:
    """
    Module-scoped TestClient using the real FastAPI app without any DI overrides.

    All routes must handle requests using their default DI providers (bootstrap
    mocks) so that acceptance tests exercise the full stack.
    """
    return TestClient(app)


# ---------------------------------------------------------------------------
# M12 S3-A: OpenAPI schema completeness
# ---------------------------------------------------------------------------


class TestOpenAPISchema:
    """
    Verify the OpenAPI schema is accessible and documents all Phase 3 endpoints.

    The FastAPI auto-generated schema at /openapi.json must list all routes
    so that operator tooling (Swagger UI, Postman, client generators) works.
    """

    def test_openapi_json_returns_200(self, client: TestClient) -> None:
        """
        GIVEN the FastAPI application is running
        WHEN GET /openapi.json is requested
        THEN 200 is returned with a valid OpenAPI document.
        """
        resp = client.get("/openapi.json")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

    def test_openapi_json_contains_paths_key(self, client: TestClient) -> None:
        """
        GIVEN the FastAPI application is running
        WHEN GET /openapi.json is requested
        THEN the response body contains a 'paths' key.
        """
        body = client.get("/openapi.json").json()
        assert "paths" in body, f"'paths' missing from OpenAPI schema: {list(body.keys())}"

    def test_openapi_schema_has_required_endpoints(self, client: TestClient) -> None:
        """
        GIVEN the FastAPI application is running
        WHEN GET /openapi.json is requested
        THEN all Phase 3 endpoint paths appear in the schema paths dict.
        """
        paths = client.get("/openapi.json").json().get("paths", {})
        required = [
            "/runs/{run_id}/results",
            "/runs/{run_id}/readiness",
            "/promotions/request",
            "/approvals/{approval_id}/approve",
            "/audit",
            "/audit/{audit_event_id}",
            "/queues/",
            "/queues/{queue_class}/contention",
            "/feeds",
            "/feeds/{feed_id}",
            "/feed-health",
            "/parity/events",
            "/parity/events/{parity_event_id}",
            "/parity/summary",
            "/symbols/{symbol}/lineage",
            "/artifacts",
            "/artifacts/{artifact_id}/download",
            "/data/certification",
            "/health",
            "/health/dependencies",
            "/health/diagnostics",
        ]
        missing = [ep for ep in required if ep not in paths]
        assert not missing, f"Missing endpoints from OpenAPI schema: {missing}"

    def test_swagger_ui_accessible(self, client: TestClient) -> None:
        """
        GIVEN the FastAPI application is running
        WHEN GET /docs is requested
        THEN 200 is returned (Swagger UI is served).
        """
        resp = client.get("/docs")
        assert resp.status_code == 200, f"Swagger UI not accessible: {resp.status_code}"


# ---------------------------------------------------------------------------
# M12 S3-B: Run results and readiness endpoints
# ---------------------------------------------------------------------------


class TestRunEndpoints:
    """
    Acceptance tests for /runs/{run_id}/results and /runs/{run_id}/readiness.
    """

    _VALID_RUN_ID = "01HQ7X9Z8K3M4N5P6Q7R8S9T0A"

    def test_run_results_returns_200_for_valid_id(self, client: TestClient) -> None:
        """
        GIVEN a valid ULID run_id
        WHEN GET /runs/{run_id}/results is requested
        THEN 200 is returned.
        """
        resp = client.get(f"/runs/{self._VALID_RUN_ID}/results")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_run_results_shape(self, client: TestClient) -> None:
        """
        GIVEN a valid run_id
        WHEN GET /runs/{run_id}/results is requested
        THEN response body contains 'run_id', 'metrics', 'artifacts'.
        """
        body = client.get(f"/runs/{self._VALID_RUN_ID}/results").json()
        for key in ("run_id", "metrics", "artifacts"):
            assert key in body, f"Missing '{key}' in results: {body}"

    def test_run_readiness_returns_200_for_valid_id(self, client: TestClient) -> None:
        """
        GIVEN a valid ULID run_id
        WHEN GET /runs/{run_id}/readiness is requested
        THEN 200 is returned.
        """
        resp = client.get(f"/runs/{self._VALID_RUN_ID}/readiness")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_run_readiness_shape(self, client: TestClient) -> None:
        """
        GIVEN a valid run_id
        WHEN GET /runs/{run_id}/readiness is requested
        THEN response body contains 'run_id', 'readiness_grade', 'blockers'.
        """
        body = client.get(f"/runs/{self._VALID_RUN_ID}/readiness").json()
        for key in ("run_id", "readiness_grade", "blockers"):
            assert key in body, f"Missing '{key}' in readiness: {body}"


# ---------------------------------------------------------------------------
# M12 S3-C: Promotions and approvals
# ---------------------------------------------------------------------------


class TestGovernanceEndpoints:
    """
    Acceptance tests for /promotions/request and /approvals/{id}/approve.
    """

    def test_promotions_request_returns_2xx(self, client: TestClient) -> None:
        """
        GIVEN a minimal promotion payload (candidate_id + target_environment)
        WHEN POST /promotions/request is requested
        THEN a 2xx response is returned (200 or 201 or 202).

        Note: PromotionRequest requires candidate_id and target_environment (TargetEnvironment enum).
        """
        payload = {
            "candidate_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0B",
            "requester_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0C",
            "target_environment": "paper",
        }
        resp = client.post("/promotions/request", json=payload)
        assert resp.status_code in (200, 201, 202), (
            f"Expected 2xx from promotions, got {resp.status_code}: {resp.text}"
        )

    def test_approvals_approve_returns_2xx_or_404(self, client: TestClient) -> None:
        """
        GIVEN an approval_id
        WHEN POST /approvals/{id}/approve is requested
        THEN a 2xx or 404 is returned (2xx for known ID, 404 for unknown).

        Note: Bootstrap mock may return 2xx for any ID.
        """
        approval_id = "01HQ7X9Z8K3M4N5P6Q7R8S9T0D"
        resp = client.post(f"/approvals/{approval_id}/approve", json={})
        assert resp.status_code in (200, 201, 202, 404), (
            f"Unexpected status from approvals: {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# M12 S3-D: Audit explorer
# ---------------------------------------------------------------------------


class TestAuditEndpoints:
    """
    Acceptance tests for /audit and /audit/{audit_event_id}.
    """

    def test_audit_list_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /audit is requested
        THEN 200 is returned.
        """
        resp = client.get("/audit")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_audit_list_shape(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /audit is requested
        THEN response body contains 'events' and 'next_cursor'.
        """
        body = client.get("/audit").json()
        for key in ("events", "next_cursor"):
            assert key in body, f"Missing '{key}' in audit list: {body}"

    def test_audit_events_is_list(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /audit is requested
        THEN 'events' is a list.
        """
        body = client.get("/audit").json()
        assert isinstance(body["events"], list), f"'events' not a list: {type(body['events'])}"

    def test_audit_detail_unknown_id_returns_404(self, client: TestClient) -> None:
        """
        GIVEN an unknown audit_event_id
        WHEN GET /audit/{audit_event_id} is requested
        THEN 404 is returned.
        """
        resp = client.get("/audit/01HQZZZZZZZZZZZZZZZZZZZZZZ")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# M12 S3-E: Queue endpoints
# ---------------------------------------------------------------------------


class TestQueueEndpoints:
    """
    Acceptance tests for /queues/ and /queues/{queue_class}/contention.
    """

    def test_queues_list_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no special setup
        WHEN GET /queues/ is requested
        THEN 200 is returned.
        """
        resp = client.get("/queues/")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_queues_list_contains_queues_key(self, client: TestClient) -> None:
        """
        GIVEN no special setup
        WHEN GET /queues/ is requested
        THEN response body contains a 'queues' key.
        """
        body = client.get("/queues/").json()
        assert "queues" in body, f"Missing 'queues' key: {body}"

    def test_queues_contention_unknown_class_returns_404(
        self, client: TestClient
    ) -> None:
        """
        GIVEN an unknown queue_class
        WHEN GET /queues/{queue_class}/contention is requested
        THEN 404 is returned.
        """
        resp = client.get("/queues/nonexistent_class/contention")
        assert resp.status_code == 404, (
            f"Expected 404 for unknown queue class, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# M12 S3-F: Feed endpoints
# ---------------------------------------------------------------------------


class TestFeedEndpoints:
    """
    Acceptance tests for /feeds, /feeds/{feed_id}, and /feed-health.
    """

    def test_feeds_list_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /feeds is requested
        THEN 200 is returned.
        """
        resp = client.get("/feeds")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_feeds_list_contains_feeds_key(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /feeds is requested
        THEN response body contains 'feeds'.
        """
        body = client.get("/feeds").json()
        assert "feeds" in body, f"Missing 'feeds' key: {body}"

    def test_feeds_feeds_is_list(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /feeds is requested
        THEN 'feeds' is a list.
        """
        body = client.get("/feeds").json()
        assert isinstance(body["feeds"], list), f"Expected list: {body}"

    def test_feed_detail_unknown_id_returns_404(self, client: TestClient) -> None:
        """
        GIVEN an unknown feed_id
        WHEN GET /feeds/{feed_id} is requested
        THEN 404 is returned.
        """
        resp = client.get("/feeds/01HQZZZZZZZZZZZZZZZZZZZZZZ")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_feed_health_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /feed-health is requested
        THEN 200 is returned.
        """
        resp = client.get("/feed-health")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_feed_health_contains_feeds_key(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /feed-health is requested
        THEN response body contains 'feeds' (feed health snapshot list).
        """
        body = client.get("/feed-health").json()
        assert "feeds" in body, f"Missing 'feeds' key: {body}"


# ---------------------------------------------------------------------------
# M12 S3-G: Parity endpoints
# ---------------------------------------------------------------------------


class TestParityEndpoints:
    """
    Acceptance tests for /parity/events, /parity/events/{id}, /parity/summary.
    """

    def test_parity_events_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /parity/events is requested
        THEN 200 is returned.
        """
        resp = client.get("/parity/events")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_parity_events_contains_events_key(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /parity/events is requested
        THEN response body contains 'events'.
        """
        body = client.get("/parity/events").json()
        assert "events" in body, f"Missing 'events' key: {body}"

    def test_parity_events_filter_by_severity(self, client: TestClient) -> None:
        """
        GIVEN ?severity=CRITICAL filter
        WHEN GET /parity/events is requested
        THEN 200 is returned (empty list is valid).
        """
        resp = client.get("/parity/events?severity=CRITICAL")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_parity_event_detail_unknown_returns_404(
        self, client: TestClient
    ) -> None:
        """
        GIVEN an unknown parity_event_id
        WHEN GET /parity/events/{id} is requested
        THEN 404 is returned.
        """
        resp = client.get("/parity/events/01HQZZZZZZZZZZZZZZZZZZZZZZ")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def test_parity_summary_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /parity/summary is requested
        THEN 200 is returned.
        """
        resp = client.get("/parity/summary")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_parity_summary_contains_summaries_key(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /parity/summary is requested
        THEN response body contains 'summaries'.
        """
        body = client.get("/parity/summary").json()
        assert "summaries" in body, f"Missing 'summaries' key: {body}"


# ---------------------------------------------------------------------------
# M12 S3-H: Symbol lineage
# ---------------------------------------------------------------------------


class TestSymbolLineageEndpoints:
    """
    Acceptance tests for /symbols/{symbol}/lineage.
    """

    def test_symbol_lineage_unknown_symbol_returns_404(
        self, client: TestClient
    ) -> None:
        """
        GIVEN an unknown symbol
        WHEN GET /symbols/{symbol}/lineage is requested
        THEN 404 is returned.
        """
        resp = client.get("/symbols/ZZZZZZZZZ/lineage")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


# ---------------------------------------------------------------------------
# M12 S3-I: Artifacts
# ---------------------------------------------------------------------------


class TestArtifactEndpoints:
    """
    Acceptance tests for /artifacts and /artifacts/{artifact_id}/download.
    """

    def test_artifacts_list_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /artifacts is requested
        THEN 200 is returned.
        """
        resp = client.get("/artifacts")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_artifacts_list_contains_artifacts_key(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /artifacts is requested
        THEN response body contains 'artifacts'.
        """
        body = client.get("/artifacts").json()
        assert "artifacts" in body, f"Missing 'artifacts' key: {body}"

    def test_artifact_download_unknown_returns_404(self, client: TestClient) -> None:
        """
        GIVEN an unknown artifact_id
        WHEN GET /artifacts/{artifact_id}/download is requested
        THEN 404 is returned.
        """
        resp = client.get("/artifacts/01HQZZZZZZZZZZZZZZZZZZZZZZ/download")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


# ---------------------------------------------------------------------------
# M12 S3-J: Certification viewer
# ---------------------------------------------------------------------------


class TestCertificationEndpoints:
    """
    Acceptance tests for /data/certification.
    """

    def test_certification_list_returns_200(self, client: TestClient) -> None:
        """
        GIVEN no filters
        WHEN GET /data/certification is requested
        THEN 200 is returned.
        """
        resp = client.get("/data/certification")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_certification_list_contains_certifications_key(
        self, client: TestClient
    ) -> None:
        """
        GIVEN no filters
        WHEN GET /data/certification is requested
        THEN response body contains 'certifications'.
        """
        body = client.get("/data/certification").json()
        assert "certifications" in body, f"Missing 'certifications' key: {body}"


# ---------------------------------------------------------------------------
# M12 S3-K: Observability (health + diagnostics)
# ---------------------------------------------------------------------------


class TestObservabilityEndpoints:
    """
    Acceptance tests for /health, /health/dependencies, /health/diagnostics.
    """

    def test_health_returns_200(self, client: TestClient) -> None:
        """
        GIVEN the service is running
        WHEN GET /health is requested
        THEN 200 is returned.
        """
        resp = client.get("/health")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_health_dependencies_returns_200(self, client: TestClient) -> None:
        """
        GIVEN the service is running
        WHEN GET /health/dependencies is requested
        THEN 200 is returned.
        """
        resp = client.get("/health/dependencies")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_health_dependencies_has_overall_status(self, client: TestClient) -> None:
        """
        GIVEN the service is running
        WHEN GET /health/dependencies is requested
        THEN response body contains 'overall_status'.
        """
        body = client.get("/health/dependencies").json()
        assert "overall_status" in body, f"Missing 'overall_status': {body}"

    def test_health_diagnostics_returns_200(self, client: TestClient) -> None:
        """
        GIVEN the service is running
        WHEN GET /health/diagnostics is requested
        THEN 200 is returned.
        """
        resp = client.get("/health/diagnostics")
        assert resp.status_code == 200, f"Expected 200: {resp.text}"

    def test_health_diagnostics_has_count_fields(self, client: TestClient) -> None:
        """
        GIVEN the service is running
        WHEN GET /health/diagnostics is requested
        THEN response body contains all four count fields.
        """
        body = client.get("/health/diagnostics").json()
        for key in (
            "queue_contention_count",
            "feed_health_count",
            "parity_critical_count",
            "certification_blocked_count",
        ):
            assert key in body, f"Missing '{key}': {body}"

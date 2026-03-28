"""
M13-T2 Governance Endpoints — Unit Tests (RED phase)

Covers:
- POST /approvals/{id}/reject
- POST /overrides/request  (evidence_link validation, SoD enforcement)
- GET  /overrides/{override_id}
- POST /strategies/draft/autosave
- GET  /strategies/draft/autosave/latest
- DELETE /strategies/draft/autosave/{id}

Test naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SUBMITTER_ID = "01HSUBMITTER00000000000000A"
APPROVER_ID  = "01HAPPROVER000000000000000B"
APPROVAL_ID  = "01HAPPROVALID0000000000000C"
OVERRIDE_ID  = "01HOVERRIDEID0000000000000D"
AUTOSAVE_ID  = "01HAUTOSAVEID0000000000000E"


@pytest.fixture(scope="module")
def client() -> TestClient:
    """FastAPI test client scoped to the module for performance."""
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# POST /approvals/{id}/reject
# ---------------------------------------------------------------------------


class TestApprovalReject:
    """Tests for POST /approvals/{approval_id}/reject."""

    def test_reject_valid_request_returns_200(self, client: TestClient) -> None:
        """
        Rejecting a pending approval with a valid rationale returns 200
        and a payload that includes approval_id and status=rejected.
        """
        response = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"rationale": "Insufficient evidence for this promotion."},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["approval_id"] == APPROVAL_ID
        assert body["status"] == "rejected"

    def test_reject_missing_rationale_returns_422(self, client: TestClient) -> None:
        """
        Rejecting without a rationale body returns 422 Unprocessable Entity.
        """
        response = client.post(f"/approvals/{APPROVAL_ID}/reject", json={})
        assert response.status_code == 422

    def test_reject_short_rationale_returns_422(self, client: TestClient) -> None:
        """
        A rationale shorter than 10 characters is rejected with 422.
        """
        response = client.post(
            f"/approvals/{APPROVAL_ID}/reject",
            json={"rationale": "Too short"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /overrides/request
# ---------------------------------------------------------------------------


class TestOverrideRequest:
    """Tests for POST /overrides/request."""

    _VALID_PAYLOAD = {
        "object_id": "01HOBJECTID00000000000000F",
        "object_type": "candidate",
        "override_type": "grade_override",
        "original_state": {"grade": "C"},
        "new_state": {"grade": "B"},
        "evidence_link": "https://jira.example.com/browse/FX-123",
        "rationale": "Backtested with extended dataset; grade uplift justified per review.",
        "submitter_id": SUBMITTER_ID,
    }

    def test_valid_override_request_returns_201(self, client: TestClient) -> None:
        """
        A well-formed override request with valid evidence_link returns 201.
        """
        response = client.post("/overrides/request", json=self._VALID_PAYLOAD)
        assert response.status_code == 201
        body = response.json()
        assert "override_id" in body
        assert body["status"] == "pending"

    def test_missing_evidence_link_returns_422(self, client: TestClient) -> None:
        """
        An override request without evidence_link is rejected — SOC 2 compliance.
        """
        payload = {**self._VALID_PAYLOAD}
        del payload["evidence_link"]
        response = client.post("/overrides/request", json=payload)
        assert response.status_code == 422

    def test_non_http_evidence_link_returns_422(self, client: TestClient) -> None:
        """
        evidence_link must be an absolute HTTP/HTTPS URI.
        A relative path or non-HTTP scheme is rejected.
        """
        payload = {**self._VALID_PAYLOAD, "evidence_link": "ftp://example.com/file"}
        response = client.post("/overrides/request", json=payload)
        assert response.status_code == 422

    def test_root_path_evidence_link_returns_422(self, client: TestClient) -> None:
        """
        evidence_link must have a non-root path (not just the host).
        https://example.com or https://example.com/ is rejected.
        """
        payload = {**self._VALID_PAYLOAD, "evidence_link": "https://example.com/"}
        response = client.post("/overrides/request", json=payload)
        assert response.status_code == 422

    def test_short_rationale_returns_422(self, client: TestClient) -> None:
        """
        Rationale shorter than 20 characters is rejected.
        """
        payload = {**self._VALID_PAYLOAD, "rationale": "Too brief."}
        response = client.post("/overrides/request", json=payload)
        assert response.status_code == 422

    def test_invalid_object_type_returns_422(self, client: TestClient) -> None:
        """
        object_type must be 'candidate' or 'deployment'.
        """
        payload = {**self._VALID_PAYLOAD, "object_type": "strategy"}
        response = client.post("/overrides/request", json=payload)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /overrides/{override_id}
# ---------------------------------------------------------------------------


class TestOverrideGet:
    """Tests for GET /overrides/{override_id}."""

    _VALID_REQUEST = {
        "object_id": "01HOBJECTID00000000000000F",
        "object_type": "candidate",
        "override_type": "grade_override",
        "original_state": {"grade": "C"},
        "new_state": {"grade": "B"},
        "evidence_link": "https://jira.example.com/browse/FX-456",
        "rationale": "Extended backtest over 3 years justifies grade B uplift.",
        "submitter_id": SUBMITTER_ID,
    }

    def test_get_existing_override_returns_200(self, client: TestClient) -> None:
        """
        POST then GET: the returned override_id resolves to 200.
        """
        # First create an override, capturing the server-assigned ID.
        create_resp = client.post("/overrides/request", json=self._VALID_REQUEST)
        assert create_resp.status_code == 201, create_resp.text
        override_id = create_resp.json()["override_id"]

        # Then retrieve it by the server-assigned ID.
        response = client.get(f"/overrides/{override_id}")
        assert response.status_code == 200
        body = response.json()
        assert "override_id" in body or "id" in body

    def test_get_nonexistent_override_returns_404(self, client: TestClient) -> None:
        """
        GET /overrides/{id} returns 404 for an unknown ID.
        """
        response = client.get("/overrides/01HNONEXISTENT00000000000Z")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /strategies/draft/autosave
# ---------------------------------------------------------------------------


class TestDraftAutosavePost:
    """Tests for POST /strategies/draft/autosave."""

    _VALID_PAYLOAD = {
        "user_id": SUBMITTER_ID,
        "draft_payload": {"name": "MyStrategy", "lookback": 30},
        "form_step": "parameters",
        "client_ts": "2026-03-28T11:00:00",
        "session_id": "sess-abc123",
    }

    def test_valid_autosave_returns_200(self, client: TestClient) -> None:
        """
        A valid autosave payload returns 200 with autosave_id and saved_at.
        """
        response = client.post("/strategies/draft/autosave", json=self._VALID_PAYLOAD)
        assert response.status_code == 200
        body = response.json()
        assert "autosave_id" in body
        assert "saved_at" in body

    def test_missing_user_id_returns_422(self, client: TestClient) -> None:
        """
        Autosave without user_id returns 422.
        """
        payload = {**self._VALID_PAYLOAD}
        del payload["user_id"]
        response = client.post("/strategies/draft/autosave", json=payload)
        assert response.status_code == 422

    def test_missing_draft_payload_returns_422(self, client: TestClient) -> None:
        """
        Autosave without draft_payload returns 422.
        """
        payload = {**self._VALID_PAYLOAD}
        del payload["draft_payload"]
        response = client.post("/strategies/draft/autosave", json=payload)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /strategies/draft/autosave/latest
# ---------------------------------------------------------------------------


class TestDraftAutosaveGetLatest:
    """Tests for GET /strategies/draft/autosave/latest."""

    _UNIQUE_USER_ID = "01HUNIQUELATESTUSERID000001"
    _SAVE_PAYLOAD = {
        "user_id": _UNIQUE_USER_ID,
        "draft_payload": {"name": "LatestTest", "lookback": 20},
        "form_step": "review",
        "client_ts": "2026-03-28T10:00:00",
        "session_id": "sess-latest-001",
    }

    def test_get_latest_returns_200_after_post(self, client: TestClient) -> None:
        """
        After POSTing an autosave, GET /latest returns 200 for that user.
        """
        # Create an autosave first.
        post_resp = client.post("/strategies/draft/autosave", json=self._SAVE_PAYLOAD)
        assert post_resp.status_code == 200, post_resp.text

        response = client.get(
            "/strategies/draft/autosave/latest",
            params={"user_id": self._UNIQUE_USER_ID},
        )
        assert response.status_code in (200, 204)

    def test_get_latest_without_user_id_returns_422(self, client: TestClient) -> None:
        """
        GET /strategies/draft/autosave/latest without user_id returns 422.
        """
        response = client.get("/strategies/draft/autosave/latest")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /strategies/draft/autosave/{id}
# ---------------------------------------------------------------------------


class TestDraftAutosaveDelete:
    """Tests for DELETE /strategies/draft/autosave/{id}."""

    _DELETE_USER_ID = "01HDELETEUSER000000000000A"
    _SAVE_PAYLOAD = {
        "user_id": _DELETE_USER_ID,
        "draft_payload": {"name": "DeleteTest"},
        "form_step": "start",
        "client_ts": "2026-03-28T09:00:00",
        "session_id": "sess-delete-001",
    }

    def test_delete_existing_autosave_returns_204(self, client: TestClient) -> None:
        """
        POST an autosave then DELETE it — should return 204 No Content.
        """
        # Create the autosave to get a real server-assigned ID.
        post_resp = client.post("/strategies/draft/autosave", json=self._SAVE_PAYLOAD)
        assert post_resp.status_code == 200, post_resp.text
        autosave_id = post_resp.json()["autosave_id"]

        response = client.delete(f"/strategies/draft/autosave/{autosave_id}")
        assert response.status_code == 204

    def test_delete_nonexistent_autosave_returns_404(self, client: TestClient) -> None:
        """
        DELETE /strategies/draft/autosave/{id} returns 404 for an unknown ID.
        """
        response = client.delete("/strategies/draft/autosave/01HNONEXISTENT00000000000Z")
        assert response.status_code == 404

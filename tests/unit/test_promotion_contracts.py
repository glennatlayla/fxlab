"""
Unit tests for promotion workflow contracts (libs.contracts.promotion).

Tests verify:
- PromotionRequest initialization and validation.
- PromotionJobResponse initialization.
- ULID pattern validation for IDs.
- Optional fields are handled correctly.
- Serialization (model_dump, model_dump_json) works as expected.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from libs.contracts.enums import Environment, PromotionStatus
from libs.contracts.promotion import PromotionJobResponse, PromotionRequest


class TestPromotionRequestInitialization:
    """Tests for PromotionRequest initialization."""

    def test_promotion_request_with_required_fields(self) -> None:
        """
        PromotionRequest can be created with required fields only.

        Scenario:
        - Create PromotionRequest with candidate_id, target_environment, requester_id.

        Expected:
        - All fields are set correctly.
        - notes is None.
        """
        request = PromotionRequest(
            candidate_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            target_environment=Environment.research,
            requester_id="01ARZ3NDEKTSV4RRFFQ69G5FB0",
        )

        assert request.candidate_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        assert request.target_environment == Environment.research
        assert request.requester_id == "01ARZ3NDEKTSV4RRFFQ69G5FB0"
        assert request.notes is None

    def test_promotion_request_with_optional_notes(self) -> None:
        """
        PromotionRequest accepts optional notes.

        Scenario:
        - Create PromotionRequest with notes.

        Expected:
        - notes field is set correctly.
        """
        request = PromotionRequest(
            candidate_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            target_environment=Environment.live,
            requester_id="01ARZ3NDEKTSV4RRFFQ69G5FB0",
            notes="Approved by review team",
        )

        assert request.notes == "Approved by review team"

    def test_promotion_request_with_all_environments(self) -> None:
        """
        PromotionRequest accepts any valid Environment enum value.

        Scenario:
        - Create PromotionRequest with different environments.

        Expected:
        - Each environment is accepted.
        """
        for env in Environment:
            request = PromotionRequest(
                candidate_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                target_environment=env,
                requester_id="01ARZ3NDEKTSV4RRFFQ69G5FB0",
            )
            assert request.target_environment == env

    def test_promotion_request_validates_candidate_id_pattern(self) -> None:
        """
        PromotionRequest validates candidate_id ULID pattern.

        Scenario:
        - Create PromotionRequest with invalid candidate_id.

        Expected:
        - Raises ValidationError.
        """
        with pytest.raises(ValidationError):
            PromotionRequest(
                candidate_id="invalid_id",  # Not a ULID
                target_environment=Environment.research,
                requester_id="01ARZ3NDEKTSV4RRFFQ69G5FB0",
            )

    def test_promotion_request_validates_requester_id_pattern(self) -> None:
        """
        PromotionRequest validates requester_id ULID pattern.

        Scenario:
        - Create PromotionRequest with invalid requester_id.

        Expected:
        - Raises ValidationError.
        """
        with pytest.raises(ValidationError):
            PromotionRequest(
                candidate_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                target_environment=Environment.research,
                requester_id="not_a_ulid",  # Not a ULID
            )

    def test_promotion_request_ulid_pattern_accepts_valid_ulids(self) -> None:
        """
        PromotionRequest ULID pattern accepts valid ULID strings.

        Scenario:
        - Create PromotionRequest with valid ULIDs.

        Expected:
        - Request is created successfully.
        """
        # Valid ULIDs (26 alphanumeric characters, Crockford base32 alphabet)
        valid_ulids = [
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",  # Example ULID
            "01BX5ZZKBK4T2JYP33A0CKW7DB",  # Another example
        ]

        for ulid in valid_ulids:
            request = PromotionRequest(
                candidate_id=ulid,
                target_environment=Environment.research,
                requester_id=ulid,
            )
            assert request.candidate_id == ulid
            assert request.requester_id == ulid


class TestPromotionRequestSerialization:
    """Tests for PromotionRequest serialization."""

    def test_promotion_request_model_dump(self) -> None:
        """
        PromotionRequest can be serialized to dict.

        Scenario:
        - Create PromotionRequest and call model_dump().

        Expected:
        - Returns dict with all fields.
        """
        request = PromotionRequest(
            candidate_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            target_environment=Environment.research,
            requester_id="01ARZ3NDEKTSV4RRFFQ69G5FB0",
            notes="Approval granted",
        )

        dumped = request.model_dump()

        assert dumped["candidate_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        assert dumped["target_environment"] == Environment.research
        assert dumped["requester_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FB0"
        assert dumped["notes"] == "Approval granted"

    def test_promotion_request_model_dump_json(self) -> None:
        """
        PromotionRequest can be serialized to JSON.

        Scenario:
        - Create PromotionRequest and call model_dump_json().

        Expected:
        - Returns valid JSON string with all fields.
        """
        request = PromotionRequest(
            candidate_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            target_environment=Environment.research,
            requester_id="01ARZ3NDEKTSV4RRFFQ69G5FB0",
            notes="Test notes",
        )

        json_str = request.model_dump_json()

        assert "01ARZ3NDEKTSV4RRFFQ69G5FAV" in json_str
        assert "research" in json_str.lower()
        assert "Test notes" in json_str


class TestPromotionJobResponseInitialization:
    """Tests for PromotionJobResponse initialization."""

    def test_promotion_job_response_creation(self) -> None:
        """
        PromotionJobResponse can be created with required fields.

        Scenario:
        - Create PromotionJobResponse with job_id and status.

        Expected:
        - All fields are set correctly.
        """
        response = PromotionJobResponse(
            job_id="01ARZ3NDEKTSV4RRFFQ69G5FB1",
            status=PromotionStatus.pending,
        )

        assert response.job_id == "01ARZ3NDEKTSV4RRFFQ69G5FB1"
        assert response.status == PromotionStatus.pending

    def test_promotion_job_response_with_all_statuses(self) -> None:
        """
        PromotionJobResponse accepts any valid PromotionStatus enum value.

        Scenario:
        - Create PromotionJobResponse with different statuses.

        Expected:
        - Each status is accepted.
        """
        for status in PromotionStatus:
            response = PromotionJobResponse(
                job_id="01ARZ3NDEKTSV4RRFFQ69G5FB1",
                status=status,
            )
            assert response.status == status

    def test_promotion_job_response_validates_job_id_pattern(self) -> None:
        """
        PromotionJobResponse validates job_id ULID pattern.

        Scenario:
        - Create PromotionJobResponse with invalid job_id.

        Expected:
        - Raises ValidationError.
        """
        with pytest.raises(ValidationError):
            PromotionJobResponse(
                job_id="invalid_job_id",  # Not a ULID
                status=PromotionStatus.pending,
            )

    def test_promotion_job_response_ulid_pattern_accepts_valid_ulids(
        self,
    ) -> None:
        """
        PromotionJobResponse ULID pattern accepts valid ULID strings.

        Scenario:
        - Create PromotionJobResponse with valid ULIDs.

        Expected:
        - Response is created successfully.
        """
        valid_ulids = [
            "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "01BX5ZZKBK4T2JYP33A0CKW7DB",
        ]

        for ulid in valid_ulids:
            response = PromotionJobResponse(
                job_id=ulid,
                status=PromotionStatus.deploying,
            )
            assert response.job_id == ulid


class TestPromotionJobResponseSerialization:
    """Tests for PromotionJobResponse serialization."""

    def test_promotion_job_response_model_dump(self) -> None:
        """
        PromotionJobResponse can be serialized to dict.

        Scenario:
        - Create PromotionJobResponse and call model_dump().

        Expected:
        - Returns dict with all fields.
        """
        response = PromotionJobResponse(
            job_id="01ARZ3NDEKTSV4RRFFQ69G5FB1",
            status=PromotionStatus.completed,
        )

        dumped = response.model_dump()

        assert dumped["job_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FB1"
        assert dumped["status"] == PromotionStatus.completed

    def test_promotion_job_response_model_dump_json(self) -> None:
        """
        PromotionJobResponse can be serialized to JSON.

        Scenario:
        - Create PromotionJobResponse and call model_dump_json().

        Expected:
        - Returns valid JSON string with all fields.
        """
        response = PromotionJobResponse(
            job_id="01ARZ3NDEKTSV4RRFFQ69G5FB1",
            status=PromotionStatus.pending,
        )

        json_str = response.model_dump_json()

        assert "01ARZ3NDEKTSV4RRFFQ69G5FB1" in json_str
        # Status might be serialized as string value
        assert "pending" in json_str.lower()

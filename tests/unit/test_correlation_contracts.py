"""
Unit tests for CorrelationContext contract (libs.contracts.correlation).

Tests verify:
- CorrelationContext initialization with default and provided values.
- Field validators ensure non-empty strings are accepted.
- Field validators reject empty or whitespace-only strings.
- Pydantic model validation and serialization.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from libs.contracts.correlation import CorrelationContext


class TestCorrelationContextInitialization:
    """Tests for CorrelationContext initialization."""

    def test_correlation_context_with_service_name_only(self) -> None:
        """
        CorrelationContext can be created with just service_name.

        Scenario:
        - Create CorrelationContext(service_name="my_service").

        Expected:
        - correlation_id is auto-generated (UUID).
        - parent_id is None.
        - service_name is set correctly.
        """
        context = CorrelationContext(service_name="my_service")

        assert context.service_name == "my_service"
        assert context.parent_id is None
        assert context.correlation_id is not None
        assert len(context.correlation_id) > 0

    def test_correlation_context_with_explicit_correlation_id(self) -> None:
        """
        CorrelationContext accepts an explicit correlation_id.

        Scenario:
        - Create CorrelationContext with explicit correlation_id.

        Expected:
        - Uses the provided correlation_id instead of auto-generating.
        """
        explicit_id = str(uuid.uuid4())
        context = CorrelationContext(
            correlation_id=explicit_id,
            service_name="my_service",
        )

        assert context.correlation_id == explicit_id
        assert context.service_name == "my_service"

    def test_correlation_context_with_parent_id(self) -> None:
        """
        CorrelationContext accepts a parent_id for nested operations.

        Scenario:
        - Create CorrelationContext with parent_id.

        Expected:
        - parent_id is set correctly.
        """
        parent_id = str(uuid.uuid4())
        context = CorrelationContext(
            parent_id=parent_id,
            service_name="child_service",
        )

        assert context.parent_id == parent_id
        assert context.service_name == "child_service"

    def test_correlation_context_with_all_fields(self) -> None:
        """
        CorrelationContext can be created with all fields provided.

        Scenario:
        - Create CorrelationContext with correlation_id, parent_id, service_name.

        Expected:
        - All fields are set correctly.
        """
        corr_id = str(uuid.uuid4())
        parent_id = str(uuid.uuid4())
        context = CorrelationContext(
            correlation_id=corr_id,
            parent_id=parent_id,
            service_name="service_a",
        )

        assert context.correlation_id == corr_id
        assert context.parent_id == parent_id
        assert context.service_name == "service_a"


class TestCorrelationContextValidators:
    """Tests for CorrelationContext field validators."""

    def test_correlation_id_validator_rejects_empty_string(self) -> None:
        """
        correlation_id validator rejects empty string.

        Scenario:
        - Create CorrelationContext with empty correlation_id.

        Expected:
        - Raises ValidationError.
        """
        with pytest.raises(ValidationError) as exc_info:
            CorrelationContext(
                correlation_id="",
                service_name="service",
            )

        assert "correlation_id must not be empty" in str(exc_info.value)

    def test_correlation_id_validator_rejects_whitespace_only(self) -> None:
        """
        correlation_id validator rejects whitespace-only string.

        Scenario:
        - Create CorrelationContext with whitespace-only correlation_id.

        Expected:
        - Raises ValidationError.
        """
        with pytest.raises(ValidationError) as exc_info:
            CorrelationContext(
                correlation_id="   ",
                service_name="service",
            )

        assert "correlation_id must not be empty" in str(exc_info.value)

    def test_correlation_id_validator_strips_whitespace(self) -> None:
        """
        correlation_id validator strips leading/trailing whitespace.

        Scenario:
        - Create CorrelationContext with correlation_id containing whitespace.

        Expected:
        - Whitespace is stripped.
        """
        context = CorrelationContext(
            correlation_id="  abc-123  ",
            service_name="service",
        )

        assert context.correlation_id == "abc-123"

    def test_service_name_validator_rejects_empty_string(self) -> None:
        """
        service_name validator rejects empty string.

        Scenario:
        - Create CorrelationContext with empty service_name.

        Expected:
        - Raises ValidationError.
        """
        with pytest.raises(ValidationError) as exc_info:
            CorrelationContext(service_name="")

        assert "service_name must not be empty" in str(exc_info.value)

    def test_service_name_validator_rejects_whitespace_only(self) -> None:
        """
        service_name validator rejects whitespace-only string.

        Scenario:
        - Create CorrelationContext with whitespace-only service_name.

        Expected:
        - Raises ValidationError.
        """
        with pytest.raises(ValidationError) as exc_info:
            CorrelationContext(service_name="   ")

        assert "service_name must not be empty" in str(exc_info.value)

    def test_service_name_validator_strips_whitespace(self) -> None:
        """
        service_name validator strips leading/trailing whitespace.

        Scenario:
        - Create CorrelationContext with service_name containing whitespace.

        Expected:
        - Whitespace is stripped.
        """
        context = CorrelationContext(service_name="  api_service  ")

        assert context.service_name == "api_service"


class TestCorrelationContextSerialization:
    """Tests for CorrelationContext serialization."""

    def test_correlation_context_model_dump(self) -> None:
        """
        CorrelationContext can be serialized to dict.

        Scenario:
        - Create CorrelationContext and call model_dump().

        Expected:
        - Returns dict with all fields.
        """
        context = CorrelationContext(
            correlation_id="abc123",
            parent_id="xyz789",
            service_name="my_service",
        )

        dumped = context.model_dump()

        assert dumped["correlation_id"] == "abc123"
        assert dumped["parent_id"] == "xyz789"
        assert dumped["service_name"] == "my_service"

    def test_correlation_context_model_dump_json(self) -> None:
        """
        CorrelationContext can be serialized to JSON.

        Scenario:
        - Create CorrelationContext and call model_dump_json().

        Expected:
        - Returns valid JSON string with all fields.
        """
        context = CorrelationContext(
            correlation_id="abc123",
            parent_id="xyz789",
            service_name="my_service",
        )

        json_str = context.model_dump_json()

        assert "abc123" in json_str
        assert "xyz789" in json_str
        assert "my_service" in json_str

    def test_correlation_context_model_dump_exclude_none(self) -> None:
        """
        CorrelationContext serialization can exclude None fields.

        Scenario:
        - Create CorrelationContext without parent_id.
        - Call model_dump(exclude_none=True).

        Expected:
        - parent_id is not included in output.
        """
        context = CorrelationContext(
            correlation_id="abc123",
            service_name="my_service",
        )

        dumped = context.model_dump(exclude_none=True)

        assert "correlation_id" in dumped
        assert "service_name" in dumped
        assert "parent_id" not in dumped

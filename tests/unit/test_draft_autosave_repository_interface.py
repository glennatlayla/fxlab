"""
Unit tests for DraftAutosaveRepositoryInterface (libs.contracts.interfaces.draft_autosave_repository).

Tests verify:
- DraftAutosaveRepositoryInterface is an abstract base class.
- All required abstract methods are properly declared.
- Concrete implementations can satisfy the interface.
"""

from __future__ import annotations

from typing import Any

import pytest

from libs.contracts.interfaces.draft_autosave_repository import (
    DraftAutosaveRepositoryInterface,
)


class ConcreteDraftAutosaveRepository(DraftAutosaveRepositoryInterface):
    """Concrete implementation of DraftAutosaveRepositoryInterface for testing."""

    def create(
        self,
        *,
        user_id: str,
        draft_payload: dict[str, Any],
        form_step: str | None = None,
        session_id: str | None = None,
        client_ts: str | None = None,
        strategy_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a draft autosave."""
        return {
            "autosave_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
            "saved_at": "2026-04-13T00:00:00Z",
        }

    def get_latest(self, user_id: str) -> dict[str, Any] | None:
        """Get the latest autosave for a user."""
        return None

    def delete(self, autosave_id: str) -> bool:
        """Delete an autosave by ID."""
        return True

    def purge_expired(self, max_age_days: int = 30) -> int:
        """Purge expired autosaves."""
        return 0


class TestDraftAutosaveRepositoryInterface:
    """Tests for DraftAutosaveRepositoryInterface."""

    def test_interface_is_abstract(self) -> None:
        """
        DraftAutosaveRepositoryInterface cannot be instantiated directly.

        Scenario:
        - Attempt to instantiate DraftAutosaveRepositoryInterface.

        Expected:
        - Raises TypeError (cannot instantiate abstract class).
        """
        with pytest.raises(TypeError):
            DraftAutosaveRepositoryInterface()  # type: ignore

    def test_concrete_implementation_can_be_instantiated(self) -> None:
        """
        Concrete subclass can be instantiated.

        Scenario:
        - Create ConcreteDraftAutosaveRepository.

        Expected:
        - Instance is created successfully.
        """
        repo = ConcreteDraftAutosaveRepository()
        assert isinstance(repo, DraftAutosaveRepositoryInterface)

    def test_concrete_implementation_has_create_method(self) -> None:
        """
        Concrete implementation has create method.

        Scenario:
        - ConcreteDraftAutosaveRepository instance.

        Expected:
        - create method exists and is callable.
        """
        repo = ConcreteDraftAutosaveRepository()
        assert hasattr(repo, "create")
        assert callable(repo.create)

    def test_create_method_can_be_called(self) -> None:
        """
        create method can be called and returns expected result.

        Scenario:
        - Call create with required parameters.

        Expected:
        - Returns dict with autosave_id and saved_at.
        """
        repo = ConcreteDraftAutosaveRepository()
        result = repo.create(
            user_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            draft_payload={"name": "test"},
        )

        assert "autosave_id" in result
        assert "saved_at" in result

    def test_concrete_implementation_has_get_latest_method(self) -> None:
        """
        Concrete implementation has get_latest method.

        Scenario:
        - ConcreteDraftAutosaveRepository instance.

        Expected:
        - get_latest method exists and is callable.
        """
        repo = ConcreteDraftAutosaveRepository()
        assert hasattr(repo, "get_latest")
        assert callable(repo.get_latest)

    def test_get_latest_method_can_be_called(self) -> None:
        """
        get_latest method can be called and returns expected result.

        Scenario:
        - Call get_latest.

        Expected:
        - Returns dict or None.
        """
        repo = ConcreteDraftAutosaveRepository()
        result = repo.get_latest(user_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")

        assert result is None or isinstance(result, dict)

    def test_concrete_implementation_has_delete_method(self) -> None:
        """
        Concrete implementation has delete method.

        Scenario:
        - ConcreteDraftAutosaveRepository instance.

        Expected:
        - delete method exists and is callable.
        """
        repo = ConcreteDraftAutosaveRepository()
        assert hasattr(repo, "delete")
        assert callable(repo.delete)

    def test_delete_method_can_be_called(self) -> None:
        """
        delete method can be called and returns expected result.

        Scenario:
        - Call delete.

        Expected:
        - Returns boolean.
        """
        repo = ConcreteDraftAutosaveRepository()
        result = repo.delete(autosave_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")

        assert isinstance(result, bool)

    def test_concrete_implementation_has_purge_expired_method(self) -> None:
        """
        Concrete implementation has purge_expired method.

        Scenario:
        - ConcreteDraftAutosaveRepository instance.

        Expected:
        - purge_expired method exists and is callable.
        """
        repo = ConcreteDraftAutosaveRepository()
        assert hasattr(repo, "purge_expired")
        assert callable(repo.purge_expired)

    def test_purge_expired_method_can_be_called(self) -> None:
        """
        purge_expired method can be called and returns expected result.

        Scenario:
        - Call purge_expired.

        Expected:
        - Returns integer count.
        """
        repo = ConcreteDraftAutosaveRepository()
        result = repo.purge_expired(max_age_days=30)

        assert isinstance(result, int)
        assert result >= 0

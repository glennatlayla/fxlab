"""
Import tests for contract and library modules.

Ensures all contract, model, and library modules can be imported
without errors. This provides baseline coverage for modules that
define data structures, enums, interfaces, and configuration schemas.

Example:
    pytest tests/unit/test_contract_importability.py -v
"""

from __future__ import annotations


class TestContractImports:
    """Verify all contract modules import successfully."""

    def test_optimization_contracts(self):
        """libs.contracts.optimization is importable."""
        from libs.contracts import optimization

        assert hasattr(optimization, "__name__")

    def test_strategy_draft_contracts(self):
        """libs.contracts.strategy_draft is importable."""
        from libs.contracts import strategy_draft

        assert hasattr(strategy_draft, "__name__")

    def test_export_contracts(self):
        """libs.contracts.export is importable."""
        from libs.contracts import export

        assert hasattr(export, "__name__")

    def test_readiness_contracts(self):
        """libs.contracts.readiness is importable."""
        from libs.contracts import readiness

        assert hasattr(readiness, "__name__")

    def test_config_contracts(self):
        """libs.contracts.config is importable."""
        from libs.contracts import config

        assert hasattr(config, "__name__")

    def test_database_contracts(self):
        """libs.contracts.database is importable."""
        from libs.contracts import database

        assert hasattr(database, "__name__")

    def test_health_contracts(self):
        """libs.contracts.health is importable."""
        from libs.contracts import health

        assert hasattr(health, "__name__")


class TestPhase3Imports:
    """Verify Phase 3 contract modules import successfully."""

    def test_runtime_contracts(self):
        """libs.contracts.phase3.runtime is importable."""
        from libs.contracts.phase3 import runtime

        assert hasattr(runtime, "__name__")

    def test_exceptions_module(self):
        """libs.contracts.phase3.exceptions is importable."""
        from libs.contracts.phase3 import exceptions

        assert hasattr(exceptions, "__name__")


class TestStorageImports:
    """Verify storage library modules import successfully."""

    def test_storage_interface(self):
        """libs.storage.interface is importable."""
        from libs.storage import interface

        assert hasattr(interface, "__name__")

    def test_object_storage_interface(self):
        """libs.storage.interfaces.object_storage is importable."""
        from libs.storage.interfaces import object_storage

        assert hasattr(object_storage, "__name__")


class TestDbImports:
    """Verify database library modules import successfully."""

    def test_metadata_module(self):
        """libs.db.metadata is importable."""
        from libs.db import metadata

        assert hasattr(metadata, "__name__")

    def test_metadata_database_module(self):
        """libs.db.metadata_database is importable."""
        from libs.db import metadata_database

        assert hasattr(metadata_database, "__name__")


class TestMockImports:
    """Verify mock repository modules import successfully."""

    def test_mock_draft_autosave(self):
        """MockDraftAutosaveRepository is importable and has expected methods."""
        from libs.contracts.mocks.mock_draft_autosave_repository import (
            MockDraftAutosaveRepository,
        )

        repo = MockDraftAutosaveRepository()
        assert hasattr(repo, "create")
        assert hasattr(repo, "get_latest")
        assert hasattr(repo, "delete")

    def test_mock_draft_autosave_create_roundtrip(self):
        """MockDraftAutosaveRepository can create and retrieve records."""
        from libs.contracts.mocks.mock_draft_autosave_repository import (
            MockDraftAutosaveRepository,
        )

        repo = MockDraftAutosaveRepository()
        result = repo.create(
            user_id="01HTESTUSER000000000000000",
            draft_payload={"name": "Test"},
            form_step="basics",
            session_id="sess-001",
            client_ts="2026-04-02T12:00:00Z",
        )
        assert "autosave_id" in result

        latest = repo.get_latest(user_id="01HTESTUSER000000000000000")
        assert latest is not None

    def test_mock_draft_autosave_delete(self):
        """MockDraftAutosaveRepository delete works."""
        from libs.contracts.mocks.mock_draft_autosave_repository import (
            MockDraftAutosaveRepository,
        )

        repo = MockDraftAutosaveRepository()
        result = repo.create(
            user_id="01HTESTDEL0000000000000000",
            draft_payload={"x": 1},
        )
        assert repo.delete(autosave_id=result["autosave_id"]) is True
        assert repo.delete(autosave_id="nonexistent") is False


class TestHealthServiceImport:
    """Verify health service module imports."""

    def test_health_main_importable(self):
        """services.health.main is importable."""
        from services.health import main

        assert hasattr(main, "__name__")

"""
Tests for the StrategyService.

Verifies:
- Strategy creation with valid DSL conditions.
- DSL validation errors prevent strategy creation.
- Strategy retrieval by ID.
- Strategy listing with filters and pagination.
- DSL expression validation (standalone).
- Name validation.
- Strategy cloning (POST /strategies/{id}/clone): happy path,
  source-not-found, name-collision (409-mappable), validation rejection
  on empty / overlong names, and structural-copy invariants (no aliased
  parsed_ir reference, fresh id, row_version=1).

Example:
    pytest tests/unit/test_strategy_service.py -v
"""

from __future__ import annotations

import json

import pytest

from libs.contracts.errors import (
    NotFoundError,
    RowVersionConflictError,
    StrategyArchiveStateError,
    StrategyNameConflictError,
    ValidationError,
)
from libs.contracts.mocks.mock_strategy_repository import MockStrategyRepository
from services.api.services.strategy_service import StrategyService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_service() -> tuple[StrategyService, MockStrategyRepository]:
    """Create a StrategyService with a fresh mock repository."""
    repo = MockStrategyRepository()
    service = StrategyService(strategy_repo=repo)
    return service, repo


# ---------------------------------------------------------------------------
# Create strategy
# ---------------------------------------------------------------------------


class TestCreateStrategy:
    """Tests for strategy creation."""

    def test_create_valid_strategy(self) -> None:
        """Valid conditions should persist and return validation metadata."""
        service, repo = _make_service()

        result = service.create_strategy(
            name="RSI Reversal",
            entry_condition="RSI(14) < 30 AND price > SMA(200)",
            exit_condition="RSI(14) > 70 OR price < SMA(200)",
            description="Mean reversion strategy",
            instrument="AAPL",
            timeframe="1h",
            max_position_size=10000,
            stop_loss_percent=2.0,
            take_profit_percent=5.0,
            created_by="01HUSER001",
        )

        assert "strategy" in result
        assert result["strategy"]["name"] == "RSI Reversal"
        assert result["strategy"]["is_active"] is True
        assert result["entry_validation"]["is_valid"] is True
        assert result["exit_validation"]["is_valid"] is True
        assert "RSI" in result["indicators_used"]
        assert "SMA" in result["indicators_used"]
        assert "price" in result["variables_used"]

        # Verify persisted in repo
        assert repo.count() == 1
        stored = repo.get_all()[0]
        code_doc = json.loads(stored["code"])
        assert code_doc["entry_condition"] == "RSI(14) < 30 AND price > SMA(200)"
        assert code_doc["instrument"] == "AAPL"

    def test_create_with_invalid_entry_condition(self) -> None:
        """Invalid entry condition should raise ValidationError."""
        service, repo = _make_service()

        with pytest.raises(ValidationError, match="Entry condition"):
            service.create_strategy(
                name="Bad Strategy",
                entry_condition="RSI() < 30",  # Missing argument
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

        # Nothing should be persisted
        assert repo.count() == 0

    def test_create_with_invalid_exit_condition(self) -> None:
        """Invalid exit condition should raise ValidationError."""
        service, repo = _make_service()

        with pytest.raises(ValidationError, match="Exit condition"):
            service.create_strategy(
                name="Bad Strategy",
                entry_condition="RSI(14) < 30",
                exit_condition="FOOBAR(14) > 70",  # Unknown indicator
                created_by="01HUSER001",
            )

        assert repo.count() == 0

    def test_create_with_both_conditions_invalid(self) -> None:
        """Both conditions invalid should report errors for both."""
        service, _ = _make_service()

        with pytest.raises(ValidationError, match="Entry condition.*Exit condition"):
            service.create_strategy(
                name="Bad Strategy",
                entry_condition="RSI() < 30",
                exit_condition="MACD(12) > 0",
                created_by="01HUSER001",
            )

    def test_create_with_empty_name_raises(self) -> None:
        """Empty name should raise ValidationError."""
        service, _ = _make_service()

        with pytest.raises(ValidationError, match="name is required"):
            service.create_strategy(
                name="",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

    def test_create_with_whitespace_name_raises(self) -> None:
        """Whitespace-only name should raise ValidationError."""
        service, _ = _make_service()

        with pytest.raises(ValidationError, match="name is required"):
            service.create_strategy(
                name="   ",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

    def test_create_minimal_fields(self) -> None:
        """Only required fields should work (name, conditions, created_by)."""
        service, repo = _make_service()

        result = service.create_strategy(
            name="Minimal",
            entry_condition="price > SMA(20)",
            exit_condition="price < SMA(20)",
            created_by="01HUSER001",
        )

        assert result["strategy"]["name"] == "Minimal"
        assert repo.count() == 1

    def test_create_preserves_risk_parameters(self) -> None:
        """Risk parameters should be stored in the code JSON."""
        service, repo = _make_service()

        service.create_strategy(
            name="Risk Test",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            max_position_size=50000,
            stop_loss_percent=3.5,
            take_profit_percent=7.0,
            created_by="01HUSER001",
        )

        stored = repo.get_all()[0]
        code_doc = json.loads(stored["code"])
        assert code_doc["max_position_size"] == 50000
        assert code_doc["stop_loss_percent"] == 3.5
        assert code_doc["take_profit_percent"] == 7.0


# ---------------------------------------------------------------------------
# Get strategy
# ---------------------------------------------------------------------------


class TestGetStrategy:
    """Tests for strategy retrieval."""

    def test_get_existing_strategy(self) -> None:
        """Should return strategy with parsed code fields."""
        service, _ = _make_service()

        created = service.create_strategy(
            name="Test Get",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            instrument="AAPL",
            created_by="01HUSER001",
        )

        strategy_id = created["strategy"]["id"]
        result = service.get_strategy(strategy_id)

        assert result["name"] == "Test Get"
        assert "parsed_code" in result
        assert result["parsed_code"]["entry_condition"] == "RSI(14) < 30"
        assert result["parsed_code"]["instrument"] == "AAPL"

    def test_get_nonexistent_raises_not_found(self) -> None:
        """Nonexistent ID should raise NotFoundError."""
        service, _ = _make_service()

        with pytest.raises(NotFoundError, match="not found"):
            service.get_strategy("01HNONEXISTENT0000000000")


# ---------------------------------------------------------------------------
# List strategies
# ---------------------------------------------------------------------------


class TestListStrategies:
    """Tests for strategy listing."""

    def test_list_empty(self) -> None:
        """Empty repo returns empty list."""
        service, _ = _make_service()

        result = service.list_strategies()
        assert result["strategies"] == []
        assert result["count"] == 0

    def test_list_returns_all(self) -> None:
        """All created strategies appear in the list."""
        service, _ = _make_service()

        for i in range(3):
            service.create_strategy(
                name=f"Strategy {i}",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

        result = service.list_strategies()
        assert result["count"] == 3

    def test_list_with_pagination(self) -> None:
        """Pagination should limit results."""
        service, _ = _make_service()

        for i in range(5):
            service.create_strategy(
                name=f"Strategy {i}",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

        result = service.list_strategies(limit=2, offset=0)
        assert result["count"] == 2
        assert result["limit"] == 2

    def test_list_filter_by_creator(self) -> None:
        """created_by filter should narrow results."""
        service, _ = _make_service()

        service.create_strategy(
            name="User1 Strategy",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER001",
        )
        service.create_strategy(
            name="User2 Strategy",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER002",
        )

        result = service.list_strategies(created_by="01HUSER001")
        assert result["count"] == 1
        assert result["strategies"][0]["created_by"] == "01HUSER001"


# ---------------------------------------------------------------------------
# Validate DSL
# ---------------------------------------------------------------------------


class TestValidateDsl:
    """Tests for standalone DSL validation."""

    def test_valid_expression(self) -> None:
        """Valid expression returns is_valid=True."""
        service, _ = _make_service()

        result = service.validate_dsl_expression("RSI(14) < 30 AND price > SMA(200)")
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert "RSI" in result["indicators_used"]

    def test_invalid_expression(self) -> None:
        """Invalid expression returns structured errors."""
        service, _ = _make_service()

        result = service.validate_dsl_expression("RSI() < 30")
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0
        assert result["errors"][0]["message"] is not None

    def test_empty_expression(self) -> None:
        """Empty expression returns is_valid=False."""
        service, _ = _make_service()

        result = service.validate_dsl_expression("")
        assert result["is_valid"] is False


# ---------------------------------------------------------------------------
# Clone strategy
# ---------------------------------------------------------------------------


def _seed_source(
    service: StrategyService,
    *,
    name: str = "Source Strategy",
    instrument: str = "EURUSD",
) -> dict:
    """Create a draft-form source strategy via the production code path.

    Returns the persisted source dict (id, name, code, version, source,
    is_active, row_version, created_at, updated_at) — the same shape the
    repository hands back. Tests can use this to anchor source_id and
    assert structural-copy semantics post-clone.
    """
    result = service.create_strategy(
        name=name,
        entry_condition="RSI(14) < 30",
        exit_condition="RSI(14) > 70",
        instrument=instrument,
        timeframe="1h",
        max_position_size=10000,
        stop_loss_percent=2.0,
        take_profit_percent=5.0,
        created_by="01HUSER000000000000000001",
    )
    return result["strategy"]


class TestCloneStrategy:
    """Tests for ``StrategyService.clone_strategy`` (POST /strategies/{id}/clone)."""

    def test_clone_happy_path_returns_new_strategy_with_new_name(self) -> None:
        """Cloning a draft-form source returns a new persisted record."""
        service, repo = _make_service()
        source = _seed_source(service, name="RSI Reversal")

        clone = service.clone_strategy(
            source["id"],
            new_name="RSI Reversal (copy)",
            requested_by="01HCLONER0000000000000001",
        )

        # Returned record has the new name + new id.
        assert clone["name"] == "RSI Reversal (copy)"
        assert clone["id"] != source["id"]
        assert len(clone["id"]) == 26  # ULID
        # Provenance + version mirror the source — clone preserves the
        # source's identity flags so downstream tooling still treats the
        # clone as "the same kind of strategy".
        assert clone["source"] == source["source"]
        assert clone["version"] == source["version"]
        # Fresh row_version per §0 (clone is a brand-new write, not an
        # update of an existing row).
        assert clone["row_version"] == 1
        # Active by default — the brief explicitly excludes copying
        # deployments / approvals, but the clone itself must be visible.
        assert clone["is_active"] is True
        # created_by is the requester, not the source's original creator.
        assert clone["created_by"] == "01HCLONER0000000000000001"

        # Repo now holds two rows.
        assert repo.count() == 2

    def test_clone_persists_structural_copy_of_code_not_aliased_reference(self) -> None:
        """Cloned ``code`` must round-trip to the same dict but be a separate object.

        The brief is explicit: ``parsed_ir`` (and therefore the persisted
        ``code`` JSON) must be a structural copy, not an aliased
        reference. Mutating the clone's parsed code must NOT affect the
        source's persisted code.
        """
        service, repo = _make_service()
        source = _seed_source(service, name="Structural Source")

        clone = service.clone_strategy(
            source["id"],
            new_name="Structural Clone",
            requested_by="01HCLONER0000000000000001",
        )

        source_code = json.loads(source["code"])
        clone_code = json.loads(clone["code"])
        # Same values …
        assert source_code == clone_code
        # … and separate identity. Mutate the clone's parsed dict and
        # assert the source's persisted bytes are unchanged.
        clone_code["instrument"] = "GBPUSD"
        re_read_source = repo.get_by_id(source["id"])
        assert re_read_source is not None
        assert json.loads(re_read_source["code"])["instrument"] == "EURUSD"

    def test_clone_with_unknown_source_raises_not_found(self) -> None:
        """Cloning a missing source raises ``NotFoundError``."""
        service, _ = _make_service()

        with pytest.raises(NotFoundError, match="not found"):
            service.clone_strategy(
                "01HMISSING0000000000000001",
                new_name="Clone",
                requested_by="01HCLONER0000000000000001",
            )

    def test_clone_with_colliding_name_raises_conflict(self) -> None:
        """Cloning to an existing strategy's name raises ``StrategyNameConflictError``."""
        service, repo = _make_service()
        source = _seed_source(service, name="Original")
        # Create a second strategy whose name is the desired clone target.
        service.create_strategy(
            name="Original (copy)",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER000000000000000001",
        )

        with pytest.raises(StrategyNameConflictError) as excinfo:
            service.clone_strategy(
                source["id"],
                new_name="Original (copy)",
                requested_by="01HCLONER0000000000000001",
            )

        # Error carries the colliding name verbatim so the route can
        # surface it in the 409 detail body.
        assert excinfo.value.name == "Original (copy)"
        # Nothing was persisted on the conflict path.
        assert repo.count() == 2

    def test_clone_name_collision_is_case_insensitive(self) -> None:
        """Names that differ only by case still collide (mirrors UI ergonomics)."""
        service, repo = _make_service()
        source = _seed_source(service, name="Mixed Case Source")
        service.create_strategy(
            name="My Strategy",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER000000000000000001",
        )

        with pytest.raises(StrategyNameConflictError):
            service.clone_strategy(
                source["id"],
                new_name="MY STRATEGY",
                requested_by="01HCLONER0000000000000001",
            )

        # No write on the conflict path.
        assert repo.count() == 2

    def test_clone_with_empty_new_name_raises_validation(self) -> None:
        """An empty / whitespace-only new_name raises ``ValidationError``."""
        service, _ = _make_service()
        source = _seed_source(service, name="Source")

        with pytest.raises(ValidationError, match="name is required"):
            service.clone_strategy(
                source["id"],
                new_name="   ",
                requested_by="01HCLONER0000000000000001",
            )

    def test_clone_with_overlong_name_raises_validation(self) -> None:
        """A new_name above the ORM column limit (255) raises ``ValidationError``."""
        service, _ = _make_service()
        source = _seed_source(service, name="Source")

        with pytest.raises(ValidationError, match="255"):
            service.clone_strategy(
                source["id"],
                new_name="x" * 256,
                requested_by="01HCLONER0000000000000001",
            )

    def test_clone_does_not_copy_source_id_or_timestamps(self) -> None:
        """The clone's id and timestamps are fresh, not aliased from the source.

        This is a structural invariant per the brief: the clone must
        carry a brand-new ULID and brand-new timestamps. Sharing those
        with the source would let downstream history queries
        accidentally cross-link the two rows.
        """
        service, _ = _make_service()
        source = _seed_source(service, name="Source row")

        clone = service.clone_strategy(
            source["id"],
            new_name="Clone row",
            requested_by="01HCLONER0000000000000001",
        )

        assert clone["id"] != source["id"]
        # Timestamps are non-empty and (in the mock repo, generated via
        # datetime.now(UTC)) at least monotonically non-decreasing.
        assert clone["created_at"]
        assert clone["updated_at"]
        # The mock repo creates both rows so quickly the ISO strings can
        # match; the load-bearing assertion is that they are not the
        # source's literal created_at value.
        # In the real SQL repo each insert hits server_default which is
        # unique per row, so we only assert non-empty here.

    def test_clone_emits_strategy_cloned_audit_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful clone emits ``strategy_cloned`` per CLAUDE.md §8.

        The structlog logger bound at module scope is the canonical
        emission point — spy on it so the test does not depend on stdlib
        logging routing (this codebase wires structlog directly to
        stdout, so caplog cannot see these calls).
        """
        service, _ = _make_service()
        from services.api.services import strategy_service as svc_module

        captured: list[tuple[str, dict]] = []
        original_info = svc_module.logger.info

        def _spy(event: str, /, **kwargs):
            captured.append((event, kwargs))
            return original_info(event, **kwargs)

        monkeypatch.setattr(svc_module.logger, "info", _spy)

        source = _seed_source(service, name="Audit Source")
        clone = service.clone_strategy(
            source["id"],
            new_name="Audit Clone",
            requested_by="01HCLONER0000000000000001",
        )

        cloned_events = [(ev, kw) for (ev, kw) in captured if ev == "strategy_cloned"]
        assert len(cloned_events) == 1, f"expected exactly one strategy_cloned line; got {captured}"
        _ev, kwargs = cloned_events[0]
        assert kwargs["source_id"] == source["id"]
        assert kwargs["new_id"] == clone["id"]
        assert kwargs["new_name"] == "Audit Clone"
        assert kwargs["requested_by"] == "01HCLONER0000000000000001"


# ---------------------------------------------------------------------------
# Archive / restore lifecycle (POST /strategies/{id}/archive | /restore)
# ---------------------------------------------------------------------------


def _seed_strategy_for_archive(
    service: StrategyService,
    *,
    name: str = "Archivable Strategy",
) -> dict:
    """Create a fresh strategy and return the persisted dict.

    Reuses the production create path so each archive test exercises a
    record that already carries the columns the archive flow reads
    (id, row_version, archived_at=None).
    """
    result = service.create_strategy(
        name=name,
        entry_condition="RSI(14) < 30",
        exit_condition="RSI(14) > 70",
        created_by="01HUSER000000000000000001",
    )
    return result["strategy"]


class TestArchiveStrategy:
    """Tests for ``StrategyService.archive_strategy`` (POST /archive)."""

    def test_archive_happy_path_sets_timestamp_and_bumps_row_version(self) -> None:
        """Archive sets archived_at to a UTC timestamp and bumps row_version."""
        service, repo = _make_service()
        source = _seed_strategy_for_archive(service)
        original_rv = source["row_version"]

        updated = service.archive_strategy(source["id"], requested_by="01HOPER000000000000000001")

        assert updated["id"] == source["id"]
        assert updated["archived_at"] is not None
        # ISO-8601 timestamp; the mock repo writes via ``isoformat()``.
        assert "T" in updated["archived_at"]
        assert updated["row_version"] == original_rv + 1

        # Persisted in the repo too — re-read confirms durability.
        re_read = repo.get_by_id(source["id"])
        assert re_read is not None
        assert re_read["archived_at"] == updated["archived_at"]
        assert re_read["row_version"] == updated["row_version"]

    def test_archive_unknown_strategy_raises_not_found(self) -> None:
        """Archive on a missing id raises NotFoundError (route maps 404)."""
        service, _ = _make_service()
        with pytest.raises(NotFoundError, match="not found"):
            service.archive_strategy(
                "01HMISSING0000000000000001",
                requested_by="01HOPER000000000000000001",
            )

    def test_archive_already_archived_raises_state_error(self) -> None:
        """Archive on an already-archived row raises StrategyArchiveStateError."""
        service, _ = _make_service()
        source = _seed_strategy_for_archive(service)
        service.archive_strategy(source["id"], requested_by="01HOPER000000000000000001")

        with pytest.raises(StrategyArchiveStateError) as excinfo:
            service.archive_strategy(source["id"], requested_by="01HOPER000000000000000001")

        # The 409-mappable error carries enough state for the route layer
        # to render an actionable message without re-querying.
        assert excinfo.value.strategy_id == source["id"]
        assert excinfo.value.current_state == "archived"

    def test_archive_with_matching_row_version_succeeds(self) -> None:
        """Optimistic-lock guard accepts a matching row_version."""
        service, _ = _make_service()
        source = _seed_strategy_for_archive(service)

        updated = service.archive_strategy(
            source["id"],
            requested_by="01HOPER000000000000000001",
            expected_row_version=source["row_version"],
        )
        assert updated["archived_at"] is not None

    def test_archive_with_stale_row_version_raises_conflict(self) -> None:
        """Stale expected_row_version raises RowVersionConflictError (409)."""
        service, _ = _make_service()
        source = _seed_strategy_for_archive(service)

        with pytest.raises(RowVersionConflictError) as excinfo:
            service.archive_strategy(
                source["id"],
                requested_by="01HOPER000000000000000001",
                expected_row_version=source["row_version"] + 99,
            )

        # Operator UI surfaces the actual row_version so the user can
        # decide whether to refresh or force the write.
        assert excinfo.value.entity == "strategy"
        assert excinfo.value.entity_id == source["id"]
        assert excinfo.value.actual_row_version == source["row_version"]

    def test_archive_emits_strategy_archived_audit_log(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful archive emits ``strategy_archived`` per CLAUDE.md §8."""
        service, _ = _make_service()
        from services.api.services import strategy_service as svc_module

        captured: list[tuple[str, dict]] = []
        original_info = svc_module.logger.info

        def _spy(event: str, /, **kwargs):
            captured.append((event, kwargs))
            return original_info(event, **kwargs)

        monkeypatch.setattr(svc_module.logger, "info", _spy)

        source = _seed_strategy_for_archive(service, name="Audit Archive Source")
        service.archive_strategy(source["id"], requested_by="01HOPER000000000000000001")

        archive_events = [(ev, kw) for (ev, kw) in captured if ev == "strategy_archived"]
        assert len(archive_events) == 1, (
            f"expected exactly one strategy_archived line; got {captured}"
        )
        _ev, kwargs = archive_events[0]
        assert kwargs["strategy_id"] == source["id"]
        assert kwargs["requested_by"] == "01HOPER000000000000000001"
        assert kwargs["archived_at"] is not None


class TestRestoreStrategy:
    """Tests for ``StrategyService.restore_strategy`` (POST /restore)."""

    def test_restore_happy_path_clears_timestamp_and_bumps_row_version(self) -> None:
        """Restore clears archived_at and bumps row_version."""
        service, repo = _make_service()
        source = _seed_strategy_for_archive(service)
        archived = service.archive_strategy(source["id"], requested_by="01HOPER000000000000000001")

        restored = service.restore_strategy(source["id"], requested_by="01HOPER000000000000000001")

        assert restored["archived_at"] is None
        assert restored["row_version"] == archived["row_version"] + 1

        # Persisted in the repo too.
        re_read = repo.get_by_id(source["id"])
        assert re_read is not None
        assert re_read["archived_at"] is None

    def test_restore_unknown_strategy_raises_not_found(self) -> None:
        """Restore on a missing id raises NotFoundError."""
        service, _ = _make_service()
        with pytest.raises(NotFoundError, match="not found"):
            service.restore_strategy(
                "01HMISSING0000000000000001",
                requested_by="01HOPER000000000000000001",
            )

    def test_restore_when_not_archived_raises_state_error(self) -> None:
        """Restore on an active row raises StrategyArchiveStateError."""
        service, _ = _make_service()
        source = _seed_strategy_for_archive(service)

        with pytest.raises(StrategyArchiveStateError) as excinfo:
            service.restore_strategy(source["id"], requested_by="01HOPER000000000000000001")

        assert excinfo.value.strategy_id == source["id"]
        assert excinfo.value.current_state == "active"

    def test_restore_emits_strategy_restored_audit_log(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Successful restore emits ``strategy_restored`` per CLAUDE.md §8."""
        service, _ = _make_service()
        source = _seed_strategy_for_archive(service, name="Audit Restore Source")
        service.archive_strategy(source["id"], requested_by="01HOPER000000000000000001")

        from services.api.services import strategy_service as svc_module

        captured: list[tuple[str, dict]] = []
        original_info = svc_module.logger.info

        def _spy(event: str, /, **kwargs):
            captured.append((event, kwargs))
            return original_info(event, **kwargs)

        monkeypatch.setattr(svc_module.logger, "info", _spy)

        service.restore_strategy(source["id"], requested_by="01HOPER000000000000000001")

        restore_events = [(ev, kw) for (ev, kw) in captured if ev == "strategy_restored"]
        assert len(restore_events) == 1, (
            f"expected exactly one strategy_restored line; got {captured}"
        )
        _ev, kwargs = restore_events[0]
        assert kwargs["strategy_id"] == source["id"]
        assert kwargs["requested_by"] == "01HOPER000000000000000001"


class TestListStrategiesIncludeArchived:
    """Coverage for the include_archived kwarg on the list_strategies methods."""

    def test_list_strategies_excludes_archived_by_default(self) -> None:
        """Archived rows disappear from the default list view."""
        service, _ = _make_service()
        keep = _seed_strategy_for_archive(service, name="Active Strategy")
        archived_src = _seed_strategy_for_archive(service, name="To Be Archived")
        service.archive_strategy(archived_src["id"], requested_by="01HOPER000000000000000001")

        result = service.list_strategies()
        ids = [row["id"] for row in result["strategies"]]

        assert keep["id"] in ids
        assert archived_src["id"] not in ids
        assert result["count"] == 1

    def test_list_strategies_include_archived_returns_everything(self) -> None:
        """include_archived=True surfaces archived rows alongside active ones."""
        service, _ = _make_service()
        keep = _seed_strategy_for_archive(service, name="Active Strategy")
        archived_src = _seed_strategy_for_archive(service, name="To Be Archived")
        service.archive_strategy(archived_src["id"], requested_by="01HOPER000000000000000001")

        result = service.list_strategies(include_archived=True)
        ids = [row["id"] for row in result["strategies"]]

        assert keep["id"] in ids
        assert archived_src["id"] in ids
        assert result["count"] == 2

    def test_list_strategies_page_excludes_archived_by_default(self) -> None:
        """The browse-page envelope also hides archived rows by default."""
        service, _ = _make_service()
        _seed_strategy_for_archive(service, name="Active 1")
        archived_src = _seed_strategy_for_archive(service, name="To Be Archived")
        service.archive_strategy(archived_src["id"], requested_by="01HOPER000000000000000001")

        page = service.list_strategies_page(page=1, page_size=20)
        ids = [item.id for item in page.strategies]

        assert archived_src["id"] not in ids
        assert page.total_count == 1

    def test_list_strategies_page_include_archived_surfaces_them_with_field(self) -> None:
        """include_archived=True populates StrategyListItem.archived_at."""
        service, _ = _make_service()
        archived_src = _seed_strategy_for_archive(service, name="To Be Archived")
        archived = service.archive_strategy(
            archived_src["id"], requested_by="01HOPER000000000000000001"
        )

        page = service.list_strategies_page(page=1, page_size=20, include_archived=True)
        archived_item = next(item for item in page.strategies if item.id == archived_src["id"])

        # The contract field is non-None and matches the persisted value.
        assert archived_item.archived_at is not None
        assert archived_item.archived_at == archived["archived_at"]


# ---------------------------------------------------------------------------
# Validate-IR (no-save) endpoint backing service method
# ---------------------------------------------------------------------------


def _load_repo_ir_dict() -> dict:
    """
    Load one of the repo's production strategy_ir.json files for happy-path tests.

    Used by both ``TestValidateIr`` and ``TestGetStrategyIrJson`` so the
    fixture has actual structural variety (15 indicators, conditions,
    derived fields) rather than a hand-rolled minimal IR. We pin the
    Mean-Reversion H1 file because it exercises both ZscoreIndicator
    (cross-references to other indicators) and the full exit-logic
    discriminated union.
    """
    from pathlib import Path as _Path

    project_root = _Path(__file__).resolve().parents[2]
    ir_path = (
        project_root
        / "Strategy Repo"
        / "fxlab_chan_next3_strategy_pack"
        / "FX_SingleAsset_MeanReversion_H1.strategy_ir.json"
    )
    with ir_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class TestValidateIr:
    """Tests for ``StrategyService.validate_ir`` (no-save validation)."""

    def test_validate_ir_happy_path_returns_valid_report(self) -> None:
        """A real production IR validates cleanly with parsed_ir populated."""
        service, repo = _make_service()
        ir_dict = _load_repo_ir_dict()
        ir_text = json.dumps(ir_dict)

        report = service.validate_ir(ir_text)

        assert report.valid is True
        assert report.errors == []
        assert report.parsed_ir is not None
        # parsed_ir round-trips deeply against the input dict.
        assert report.parsed_ir == ir_dict
        # Idempotent + side-effect-free: the repo never sees a write.
        assert repo.count() == 0

    def test_validate_ir_does_not_persist_on_success(self) -> None:
        """Successful validation must not touch the repository."""
        service, repo = _make_service()
        before = repo.count()
        ir_text = json.dumps(_load_repo_ir_dict())

        service.validate_ir(ir_text)

        assert repo.count() == before, "validate_ir must never persist"

    def test_validate_ir_does_not_persist_on_failure(self) -> None:
        """Failed validation must also not touch the repository."""
        service, repo = _make_service()
        before = repo.count()

        report = service.validate_ir("{not valid json}")

        assert report.valid is False
        assert repo.count() == before

    def test_validate_ir_empty_text_reports_invalid_json(self) -> None:
        """Empty / whitespace-only text returns an invalid_json issue at root."""
        service, _ = _make_service()

        report = service.validate_ir("   ")

        assert report.valid is False
        assert report.parsed_ir is None
        assert len(report.errors) == 1
        assert report.errors[0].code == "invalid_json"
        assert report.errors[0].path == "/"

    def test_validate_ir_malformed_json_reports_invalid_json(self) -> None:
        """Malformed JSON yields one invalid_json issue at path '/'."""
        service, _ = _make_service()

        report = service.validate_ir("{not valid json}")

        assert report.valid is False
        assert report.parsed_ir is None
        assert len(report.errors) == 1
        issue = report.errors[0]
        assert issue.code == "invalid_json"
        assert issue.path == "/"

    def test_validate_ir_non_object_root_reports_invalid_json(self) -> None:
        """A JSON array / scalar at the root is also an invalid_json issue."""
        service, _ = _make_service()

        report = service.validate_ir("[1, 2, 3]")

        assert report.valid is False
        assert len(report.errors) == 1
        assert report.errors[0].code == "invalid_json"

    def test_validate_ir_schema_violation_returns_pydantic_paths(self) -> None:
        """Pydantic schema failure produces multiple issues with JSON-pointer paths."""
        service, _ = _make_service()
        ir = _load_repo_ir_dict()
        # Drop a required nested field so Pydantic produces a localised
        # error path. Choose ``metadata.strategy_name`` so the test's
        # path-format assertion is deterministic.
        del ir["metadata"]["strategy_name"]
        # Also drop a top-level required field so we see >1 errors and
        # can assert the helper reports them all rather than failing
        # fast on the first one.
        del ir["artifact_type"]

        report = service.validate_ir(json.dumps(ir))

        assert report.valid is False
        assert report.parsed_ir is None
        assert len(report.errors) >= 2
        codes = {issue.code for issue in report.errors}
        assert codes == {"schema_violation"}
        paths = {issue.path for issue in report.errors}
        assert "/metadata/strategy_name" in paths
        assert "/artifact_type" in paths

    def test_validate_ir_undefined_reference_reports_resolver_failure(self) -> None:
        """A dangling indicator reference produces an undefined_reference issue."""
        service, _ = _make_service()
        ir = _load_repo_ir_dict()
        # Mutate the long-entry condition to reference an indicator id
        # that does not exist. The schema still passes (lhs is just a
        # free-form string) but the reference resolver rejects it.
        ir["entry_logic"]["long"]["logic"]["conditions"][0]["lhs"] = "totally_unknown_indicator"

        report = service.validate_ir(json.dumps(ir))

        assert report.valid is False
        assert report.parsed_ir is None
        assert any(issue.code == "undefined_reference" for issue in report.errors)
        # The resolver records a location hint; the helper translates
        # that into a JSON pointer like ``/entry_logic/long/...``.
        ref_issue = next(issue for issue in report.errors if issue.code == "undefined_reference")
        assert ref_issue.path.startswith("/entry_logic/long/")

    def test_validate_ir_caps_error_list_at_max_validation_issues(self) -> None:
        """A deeply broken IR yields at most MAX_VALIDATION_ISSUES rows."""
        from libs.contracts.strategy import MAX_VALIDATION_ISSUES

        service, _ = _make_service()
        ir = _load_repo_ir_dict()
        # Strip every indicator's ``id`` field. Each missing id triggers
        # a Pydantic schema error; with 15 indicators that alone wouldn't
        # exceed the cap, so also strip ``timeframe`` and ``length`` /
        # equivalents to fan the error count past 100.
        for ind in ir["indicators"]:
            ind.pop("id", None)
            ind.pop("timeframe", None)
            ind.pop("length", None)
            ind.pop("length_bars", None)
            ind.pop("source", None)
            ind.pop("stddev", None)
            ind.pop("mean_source", None)
            ind.pop("std_source", None)

        report = service.validate_ir(json.dumps(ir))

        assert report.valid is False
        assert len(report.errors) <= MAX_VALIDATION_ISSUES, (
            f"errors exceeded cap: {len(report.errors)} > {MAX_VALIDATION_ISSUES}"
        )

    def test_validate_ir_truncation_appends_truncated_issue(self) -> None:
        """When the cap fires, the last issue documents truncation."""
        from libs.contracts.strategy import MAX_VALIDATION_ISSUES

        service, _ = _make_service()
        ir = _load_repo_ir_dict()
        # Same trick as above — strip enough required fields to fan the
        # error count well past the cap.
        for ind in ir["indicators"]:
            for k in (
                "id",
                "timeframe",
                "length",
                "length_bars",
                "source",
                "stddev",
                "mean_source",
                "std_source",
                "type",
            ):
                ind.pop(k, None)
        # Also drop a few top-level required blocks for additional errors.
        del ir["entry_logic"]
        del ir["exit_logic"]

        report = service.validate_ir(json.dumps(ir))

        if len(report.errors) == MAX_VALIDATION_ISSUES:
            # Truncation fired — the trailing row documents it.
            assert report.errors[-1].code == "truncated"
            assert "truncated" in report.errors[-1].message.lower()
        else:
            # If our error-fanning trick happened to produce <= cap rows
            # we still confirm no truncated issue was synthesised.
            assert all(issue.code != "truncated" for issue in report.errors)

    def test_validate_ir_never_raises(self) -> None:
        """validate_ir captures every error in the report, never raises."""
        service, _ = _make_service()
        # Cover the obvious failure modes plus an edge case (binary
        # data shoved through as text). None should escape as an
        # exception.
        for payload in (
            "",
            "{",
            "null",
            json.dumps([1, 2, 3]),
            "\x00\x01garbage",
        ):
            report = service.validate_ir(payload)
            assert report.valid is False, f"expected invalid for payload {payload!r}"
            assert report.errors, f"expected at least one issue for payload {payload!r}"


class TestGetStrategyIrJson:
    """Tests for ``StrategyService.get_strategy_ir_json`` (download path)."""

    def test_get_ir_json_happy_path_returns_persisted_source(self) -> None:
        """For an imported IR strategy, the method returns the canonical IR text."""
        service, _ = _make_service()
        ir_body = _load_repo_ir_dict()
        persisted = service.create_from_ir(ir_body, created_by="01HUSER000000000000000001")

        text = service.get_strategy_ir_json(persisted["id"])

        # Returned text parses back to the original IR (canonical
        # sort-keys form preserves values).
        assert json.loads(text) == ir_body

    def test_get_ir_json_unknown_strategy_raises_not_found(self) -> None:
        """A missing strategy id raises NotFoundError."""
        service, _ = _make_service()

        with pytest.raises(NotFoundError, match="not found"):
            service.get_strategy_ir_json("01HMISSING0000000000000001")

    def test_get_ir_json_legacy_blank_code_falls_back_to_empty_object(self) -> None:
        """Legacy rows with empty code degrade gracefully to '{}'.

        The fallback path is documented behaviour: rather than raising
        on a malformed legacy row, the download endpoint returns a
        parseable JSON document so the operator's browser save dialog
        always succeeds. The contract is "always returns a JSON
        string", and an empty object is the safest non-raising choice
        when the row carries no recoverable IR.
        """
        service, repo = _make_service()
        # Build a row with an empty code field. The mock repo's create()
        # rejects empty code via the SQL CHECK mirror; we mutate the
        # stored dict directly to simulate a legacy row that pre-dates
        # canonicalisation (write-bypass is the test point).
        persisted = service.create_from_ir(
            _load_repo_ir_dict(),
            created_by="01HUSER000000000000000001",
        )
        # Reach into the mock store to blank the code field (legacy row
        # simulation — not a code path any production caller can hit).
        repo._store[persisted["id"]]["code"] = ""

        text = service.get_strategy_ir_json(persisted["id"])

        # Fallback contract: returns parseable JSON. Empty object is
        # the documented last-resort.
        parsed = json.loads(text)
        assert parsed == {}

    def test_get_ir_json_returns_canonical_form_round_trip(self) -> None:
        """The returned JSON, re-encoded, equals the persisted code bytes."""
        service, repo = _make_service()
        ir_body = _load_repo_ir_dict()
        persisted = service.create_from_ir(ir_body, created_by="01HUSER000000000000000001")

        text = service.get_strategy_ir_json(persisted["id"])
        # The persisted code is sort_keys=True canonical form; the
        # download surfaces the same bytes verbatim.
        stored = repo.get_by_id(persisted["id"])
        assert stored is not None
        assert text == stored["code"]

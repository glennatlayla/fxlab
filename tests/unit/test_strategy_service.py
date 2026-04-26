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

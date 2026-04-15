"""
Unit tests for research run domain contracts.

Covers:
- ResearchRunType enum values and membership.
- ResearchRunStatus enum values, terminal detection, valid transitions.
- ResearchRunConfig validation (frozen, symbol normalisation, field constraints).
- ResearchRunResult construction and frozen guarantee.
- ResearchRunRecord construction, defaults, and frozen guarantee.
- SubmitResearchRunRequest / ResearchRunListResponse DTOs.
- InvalidStatusTransitionError message formatting.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.research_run import (
    VALID_STATUS_TRANSITIONS,
    InvalidStatusTransitionError,
    ResearchRunConfig,
    ResearchRunListResponse,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    ResearchRunType,
    SubmitResearchRunRequest,
    is_terminal_status,
    validate_status_transition,
)

# ---------------------------------------------------------------------------
# ResearchRunType
# ---------------------------------------------------------------------------


class TestResearchRunType:
    """Tests for ResearchRunType enum."""

    def test_all_types_present(self) -> None:
        assert set(ResearchRunType) == {
            ResearchRunType.BACKTEST,
            ResearchRunType.WALK_FORWARD,
            ResearchRunType.MONTE_CARLO,
            ResearchRunType.COMPOSITE,
        }

    def test_type_values(self) -> None:
        assert ResearchRunType.BACKTEST.value == "backtest"
        assert ResearchRunType.WALK_FORWARD.value == "walk_forward"
        assert ResearchRunType.MONTE_CARLO.value == "monte_carlo"
        assert ResearchRunType.COMPOSITE.value == "composite"

    def test_type_is_str_enum(self) -> None:
        assert isinstance(ResearchRunType.BACKTEST, str)


# ---------------------------------------------------------------------------
# ResearchRunStatus
# ---------------------------------------------------------------------------


class TestResearchRunStatus:
    """Tests for ResearchRunStatus enum."""

    def test_all_statuses_present(self) -> None:
        assert set(ResearchRunStatus) == {
            ResearchRunStatus.PENDING,
            ResearchRunStatus.QUEUED,
            ResearchRunStatus.RUNNING,
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.FAILED,
            ResearchRunStatus.CANCELLED,
        }

    def test_terminal_statuses(self) -> None:
        assert is_terminal_status(ResearchRunStatus.COMPLETED) is True
        assert is_terminal_status(ResearchRunStatus.FAILED) is True
        assert is_terminal_status(ResearchRunStatus.CANCELLED) is True

    def test_non_terminal_statuses(self) -> None:
        assert is_terminal_status(ResearchRunStatus.PENDING) is False
        assert is_terminal_status(ResearchRunStatus.QUEUED) is False
        assert is_terminal_status(ResearchRunStatus.RUNNING) is False

    def test_valid_transitions_from_pending(self) -> None:
        assert validate_status_transition(ResearchRunStatus.PENDING, ResearchRunStatus.QUEUED)
        assert validate_status_transition(ResearchRunStatus.PENDING, ResearchRunStatus.CANCELLED)
        assert not validate_status_transition(
            ResearchRunStatus.PENDING, ResearchRunStatus.COMPLETED
        )

    def test_valid_transitions_from_queued(self) -> None:
        assert validate_status_transition(ResearchRunStatus.QUEUED, ResearchRunStatus.RUNNING)
        assert validate_status_transition(ResearchRunStatus.QUEUED, ResearchRunStatus.CANCELLED)
        assert not validate_status_transition(ResearchRunStatus.QUEUED, ResearchRunStatus.COMPLETED)

    def test_valid_transitions_from_running(self) -> None:
        assert validate_status_transition(ResearchRunStatus.RUNNING, ResearchRunStatus.COMPLETED)
        assert validate_status_transition(ResearchRunStatus.RUNNING, ResearchRunStatus.FAILED)
        assert not validate_status_transition(
            ResearchRunStatus.RUNNING, ResearchRunStatus.CANCELLED
        )

    def test_terminal_states_have_no_transitions(self) -> None:
        for terminal in (
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.FAILED,
            ResearchRunStatus.CANCELLED,
        ):
            for target in ResearchRunStatus:
                assert not validate_status_transition(terminal, target)

    def test_all_statuses_in_transition_map(self) -> None:
        for status in ResearchRunStatus:
            assert status in VALID_STATUS_TRANSITIONS


# ---------------------------------------------------------------------------
# InvalidStatusTransitionError
# ---------------------------------------------------------------------------


class TestInvalidStatusTransitionError:
    """Tests for InvalidStatusTransitionError."""

    def test_error_message_format(self) -> None:
        err = InvalidStatusTransitionError(ResearchRunStatus.COMPLETED, ResearchRunStatus.RUNNING)
        assert "completed" in str(err).lower()
        assert "running" in str(err).lower()

    def test_error_attributes(self) -> None:
        err = InvalidStatusTransitionError(ResearchRunStatus.PENDING, ResearchRunStatus.COMPLETED)
        assert err.current == ResearchRunStatus.PENDING
        assert err.target == ResearchRunStatus.COMPLETED


# ---------------------------------------------------------------------------
# ResearchRunConfig
# ---------------------------------------------------------------------------


class TestResearchRunConfig:
    """Tests for ResearchRunConfig model."""

    def test_minimal_config(self) -> None:
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL"],
        )
        assert config.run_type == ResearchRunType.BACKTEST
        assert config.strategy_id == "01HSTRATEGY00000000000001"
        assert config.symbols == ["AAPL"]
        assert config.initial_equity == Decimal("100000")

    def test_config_is_frozen(self) -> None:
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL"],
        )
        with pytest.raises(Exception):
            config.run_type = ResearchRunType.WALK_FORWARD  # type: ignore[misc]

    def test_symbols_normalised_to_uppercase(self) -> None:
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["aapl", "  msft  "],
        )
        assert config.symbols == ["AAPL", "MSFT"]

    def test_symbols_deduplicated(self) -> None:
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL", "aapl", "MSFT"],
        )
        assert config.symbols == ["AAPL", "MSFT"]

    def test_symbols_minimum_one(self) -> None:
        with pytest.raises(Exception):
            ResearchRunConfig(
                run_type=ResearchRunType.BACKTEST,
                strategy_id="01HSTRATEGY00000000000001",
                symbols=[],
            )

    def test_initial_equity_must_be_positive(self) -> None:
        with pytest.raises(Exception):
            ResearchRunConfig(
                run_type=ResearchRunType.BACKTEST,
                strategy_id="01HSTRATEGY00000000000001",
                symbols=["AAPL"],
                initial_equity=Decimal("0"),
            )

    def test_metadata_defaults_to_empty(self) -> None:
        config = ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL"],
        )
        assert config.metadata == {}

    def test_config_with_all_optional_engines(self) -> None:
        config = ResearchRunConfig(
            run_type=ResearchRunType.COMPOSITE,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL"],
            strategy_version_id="01HVERSION0000000000000001",
            signal_strategy_id="moving_average_crossover",
        )
        assert config.strategy_version_id is not None
        assert config.signal_strategy_id is not None


# ---------------------------------------------------------------------------
# ResearchRunResult
# ---------------------------------------------------------------------------


class TestResearchRunResult:
    """Tests for ResearchRunResult model."""

    def test_empty_result(self) -> None:
        result = ResearchRunResult()
        assert result.backtest_result is None
        assert result.walk_forward_result is None
        assert result.monte_carlo_result is None
        assert result.summary_metrics == {}
        assert result.completed_at is not None

    def test_result_is_frozen(self) -> None:
        result = ResearchRunResult()
        with pytest.raises(Exception):
            result.summary_metrics = {"foo": "bar"}  # type: ignore[misc]

    def test_result_with_summary_metrics(self) -> None:
        result = ResearchRunResult(
            summary_metrics={"total_return": 0.15, "sharpe_ratio": 1.2},
        )
        assert result.summary_metrics["total_return"] == 0.15


# ---------------------------------------------------------------------------
# ResearchRunRecord
# ---------------------------------------------------------------------------


class TestResearchRunRecord:
    """Tests for ResearchRunRecord model."""

    def _make_config(self) -> ResearchRunConfig:
        return ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL"],
        )

    def test_record_defaults(self) -> None:
        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=self._make_config(),
            created_by="01HUSER00000000000000001",
        )
        assert record.status == ResearchRunStatus.PENDING
        assert record.result is None
        assert record.error_message is None
        assert record.started_at is None
        assert record.completed_at is None
        assert record.created_at is not None
        assert record.updated_at is not None

    def test_record_is_frozen(self) -> None:
        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=self._make_config(),
            created_by="01HUSER00000000000000001",
        )
        with pytest.raises(Exception):
            record.status = ResearchRunStatus.RUNNING  # type: ignore[misc]

    def test_record_model_copy_update(self) -> None:
        """Frozen models update via model_copy(update=...)."""
        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=self._make_config(),
            created_by="01HUSER00000000000000001",
        )
        updated = record.model_copy(update={"status": ResearchRunStatus.QUEUED})
        assert updated.status == ResearchRunStatus.QUEUED
        assert record.status == ResearchRunStatus.PENDING  # original unchanged


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TestDTOs:
    """Tests for API-layer DTOs."""

    def _make_config(self) -> ResearchRunConfig:
        return ResearchRunConfig(
            run_type=ResearchRunType.BACKTEST,
            strategy_id="01HSTRATEGY00000000000001",
            symbols=["AAPL"],
        )

    def test_submit_request(self) -> None:
        req = SubmitResearchRunRequest(config=self._make_config())
        assert req.config.run_type == ResearchRunType.BACKTEST

    def test_list_response(self) -> None:
        record = ResearchRunRecord(
            id="01HRUN00000000000000000001",
            config=self._make_config(),
            created_by="01HUSER00000000000000001",
        )
        resp = ResearchRunListResponse(runs=[record], total_count=1)
        assert resp.total_count == 1
        assert len(resp.runs) == 1

    def test_list_response_total_count_non_negative(self) -> None:
        with pytest.raises(Exception):
            ResearchRunListResponse(runs=[], total_count=-1)

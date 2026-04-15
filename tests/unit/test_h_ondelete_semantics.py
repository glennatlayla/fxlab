"""
ON DELETE semantics validation tests.

Every ForeignKey in the ORM must specify an explicit ``ondelete`` action
(CASCADE or RESTRICT) so the database enforces referential integrity
deterministically, rather than relying on database-engine defaults.

Dependencies:
    - libs.contracts.models

Example:
    pytest tests/unit/test_h_ondelete_semantics.py -v
"""

from __future__ import annotations


def _get_fk_ondelete_map(model_class: type) -> dict[str, str | None]:
    """
    Extract a mapping of column_name → ondelete action for every FK column.

    Args:
        model_class: A SQLAlchemy ORM model class.

    Returns:
        Dict mapping column names that have ForeignKeys to their ondelete
        value (e.g. "CASCADE", "RESTRICT", or None if unspecified).
    """
    result: dict[str, str | None] = {}
    for col in model_class.__table__.columns:
        for fk in col.foreign_keys:
            result[col.name] = fk.ondelete
    return result


def _assert_ondelete(model_class: type, column_name: str, expected: str) -> None:
    """
    Assert that a FK column has the expected ondelete action.

    Args:
        model_class: A SQLAlchemy ORM model class.
        column_name: Name of the FK column.
        expected: Expected ondelete value (e.g. "CASCADE" or "RESTRICT").

    Raises:
        AssertionError: If the ondelete value does not match.
    """
    fk_map = _get_fk_ondelete_map(model_class)
    assert column_name in fk_map, (
        f"{model_class.__name__} has no FK column '{column_name}'. "
        f"FK columns: {list(fk_map.keys())}"
    )
    actual = fk_map[column_name]
    assert actual is not None, (
        f"{model_class.__name__}.{column_name} FK has no ondelete specified (expected '{expected}')"
    )
    assert actual.upper() == expected.upper(), (
        f"{model_class.__name__}.{column_name} FK ondelete is '{actual}', expected '{expected}'"
    )


# ---------------------------------------------------------------------------
# Test: every FK column specifies ondelete
# ---------------------------------------------------------------------------


class TestAllForeignKeysHaveOnDelete:
    """Every ForeignKey column must specify ondelete explicitly."""

    def test_no_fk_without_ondelete(self) -> None:
        """Scan all models for FK columns missing ondelete."""
        from libs.contracts.models import Base

        missing: list[str] = []
        for mapper in Base.registry.mappers:
            model = mapper.class_
            table = model.__table__
            for col in table.columns:
                for fk in col.foreign_keys:
                    if fk.ondelete is None:
                        missing.append(f"{table.name}.{col.name}")

        assert not missing, f"{len(missing)} FK column(s) lack explicit ondelete: {missing}"


# ---------------------------------------------------------------------------
# Test: CASCADE semantics (child wholly owned by parent)
# ---------------------------------------------------------------------------


class TestCascadeForeignKeys:
    """FK columns where CASCADE is the correct semantic."""

    def test_strategy_build_strategy_id(self) -> None:
        """Builds belong to a strategy — CASCADE on delete."""
        from libs.contracts.models import StrategyBuild

        _assert_ondelete(StrategyBuild, "strategy_id", "CASCADE")

    def test_trial_run_id(self) -> None:
        """Trials belong to a run — CASCADE on delete."""
        from libs.contracts.models import Trial

        _assert_ondelete(Trial, "run_id", "CASCADE")

    def test_artifact_run_id(self) -> None:
        """Artifacts belong to a run — CASCADE on delete."""
        from libs.contracts.models import Artifact

        _assert_ondelete(Artifact, "run_id", "CASCADE")

    def test_feed_health_event_feed_id(self) -> None:
        """Feed health events belong to a feed — CASCADE on delete."""
        from libs.contracts.models import FeedHealthEvent

        _assert_ondelete(FeedHealthEvent, "feed_id", "CASCADE")

    def test_override_watermark_override_id(self) -> None:
        """Override watermarks belong to an override — CASCADE on delete."""
        from libs.contracts.models import OverrideWatermark

        _assert_ondelete(OverrideWatermark, "override_id", "CASCADE")


# ---------------------------------------------------------------------------
# Test: RESTRICT semantics (audit-trail actors, cross-entity references)
# ---------------------------------------------------------------------------


class TestRestrictForeignKeys:
    """FK columns where RESTRICT is the correct semantic."""

    def test_strategy_created_by(self) -> None:
        """Audit FK — cannot delete user if they created strategies."""
        from libs.contracts.models import Strategy

        _assert_ondelete(Strategy, "created_by", "RESTRICT")

    def test_candidate_strategy_id(self) -> None:
        """Cannot delete strategy if candidates reference it."""
        from libs.contracts.models import Candidate

        _assert_ondelete(Candidate, "strategy_id", "RESTRICT")

    def test_candidate_submitted_by(self) -> None:
        """Audit FK — cannot delete submitter user."""
        from libs.contracts.models import Candidate

        _assert_ondelete(Candidate, "submitted_by", "RESTRICT")

    def test_deployment_strategy_id(self) -> None:
        """Cannot delete strategy if deployments reference it."""
        from libs.contracts.models import Deployment

        _assert_ondelete(Deployment, "strategy_id", "RESTRICT")

    def test_deployment_deployed_by(self) -> None:
        """Audit FK — cannot delete deployer user."""
        from libs.contracts.models import Deployment

        _assert_ondelete(Deployment, "deployed_by", "RESTRICT")

    def test_run_strategy_id(self) -> None:
        """Cannot delete strategy if runs reference it."""
        from libs.contracts.models import Run

        _assert_ondelete(Run, "strategy_id", "RESTRICT")

    def test_override_submitter_id(self) -> None:
        """Audit FK — cannot delete submitter user."""
        from libs.contracts.models import Override

        _assert_ondelete(Override, "submitter_id", "RESTRICT")

    def test_override_reviewer_id(self) -> None:
        """Audit FK — cannot delete reviewer user."""
        from libs.contracts.models import Override

        _assert_ondelete(Override, "reviewer_id", "RESTRICT")

    def test_override_applied_by(self) -> None:
        """Audit FK — cannot delete applier user."""
        from libs.contracts.models import Override

        _assert_ondelete(Override, "applied_by", "RESTRICT")

    def test_approval_request_candidate_id(self) -> None:
        """Cannot delete candidate if approval requests reference it."""
        from libs.contracts.models import ApprovalRequest

        _assert_ondelete(ApprovalRequest, "candidate_id", "RESTRICT")

    def test_approval_request_requested_by(self) -> None:
        """Audit FK — cannot delete requester user."""
        from libs.contracts.models import ApprovalRequest

        _assert_ondelete(ApprovalRequest, "requested_by", "RESTRICT")

    def test_approval_request_reviewer_id(self) -> None:
        """Audit FK — cannot delete reviewer user."""
        from libs.contracts.models import ApprovalRequest

        _assert_ondelete(ApprovalRequest, "reviewer_id", "RESTRICT")

    def test_draft_autosave_user_id(self) -> None:
        """Cannot delete user if autosaves reference them."""
        from libs.contracts.models import DraftAutosave

        _assert_ondelete(DraftAutosave, "user_id", "RESTRICT")

    def test_draft_autosave_strategy_id(self) -> None:
        """Cannot delete strategy if autosaves reference it."""
        from libs.contracts.models import DraftAutosave

        _assert_ondelete(DraftAutosave, "strategy_id", "RESTRICT")

    def test_parity_event_feed_id(self) -> None:
        """Cannot delete feed if parity events reference it."""
        from libs.contracts.models import ParityEvent

        _assert_ondelete(ParityEvent, "feed_id", "RESTRICT")

    def test_parity_event_reference_feed_id(self) -> None:
        """Cannot delete reference feed if parity events reference it."""
        from libs.contracts.models import ParityEvent

        _assert_ondelete(ParityEvent, "reference_feed_id", "RESTRICT")

    def test_certification_event_feed_id(self) -> None:
        """Cannot delete feed if certification events reference it."""
        from libs.contracts.models import CertificationEvent

        _assert_ondelete(CertificationEvent, "feed_id", "RESTRICT")

    def test_certification_event_run_id(self) -> None:
        """Cannot delete run if certification events reference it."""
        from libs.contracts.models import CertificationEvent

        _assert_ondelete(CertificationEvent, "run_id", "RESTRICT")

    def test_promotion_request_candidate_id(self) -> None:
        """Cannot delete candidate if promotion requests reference it."""
        from libs.contracts.models import PromotionRequest

        _assert_ondelete(PromotionRequest, "candidate_id", "RESTRICT")

    def test_promotion_request_requester_id(self) -> None:
        """Audit FK — cannot delete requester user."""
        from libs.contracts.models import PromotionRequest

        _assert_ondelete(PromotionRequest, "requester_id", "RESTRICT")

    def test_promotion_request_reviewer_id(self) -> None:
        """Audit FK — cannot delete reviewer user."""
        from libs.contracts.models import PromotionRequest

        _assert_ondelete(PromotionRequest, "reviewer_id", "RESTRICT")

    def test_refresh_token_user_id(self) -> None:
        """Cannot delete user if refresh tokens reference them."""
        from libs.contracts.models import RefreshToken

        _assert_ondelete(RefreshToken, "user_id", "RESTRICT")

    def test_chart_cache_entry_run_id(self) -> None:
        """Cannot delete run if chart cache entries reference it."""
        from libs.contracts.models import ChartCacheEntry

        _assert_ondelete(ChartCacheEntry, "run_id", "RESTRICT")

    def test_symbol_lineage_entry_feed_id(self) -> None:
        """Cannot delete feed if symbol lineage entries reference it."""
        from libs.contracts.models import SymbolLineageEntry

        _assert_ondelete(SymbolLineageEntry, "feed_id", "RESTRICT")

    def test_symbol_lineage_entry_run_id(self) -> None:
        """Cannot delete run if symbol lineage entries reference it."""
        from libs.contracts.models import SymbolLineageEntry

        _assert_ondelete(SymbolLineageEntry, "run_id", "RESTRICT")

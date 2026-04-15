"""
Unit tests for STUB-2 (wired stub functions) and STUB-3 (artifact storage).

Tests cover:
- get_run_results: returns data from Run/Trial/Artifact tables, None if not found.
- get_readiness_report: computes grade from run status, trials, certifications.
- submit_promotion_request: creates PromotionRequest record in DB.
- get_artifact_storage: reads backend/root from env vars.

Dependencies:
    - SQLAlchemy: In-memory SQLite.
    - libs.contracts.models: Run, Trial, Artifact, PromotionRequest, CertificationEvent.

Example:
    pytest tests/unit/test_stub_replacements.py -v
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.contracts.models import (
    Artifact,
    Base,
    CertificationEvent,
    PromotionRequest,
    Run,
    Trial,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session with all tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()


@pytest.fixture()
def sample_run(db_session: Session) -> Run:
    """Create a completed run with trials and artifacts."""
    run = Run(
        id="01HRUN0000000000000000000",
        run_type="backtest",
        status="completed",
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
    )
    db_session.add(run)

    # Add trials
    t1 = Trial(
        id="01HTRIAL000000000000000001",
        run_id=run.id,
        trial_index=0,
        status="completed",
        metrics={"sharpe": 1.5, "max_dd": -0.05},
    )
    t2 = Trial(
        id="01HTRIAL000000000000000002",
        run_id=run.id,
        trial_index=1,
        status="completed",
        metrics={"sharpe": 1.2, "max_dd": -0.08},
    )
    db_session.add_all([t1, t2])

    # Add artifact
    art = Artifact(
        id="01HART0000000000000000001",
        run_id=run.id,
        artifact_type="report",
        uri="s3://bucket/reports/report-1.pdf",
        size_bytes=1024,
        checksum="abc123",
    )
    db_session.add(art)
    db_session.flush()
    return run


# ---------------------------------------------------------------------------
# get_run_results tests
# ---------------------------------------------------------------------------


class TestGetRunResults:
    """Tests for the DB-backed get_run_results implementation."""

    def test_returns_none_for_nonexistent_run(self, db_session: Session) -> None:
        """get_run_results should return None when run_id does not exist."""
        from services.api.main import get_run_results

        result = get_run_results("01HNOTFOUND0000000000000000", db=db_session)
        assert result is None

    def test_returns_run_with_trials_and_artifacts(
        self, db_session: Session, sample_run: Run
    ) -> None:
        """get_run_results should return run data with metrics and artifacts."""
        from services.api.main import get_run_results

        result = get_run_results(sample_run.id, db=db_session)
        assert result is not None
        assert result["run_id"] == sample_run.id
        assert result["status"] == "completed"
        assert result["run_type"] == "backtest"
        assert len(result["metrics"]) == 2
        assert len(result["artifacts"]) == 1
        assert result["artifacts"][0]["artifact_type"] == "report"

    def test_returns_empty_metrics_for_run_without_trials(self, db_session: Session) -> None:
        """Run with no trials should return empty metrics list."""
        from services.api.main import get_run_results

        run = Run(
            id="01HRUNEMPTY000000000000000",
            run_type="paper",
            status="pending",
        )
        db_session.add(run)
        db_session.flush()

        result = get_run_results(run.id, db=db_session)
        assert result is not None
        assert result["metrics"] == []
        assert result["artifacts"] == []


# ---------------------------------------------------------------------------
# get_readiness_report tests
# ---------------------------------------------------------------------------


class TestGetReadinessReport:
    """Tests for the DB-backed get_readiness_report implementation."""

    def test_returns_none_for_nonexistent_run(self, db_session: Session) -> None:
        """get_readiness_report should return None when run_id does not exist."""
        from services.api.main import get_readiness_report

        result = get_readiness_report("01HNOTFOUND0000000000000000", db=db_session)
        assert result is None

    def test_green_grade_for_completed_run_with_certs(
        self, db_session: Session, sample_run: Run
    ) -> None:
        """Completed run with certifications and no blockers should be GREEN."""
        from services.api.main import get_readiness_report

        cert = CertificationEvent(
            id="01HCERT0000000000000000001",
            run_id=sample_run.id,
            certification_type="backtest_coverage",
            status="passed",
            blocked=False,
        )
        db_session.add(cert)
        db_session.flush()

        report = get_readiness_report(sample_run.id, db=db_session)
        assert report is not None
        assert report["readiness_grade"] == "GREEN"
        assert report["blockers"] == []

    def test_yellow_grade_for_completed_run_without_certs(
        self, db_session: Session, sample_run: Run
    ) -> None:
        """Completed run without certifications should be YELLOW."""
        from services.api.main import get_readiness_report

        report = get_readiness_report(sample_run.id, db=db_session)
        assert report is not None
        assert report["readiness_grade"] == "YELLOW"

    def test_red_grade_for_incomplete_run_with_failures(self, db_session: Session) -> None:
        """Pending run with failed trials should be RED (multiple blockers)."""
        from services.api.main import get_readiness_report

        run = Run(
            id="01HRUNFAIL00000000000000000",
            run_type="backtest",
            status="running",
        )
        db_session.add(run)

        trial = Trial(
            id="01HTRIALFAIL0000000000001",
            run_id=run.id,
            trial_index=0,
            status="failed",
        )
        db_session.add(trial)
        db_session.flush()

        report = get_readiness_report(run.id, db=db_session)
        assert report is not None
        assert report["readiness_grade"] == "RED"
        assert len(report["blockers"]) >= 2

    def test_blockers_for_no_trials(self, db_session: Session) -> None:
        """Run with no trials should have a 'no trials' blocker."""
        from services.api.main import get_readiness_report

        run = Run(
            id="01HRUNNOTRIAL00000000000000",
            run_type="backtest",
            status="completed",
        )
        db_session.add(run)
        db_session.flush()

        report = get_readiness_report(run.id, db=db_session)
        assert any("No trials" in b for b in report["blockers"])


# ---------------------------------------------------------------------------
# submit_promotion_request tests
# ---------------------------------------------------------------------------


class TestSubmitPromotionRequest:
    """Tests for the DB-backed submit_promotion_request implementation."""

    def test_creates_promotion_record_in_db(self, db_session: Session) -> None:
        """submit_promotion_request should persist a PromotionRequest."""
        from services.api.main import submit_promotion_request

        payload = {
            "candidate_id": "01HCAND0000000000000000001",
            "requester_id": "01HUSER0000000000000000001",
            "target_environment": "paper",
            "rationale": "Backtest passed all gates.",
            "evidence_link": "https://evidence.example.com/run/123",
        }

        result = submit_promotion_request(payload, db=db_session)
        db_session.flush()

        assert "job_id" in result
        assert result["status"] == "pending"
        assert len(result["job_id"]) == 26  # ULID length

        # Verify persisted in DB
        record = db_session.get(PromotionRequest, result["job_id"])
        assert record is not None
        assert record.status == "pending"
        assert record.target_environment == "paper"

    def test_returns_unique_job_ids(self, db_session: Session) -> None:
        """Each call should return a unique job_id."""
        from services.api.main import submit_promotion_request

        payload = {
            "candidate_id": "01HCAND0000000000000000001",
            "requester_id": "01HUSER0000000000000000001",
        }

        r1 = submit_promotion_request(payload, db=db_session)
        r2 = submit_promotion_request(payload, db=db_session)
        assert r1["job_id"] != r2["job_id"]


# ---------------------------------------------------------------------------
# Artifact storage configuration tests (STUB-3)
# ---------------------------------------------------------------------------


class TestArtifactStorageConfiguration:
    """Tests for environment-driven artifact storage configuration."""

    def test_default_backend_is_local(self) -> None:
        """Default backend should be 'local' with production root."""
        from libs.storage.local_storage import LocalArtifactStorage
        from services.api.routes.artifacts import get_artifact_storage

        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing overrides
            os.environ.pop("ARTIFACT_STORAGE_BACKEND", None)
            os.environ.pop("ARTIFACT_STORAGE_ROOT", None)

            storage = get_artifact_storage()
            assert isinstance(storage, LocalArtifactStorage)
            # LocalArtifactStorage converts root to pathlib.Path internally
            assert str(storage._root) == "/var/lib/fxlab/artifacts"

    def test_custom_root_from_env(self) -> None:
        """ARTIFACT_STORAGE_ROOT should override the default path."""
        from libs.storage.local_storage import LocalArtifactStorage
        from services.api.routes.artifacts import get_artifact_storage

        with patch.dict(
            os.environ,
            {"ARTIFACT_STORAGE_BACKEND": "local", "ARTIFACT_STORAGE_ROOT": "/data/artifacts"},
        ):
            storage = get_artifact_storage()
            assert isinstance(storage, LocalArtifactStorage)
            assert str(storage._root) == "/data/artifacts"

    def test_unsupported_backend_raises_error(self) -> None:
        """Unknown backend should raise ValueError."""
        from services.api.routes.artifacts import get_artifact_storage

        with (
            patch.dict(os.environ, {"ARTIFACT_STORAGE_BACKEND": "gcs"}),
            pytest.raises(ValueError, match="Unsupported"),
        ):
            get_artifact_storage()

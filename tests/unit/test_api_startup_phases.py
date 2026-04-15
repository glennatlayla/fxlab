"""
Unit tests for startup phase logging and wiring-block isolation in
services/api/main.py.

Rationale:
The API lifespan wires several independent subsystems in sequence
(orphan recovery, LiveExecutionService, periodic reconciliation, etc.).
Historically these blocks cross-referenced each other via local
variables (`adapter_registry_dict`, `app.state.live_execution_db_session`)
which meant a failure in an earlier block produced a cascading
NameError/AttributeError in a later block whose exception handler then
logged a misleading root cause. When the system is being installed on a
remote host (e.g. minitux) this makes root-cause triage slow.

These tests enforce two invariants:

1.  Structural: the periodic-reconciliation try/except does NOT reference
    names that only exist inside the LiveExecutionService try/except.
    A regex scan of the source is the cheapest durable guard.

2.  Observability: the `_startup_phase` context manager emits the three
    expected structured events (phase_begin, phase_complete, phase_failed),
    so the operator log trail on minitux answers "which phase failed?"
    without needing a debugger.

3.  Runtime: the `_log_runtime_versions` helper emits a single structured
    log line with the package versions and non-secret env snapshot.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
import structlog

# ---------------------------------------------------------------------------
# Structural guards — static analysis of services/api/main.py
# ---------------------------------------------------------------------------


def _main_source() -> str:
    """Return the text of services/api/main.py."""
    # tests/unit/test_api_startup_phases.py -> repo root is three parents up.
    repo_root = Path(__file__).resolve().parents[2]
    main_path = repo_root / "services" / "api" / "main.py"
    assert main_path.is_file(), f"services/api/main.py not found at {main_path}"
    return main_path.read_text(encoding="utf-8")


def _extract_block(src: str, start_marker: str, end_marker: str) -> str:
    """
    Return the substring between (and excluding) start_marker and end_marker.

    Raises AssertionError if either marker is missing — that also signals
    the block has been renamed and this test needs a code review.
    """
    start = src.find(start_marker)
    assert start != -1, f"start marker not found: {start_marker!r}"
    end = src.find(end_marker, start)
    assert end != -1, f"end marker not found after start: {end_marker!r}"
    return src[start:end]


class TestPeriodicReconciliationBlockIsolation:
    """
    The periodic reconciliation try/except block MUST be self-contained:
    it must build its own adapter snapshot and its own DB session from
    durable inputs (broker_registry, SessionLocal), not reuse the locals
    of the LiveExecutionService block.
    """

    _START = "# Periodic broker-vs-internal reconciliation (M19 production hardening)"
    _END = 'logger.info("api.startup"'

    def test_block_is_present(self) -> None:
        src = _main_source()
        block = _extract_block(src, self._START, self._END)
        assert "PeriodicReconciliationJob" in block, (
            "periodic reconciliation block no longer wires PeriodicReconciliationJob"
        )

    def test_block_does_not_reference_live_execution_db_session_attr(self) -> None:
        src = _main_source()
        block = _extract_block(src, self._START, self._END)
        # Comments are allowed to mention the name (explaining why we do
        # not use it). Strip comment lines before scanning.
        code_only = "\n".join(
            line for line in block.splitlines() if not line.lstrip().startswith("#")
        )
        assert "app.state.live_execution_db_session" not in code_only, (
            "periodic reconciliation must not reuse app.state.live_execution_db_session; "
            "if LiveExecutionService wiring failed, that attr is never set and this block "
            "would AttributeError inside its own try/except, producing a misleading log."
        )

    def test_block_does_not_reference_live_exec_locals(self) -> None:
        src = _main_source()
        block = _extract_block(src, self._START, self._END)
        code_only = "\n".join(
            line for line in block.splitlines() if not line.lstrip().startswith("#")
        )
        # These are local variables declared inside the LiveExecutionService
        # try block. Their names don't exist at this point in lifespan if
        # the prior try failed.
        forbidden_locals = [
            "adapter_registry_dict",
            "db_session_live",
            "live_execution_service",
        ]
        for name in forbidden_locals:
            # Whole-word match to avoid false positives on substrings.
            pattern = rf"\b{re.escape(name)}\b"
            assert not re.search(pattern, code_only), (
                f"periodic reconciliation block must not reference "
                f"LiveExecutionService block local {name!r}"
            )


class TestLiveExecutionPhaseInstrumentation:
    """
    The LiveExecutionService wiring block is instrumented with explicit
    startup.phase_begin / phase_complete / phase_failed events so that
    the operator log trail pinpoints which block failed even when the
    block's own except clause swallows the exception to keep the API up.
    """

    def test_live_execution_phase_begin_emitted(self) -> None:
        src = _main_source()
        assert 'phase="live_execution_wiring"' in src, (
            "LiveExecutionService block missing phase label 'live_execution_wiring'"
        )
        assert "startup.phase_begin" in src
        assert "startup.phase_complete" in src
        assert "startup.phase_failed" in src


# ---------------------------------------------------------------------------
# Behavioural tests for _startup_phase helper
# ---------------------------------------------------------------------------


class TestStartupPhaseHelper:
    """
    _startup_phase must emit phase_begin at entry, phase_complete on clean
    exit, and phase_failed on exception (with the exception re-raised).
    """

    def _events(self, captured: list[dict]) -> list[str]:
        return [e.get("event") for e in captured]

    def test_success_emits_begin_then_complete(self) -> None:
        from services.api.main import _startup_phase

        captured: list[dict] = []

        def _capture(logger, method_name, event_dict):  # noqa: ARG001
            captured.append(event_dict)
            return event_dict

        structlog.configure(
            processors=[_capture, structlog.processors.KeyValueRenderer()],
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=False,
        )
        try:
            with _startup_phase("unit_test_phase", foo="bar"):
                pass
        finally:
            structlog.reset_defaults()

        events = self._events(captured)
        assert "startup.phase_begin" in events
        assert "startup.phase_complete" in events
        assert "startup.phase_failed" not in events

        complete = next(e for e in captured if e.get("event") == "startup.phase_complete")
        assert complete["phase"] == "unit_test_phase"
        assert complete["foo"] == "bar"
        assert isinstance(complete["duration_ms"], int)
        assert complete["duration_ms"] >= 0

    def test_exception_emits_failed_and_reraises(self) -> None:
        from services.api.main import _startup_phase

        captured: list[dict] = []

        def _capture(logger, method_name, event_dict):  # noqa: ARG001
            captured.append(event_dict)
            return event_dict

        structlog.configure(
            processors=[_capture, structlog.processors.KeyValueRenderer()],
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=False,
        )
        try:
            with pytest.raises(RuntimeError, match="boom"):
                with _startup_phase("unit_test_phase_fail"):
                    raise RuntimeError("boom")
        finally:
            structlog.reset_defaults()

        events = self._events(captured)
        assert "startup.phase_begin" in events
        assert "startup.phase_failed" in events
        assert "startup.phase_complete" not in events

        failed = next(e for e in captured if e.get("event") == "startup.phase_failed")
        assert failed["phase"] == "unit_test_phase_fail"
        assert isinstance(failed["duration_ms"], int)


# ---------------------------------------------------------------------------
# Behavioural test for _log_runtime_versions
# ---------------------------------------------------------------------------


class TestLogRuntimeVersions:
    def test_emits_structured_versions_and_scheme_only(self) -> None:
        from services.api.main import _log_runtime_versions

        captured: list[dict] = []

        def _capture(logger, method_name, event_dict):  # noqa: ARG001
            captured.append(event_dict)
            return event_dict

        structlog.configure(
            processors=[_capture, structlog.processors.KeyValueRenderer()],
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=False,
        )
        try:
            with patch.dict(
                "os.environ",
                {
                    "ENVIRONMENT": "production",
                    "DATABASE_URL": "postgresql+psycopg://user:SEKRET@db:5432/fxlab?sslmode=require",
                    "REDIS_URL": "redis://redis:6379/0",
                    "RATE_LIMIT_BACKEND": "redis",
                    "RECONCILIATION_INTERVAL_SECONDS": "120",
                    "ARTIFACT_STORAGE_BACKEND": "minio",
                },
                clear=False,
            ):
                _log_runtime_versions()
        finally:
            structlog.reset_defaults()

        version_events = [e for e in captured if e.get("event") == "startup.runtime_versions"]
        assert len(version_events) == 1
        ev = version_events[0]

        # Schemes must be logged, but raw credentials must NOT be.
        assert ev["database_url_scheme"] == "postgresql+psycopg://..."
        assert "SEKRET" not in str(ev)
        assert ev["redis_url_scheme"] == "redis://..."
        assert ev["environment"] == "production"
        assert ev["rate_limit_backend"] == "redis"
        assert ev["reconciliation_interval_seconds"] == "120"
        assert ev["artifact_storage_backend"] == "minio"

        # Package versions are present (real strings or "not_installed").
        for key in ("pydantic", "pydantic_core", "sqlalchemy", "fastapi", "structlog"):
            assert key in ev
            assert isinstance(ev[key], str)
            assert ev[key]  # non-empty

        # Platform/python surfaced for debugging cross-OS wheel issues.
        assert "python_version" in ev
        assert "platform" in ev
        assert "machine" in ev

    def test_missing_env_vars_do_not_raise(self) -> None:
        """
        _log_runtime_versions must never raise — it runs before anything
        else at startup and a crash here would block every other diagnostic.
        """
        from services.api.main import _log_runtime_versions

        with patch.dict("os.environ", {}, clear=True):
            # Must not raise even with empty env.
            _log_runtime_versions()

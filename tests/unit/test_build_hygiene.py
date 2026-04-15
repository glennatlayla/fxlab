"""
Unit tests for build hygiene and CI configuration (INFRA-7).

Purpose:
    Verify that production build configuration files exist and contain
    the required settings for secure, minimal Docker images and enforced
    test coverage thresholds.

Responsibilities:
    - Verify .dockerignore exists and excludes critical patterns.
    - Verify .coveragerc enforces fail_under threshold.
    - Verify pytest.ini has coverage configuration.

Does NOT:
    - Build Docker images (that is CI's job).
    - Run the full coverage report.

Dependencies:
    - pathlib: For file existence checks.
    - configparser: For parsing .coveragerc.

Example:
    pytest tests/unit/test_build_hygiene.py -v
"""

from __future__ import annotations

import configparser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestDockerignore:
    """Verify .dockerignore exists and excludes sensitive/unnecessary files."""

    def test_dockerignore_exists(self) -> None:
        """.dockerignore must exist at project root."""
        dockerignore = PROJECT_ROOT / ".dockerignore"
        assert dockerignore.is_file(), (
            ".dockerignore not found at project root. Production images "
            "will include test files, secrets, and dev artifacts."
        )

    def test_dockerignore_excludes_tests(self) -> None:
        """.dockerignore must exclude test directories."""
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert "tests/" in content, ".dockerignore must exclude tests/"

    def test_dockerignore_excludes_env_files(self) -> None:
        """.dockerignore must exclude .env files (secrets)."""
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert ".env" in content, ".dockerignore must exclude .env files"

    def test_dockerignore_excludes_git(self) -> None:
        """.dockerignore must exclude .git directory."""
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert ".git" in content, ".dockerignore must exclude .git"

    def test_dockerignore_excludes_archive(self) -> None:
        """.dockerignore must exclude .archive/ directory."""
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert ".archive/" in content, ".dockerignore must exclude .archive/"

    def test_dockerignore_excludes_coverage(self) -> None:
        """.dockerignore must exclude coverage artifacts."""
        content = (PROJECT_ROOT / ".dockerignore").read_text()
        assert ".coveragerc" in content or "htmlcov" in content, (
            ".dockerignore must exclude coverage artifacts"
        )


class TestCoverageConfiguration:
    """Verify coverage thresholds are enforced."""

    def test_coveragerc_exists(self) -> None:
        """.coveragerc must exist at project root."""
        coveragerc = PROJECT_ROOT / ".coveragerc"
        assert coveragerc.is_file(), ".coveragerc not found at project root"

    def test_coveragerc_has_fail_under(self) -> None:
        """.coveragerc must enforce a minimum coverage threshold."""
        config = configparser.ConfigParser()
        config.read(PROJECT_ROOT / ".coveragerc")
        assert config.has_option("report", "fail_under"), (
            ".coveragerc must have fail_under in [report] section"
        )
        threshold = config.getint("report", "fail_under")
        assert threshold >= 80, f"Coverage fail_under must be at least 80%, got {threshold}%"

    def test_coveragerc_omits_test_files(self) -> None:
        """.coveragerc must omit test files from coverage measurement."""
        config = configparser.ConfigParser()
        config.read(PROJECT_ROOT / ".coveragerc")
        omit = config.get("run", "omit", fallback="")
        assert "test" in omit.lower(), ".coveragerc must omit test files from coverage measurement"


class TestPytestConfiguration:
    """Verify pytest is configured for coverage reporting."""

    def test_pytest_ini_exists(self) -> None:
        """pytest.ini must exist at project root."""
        pytest_ini = PROJECT_ROOT / "pytest.ini"
        assert pytest_ini.is_file(), "pytest.ini not found at project root"

    def test_pytest_ini_has_coverage_config(self) -> None:
        """pytest.ini must include --cov flags."""
        content = (PROJECT_ROOT / "pytest.ini").read_text()
        assert "--cov=" in content, "pytest.ini must include --cov= in addopts"
        assert "--cov-report" in content, "pytest.ini must include --cov-report"

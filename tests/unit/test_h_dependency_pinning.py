"""
Dependency pinning validation tests.

Production requirements must pin every dependency to an exact version
(== operator) to ensure reproducible builds. Unpinned (>=, ~=, or bare)
dependencies can silently introduce regressions or supply-chain attacks.

Also validates that the CI pipeline includes a security scanning step.

Dependencies:
    - requirements.txt (project root)
    - .github/workflows/ci.yml

Example:
    pytest tests/unit/test_h_dependency_pinning.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REQUIREMENTS_FILE = _PROJECT_ROOT / "requirements.txt"
_CI_YML = _PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

# Pattern matching unpinned dependency specifiers:
# >=, >, <=, <, ~=, !=, or bare package name with no version at all.
_UNPINNED_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s*(>=|>|<=|<|~=|!=)")
_BARE_RE = re.compile(r"^([a-zA-Z0-9_-]+)\s*$")


def _parse_requirements(path: Path) -> list[str]:
    """
    Return non-empty, non-comment lines from a requirements file.

    Args:
        path: Path to the requirements.txt file.

    Returns:
        List of stripped requirement lines.
    """
    lines: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and not line.startswith("-"):
            lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Tests: dependency pinning
# ---------------------------------------------------------------------------


class TestDependencyPinning:
    """All production dependencies must be pinned to exact versions."""

    def test_requirements_file_exists(self) -> None:
        """requirements.txt must exist at project root."""
        assert _REQUIREMENTS_FILE.exists(), f"requirements.txt not found at {_REQUIREMENTS_FILE}"

    def test_no_unpinned_dependencies(self) -> None:
        """Every dependency must use == pinning, not >= or bare names."""
        lines = _parse_requirements(_REQUIREMENTS_FILE)
        unpinned: list[str] = []
        for line in lines:
            if _UNPINNED_RE.match(line) or _BARE_RE.match(line):
                unpinned.append(line)
        assert not unpinned, (
            f"Found {len(unpinned)} unpinned dependency(ies) in "
            f"requirements.txt: {unpinned}. Use == for all versions."
        )

    def test_all_dependencies_have_versions(self) -> None:
        """Every dependency line must contain ==."""
        lines = _parse_requirements(_REQUIREMENTS_FILE)
        missing: list[str] = []
        for line in lines:
            # Skip editable installs and extras-only lines
            if line.startswith("-e") or line.startswith("."):
                continue
            if "==" not in line:
                missing.append(line)
        assert not missing, f"Dependencies without pinned versions: {missing}"


# ---------------------------------------------------------------------------
# Tests: CI security scanning
# ---------------------------------------------------------------------------


class TestCISecurityScanning:
    """CI pipeline must include a security scanning step."""

    def test_ci_yml_exists(self) -> None:
        """CI workflow file must exist."""
        assert _CI_YML.exists(), f"CI workflow not found at {_CI_YML}"

    def test_ci_includes_security_scan(self) -> None:
        """CI must include a security-scan or audit step."""
        content = _CI_YML.read_text().lower()
        # Accept any of: bandit, safety, pip-audit, npm audit, trivy, snyk
        security_indicators = [
            "bandit",
            "safety",
            "pip-audit",
            "security",
            "audit",
            "trivy",
            "snyk",
        ]
        found = any(term in content for term in security_indicators)
        assert found, (
            "CI workflow missing security scanning step. "
            "Add bandit, pip-audit, safety, or equivalent."
        )

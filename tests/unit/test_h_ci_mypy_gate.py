"""
CI mypy gate validation test.

The mypy type-check step in CI must NOT use continue-on-error, ensuring
type errors block merges and maintain code quality.

Dependencies:
    - .github/workflows/ci.yml

Example:
    pytest tests/unit/test_h_ci_mypy_gate.py -v
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CI_YML = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


class TestMypyCIGate:
    """mypy must be a hard gate — not continue-on-error."""

    def test_mypy_step_does_not_continue_on_error(self) -> None:
        """The mypy step must not have continue-on-error: true."""
        content = yaml.safe_load(_CI_YML.read_text())
        quality_steps = content["jobs"]["quality"]["steps"]

        mypy_step = None
        for step in quality_steps:
            if "mypy" in step.get("name", "").lower():
                mypy_step = step
                break

        assert mypy_step is not None, "No mypy step found in quality job"
        coe = mypy_step.get("continue-on-error", False)
        assert coe is not True, "mypy step has continue-on-error: true — type errors must block CI"

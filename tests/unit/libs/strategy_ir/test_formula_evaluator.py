"""
Unit tests for the safe arithmetic formula evaluator (M1.B6).

Verifies:
- Hand-computed correctness against a known Fibonacci formula.
- Parametrised correctness across all four Fibonacci formulas in the
  FX_MTF_DailyTrend_H1Pullback strategy IR's `derived_fields` block.
- Injection / disallowed-syntax rejection at PARSE time (compile()),
  not at evaluation time. This is a security boundary, not a style
  preference.
- Divide-by-zero produces nan (numpy convention), not an exception.
- Re-entrancy: two threads evaluating two different compiled formulas
  with two different value-dicts produce independent, correct results.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path

import pytest

from libs.strategy_ir.formula_evaluator import CompiledFormula, FormulaEvaluator

# ---------------------------------------------------------------------------
# Spec constants
# ---------------------------------------------------------------------------

# The four Fibonacci formulas live in the MTF Daily-Trend / H1-Pullback IR's
# `derived_fields` block. We load them from disk so the test stays in sync
# with the spec file rather than embedding magic strings.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_STRATEGY_IR_PATH = (
    _REPO_ROOT
    / "Strategy Repo"
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_MTF_DailyTrend_H1Pullback.strategy_ir.json"
)


def _load_fibonacci_formulas() -> list[tuple[str, str]]:
    """
    Load the four (id, formula) pairs from the strategy IR's derived_fields.

    Returns:
        List of (derived_field_id, formula_source) tuples. Length asserted
        to be 4 so a future spec change loud-fails the test instead of
        silently dropping coverage.
    """
    with _STRATEGY_IR_PATH.open("r", encoding="utf-8") as fh:
        ir = json.load(fh)
    fields = ir["derived_fields"]
    pairs = [(f["id"], f["formula"]) for f in fields]
    assert len(pairs) == 4, (
        f"Expected exactly 4 Fibonacci formulas in the MTF Pullback IR; "
        f"found {len(pairs)}. Update the test if the spec deliberately changed."
    )
    return pairs


# Fixed indicator values used for the parametrised tests. Hand-picked so the
# Fibonacci arithmetic produces non-trivial, distinct results per formula.
_SWING_HIGH = 1.10000
_SWING_LOW = 1.08000
_RANGE = _SWING_HIGH - _SWING_LOW  # 0.02000

_EXPECTED_BY_ID = {
    # swing_high - (range * 0.382) = 1.10 - 0.00764 = 1.09236
    "fib_38_long": _SWING_HIGH - (_RANGE * 0.382),
    # swing_high - (range * 0.618) = 1.10 - 0.01236 = 1.08764
    "fib_61_long": _SWING_HIGH - (_RANGE * 0.618),
    # swing_low + (range * 0.382) = 1.08 + 0.00764 = 1.08764
    "fib_38_short": _SWING_LOW + (_RANGE * 0.382),
    # swing_low + (range * 0.618) = 1.08 + 0.01236 = 1.09236
    "fib_61_short": _SWING_LOW + (_RANGE * 0.618),
}


# ---------------------------------------------------------------------------
# Hand-computed sanity check
# ---------------------------------------------------------------------------


def test_evaluator_handcomputed_fib_38_long_matches_arithmetic() -> None:
    """The canonical example from the workplan must produce the exact value."""
    source = "swing_high_h1 - ((swing_high_h1 - swing_low_h1) * 0.382)"
    compiled = FormulaEvaluator().compile(source)

    result = compiled.evaluate({"swing_high_h1": 1.10000, "swing_low_h1": 1.08000})

    expected = 1.10000 - ((1.10000 - 1.08000) * 0.382)
    assert result == pytest.approx(expected, abs=1e-12)


# ---------------------------------------------------------------------------
# Parametrised: every Fibonacci formula in the spec
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_id,source",
    _load_fibonacci_formulas(),
    ids=[pair[0] for pair in _load_fibonacci_formulas()],
)
def test_evaluator_matches_spec_for_each_fibonacci_formula(field_id: str, source: str) -> None:
    """
    Each derived_fields formula must compile and evaluate to the
    arithmetic answer derived from the same inputs.
    """
    compiled = FormulaEvaluator().compile(source)
    values = {"swing_high_h1": _SWING_HIGH, "swing_low_h1": _SWING_LOW}

    result = compiled.evaluate(values)

    assert result == pytest.approx(_EXPECTED_BY_ID[field_id], abs=1e-12)


def test_compile_returns_reusable_compiled_formula() -> None:
    """A CompiledFormula must be reusable across many evaluate() calls."""
    compiled = FormulaEvaluator().compile("a + b")
    assert isinstance(compiled, CompiledFormula)
    assert compiled.evaluate({"a": 1.0, "b": 2.0}) == pytest.approx(3.0)
    assert compiled.evaluate({"a": 10.0, "b": 20.0}) == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Injection / disallowed-syntax rejection — MUST raise at compile() time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malicious_source",
    [
        # The headline injection attempt from the workplan acceptance criteria.
        "__import__('os').system('rm -rf /')",
        # `import` is a statement, not an expression — ast.parse mode='eval'
        # rejects it before our walker even sees it; still asserted explicitly
        # because the contract is "rejected at parse time".
        "import os",
        # Lambdas introduce arbitrary callables.
        "lambda x: x",
        # List / dict / set / tuple displays are not arithmetic.
        "[1, 2, 3]",
        "{1: 2}",
        "(1, 2, 3)",
        # Function calls are unconditionally forbidden — even seemingly safe
        # ones like abs() — because allowing any call opens the surface area.
        "abs(x)",
        "min(a, b)",
        "max(a, b)",
        # Attribute access could reach __class__, __subclasses__, etc.
        "x.y",
        "().__class__",
        # Subscript / indexing.
        "a[0]",
        # Comparisons / boolean ops are out of scope (this evaluator is
        # arithmetic only; logic lives in a different IR block).
        "a > b",
        "a and b",
        "not a",
        # Comprehensions / generator expressions.
        "[x for x in range(10)]",
        # Conditional expressions.
        "a if b else c",
        # Power operator is not in the allowed set.
        "a ** b",
        # Floor division and modulo are not in the allowed set.
        "a // b",
        "a % b",
        # Bitwise operators.
        "a | b",
        "a & b",
        # Walrus / assignment (Python 3.8+).
        "(a := 1)",
        # f-strings.
        "f'{a}'",
    ],
)
def test_compile_rejects_disallowed_syntax_at_parse_time(
    malicious_source: str,
) -> None:
    """
    Any non-whitelisted construct MUST be rejected by compile(), not by
    evaluate(). This guarantees no malicious AST node is ever walked with
    a populated values dict.
    """
    evaluator = FormulaEvaluator()
    with pytest.raises(ValueError):
        evaluator.compile(malicious_source)


def test_evaluate_rejects_unknown_variable_reference() -> None:
    """
    A name that compiles fine but is missing from the values dict at
    evaluate() time must raise a clear error rather than silently yield
    None or KeyError.
    """
    compiled = FormulaEvaluator().compile("a + b")
    with pytest.raises(ValueError):
        compiled.evaluate({"a": 1.0})  # 'b' missing on purpose


# ---------------------------------------------------------------------------
# Divide-by-zero — return nan, do not raise
# ---------------------------------------------------------------------------


def test_divide_by_zero_returns_nan() -> None:
    """A formula that divides by zero must yield nan, not raise."""
    compiled = FormulaEvaluator().compile("a / b")
    result = compiled.evaluate({"a": 1.0, "b": 0.0})
    assert math.isnan(result)


def test_zero_divided_by_zero_returns_nan() -> None:
    """0/0 is also nan (numpy convention)."""
    compiled = FormulaEvaluator().compile("a / b")
    result = compiled.evaluate({"a": 0.0, "b": 0.0})
    assert math.isnan(result)


# ---------------------------------------------------------------------------
# Re-entrancy / concurrency
# ---------------------------------------------------------------------------


def test_concurrent_evaluation_of_two_formulas_is_independent() -> None:
    """
    Two threads, two different compiled formulas, two different value
    dicts, 1000 iterations each. Neither thread may observe the other's
    values. Failure mode (if the evaluator held module-level state) would
    be sporadic incorrect results.
    """
    formula_a = FormulaEvaluator().compile("x * 2 + y")
    formula_b = FormulaEvaluator().compile("x - y / 4")

    iterations = 1000
    results_a: list[float] = []
    results_b: list[float] = []
    errors: list[BaseException] = []

    def run_a() -> None:
        try:
            for i in range(iterations):
                values = {"x": float(i), "y": float(i + 1)}
                results_a.append(formula_a.evaluate(values))
        except BaseException as exc:  # noqa: BLE001 — surface any failure
            errors.append(exc)

    def run_b() -> None:
        try:
            for i in range(iterations):
                values = {"x": float(i + 100), "y": 8.0}
                results_b.append(formula_b.evaluate(values))
        except BaseException as exc:  # noqa: BLE001 — surface any failure
            errors.append(exc)

    t_a = threading.Thread(target=run_a)
    t_b = threading.Thread(target=run_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    assert errors == [], f"Concurrent evaluation raised: {errors!r}"
    assert len(results_a) == iterations
    assert len(results_b) == iterations

    # Verify every result against the closed-form expectation. If the
    # threads ever cross-contaminated each other's value dict, at least
    # one assertion in this loop would fail.
    for i in range(iterations):
        assert results_a[i] == pytest.approx(float(i) * 2 + float(i + 1))
        assert results_b[i] == pytest.approx(float(i + 100) - 8.0 / 4)

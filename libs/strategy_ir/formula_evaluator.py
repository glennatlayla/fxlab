"""
Safe arithmetic formula evaluator for strategy_ir derived_fields (M1.B6).

Purpose:
    Compile and evaluate the small arithmetic formulas that appear in a
    strategy IR's `derived_fields` block (e.g. Fibonacci retracements
    expressed as `swing_high - ((swing_high - swing_low) * 0.382)`)
    without ever invoking Python's dynamic-execution builtins.

Responsibilities:
    - Parse a formula string with `ast.parse(source, mode='eval')`.
    - Walk the resulting AST, rejecting any node type that is not on a
      strict whitelist. Rejection happens at compile() time, before any
      values are bound, so a malicious source string cannot reach the
      evaluation phase under any circumstance.
    - Evaluate the compiled tree against a caller-supplied dict of
      indicator values.
    - Return numpy-style nan for divide-by-zero rather than raising.
    - Be re-entrant: a CompiledFormula holds only the immutable AST
      node it was built from. Two threads evaluating two different
      formulas with two different value dicts cannot interfere.

Does NOT:
    - Use Python's dynamic-execution builtins for any reason.
    - Resolve names against globals(), builtins, or any module-level
      mutable state. The whitelist forbids ast.Attribute, ast.Call,
      ast.Subscript, etc., so there is no syntactic path to escape
      the supplied values dict.
    - Support comparison, boolean, bitwise, exponent, floor-div, or
      modulo operators. Logic and comparisons live in a different
      part of the IR.
    - Cache compiled formulas. Callers compile once, evaluate many.

Dependencies:
    - Python stdlib only: `ast`, `math`. No third-party packages.

Raises:
    - ValueError on disallowed syntax (compile time).
    - ValueError on unknown variable reference (evaluate time).

Example:
    evaluator = FormulaEvaluator()
    compiled = evaluator.compile(
        "swing_high_h1 - ((swing_high_h1 - swing_low_h1) * 0.382)"
    )
    fib_38 = compiled.evaluate(
        {"swing_high_h1": 1.10, "swing_low_h1": 1.08}
    )
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------
# Every AST node type the evaluator is allowed to see. Any other node
# type encountered during the compile-time walk causes immediate rejection.
# This set is intentionally small and is the security boundary that
# replaces any dynamic-execution pathway.
_ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset(
    {
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.USub,
        ast.UAdd,
        ast.Name,
        ast.Constant,
        ast.Load,
    }
)


@dataclass(frozen=True)
class CompiledFormula:
    """
    A pre-validated, immutable formula ready for repeated evaluation.

    Attributes:
        source: The original formula string. Retained for diagnostics
            and structured logging; not used during evaluation.
        tree: The parsed-and-validated `ast.Expression` node. Immutable
            for the lifetime of this object, which is what makes
            evaluate() safe to call concurrently from multiple threads.

    Example:
        compiled = FormulaEvaluator().compile("a + b")
        compiled.evaluate({"a": 1.0, "b": 2.0})  # -> 3.0
    """

    source: str
    tree: ast.Expression

    def evaluate(self, values: dict[str, float]) -> float:
        """
        Evaluate this compiled formula against the supplied values dict.

        Args:
            values: Mapping from indicator-id to numeric value. Every
                `ast.Name` reference in the formula must be a key in
                this dict; missing keys raise ValueError.

        Returns:
            The numeric result as a float. Divide-by-zero returns
            `math.nan` (numpy convention) rather than raising
            ZeroDivisionError.

        Raises:
            ValueError: If the formula references a name that is not
                present in `values`. (Disallowed syntax was already
                rejected at compile() time, so it cannot occur here.)

        Example:
            compiled = FormulaEvaluator().compile("a / b")
            compiled.evaluate({"a": 1.0, "b": 0.0})  # -> nan
        """
        # The recursion is parameterised on the local `values` dict,
        # not on any instance or module attribute, so it is re-entrant
        # by construction. No locks needed.
        return _eval_node(self.tree.body, values)


class FormulaEvaluator:
    """
    Stateless factory that turns a formula string into a CompiledFormula.

    Responsibilities:
        - Parse the source with `ast.parse(source, mode='eval')`.
        - Walk every node in the resulting tree and reject any node
          whose type is not in the `_ALLOWED_NODES` whitelist.
        - Wrap the validated tree in a CompiledFormula.

    Does NOT:
        - Hold any per-formula state. Re-entrancy is guaranteed because
          there is no instance-level mutable state to share.
        - Evaluate. Evaluation is performed by `CompiledFormula.evaluate`.

    Raises:
        - ValueError: At compile() time if the source contains any
          syntactic construct outside the whitelist (function calls,
          attribute access, comparisons, comprehensions, lambdas,
          imports, subscripting, exponentiation, modulo, floor-div,
          bitwise ops, walrus, f-strings, etc.).

    Example:
        evaluator = FormulaEvaluator()
        compiled = evaluator.compile("a + b * c")
        compiled.evaluate({"a": 1, "b": 2, "c": 3})  # -> 7
    """

    def compile(self, source: str) -> CompiledFormula:  # noqa: A003
        """
        Compile a formula string into a CompiledFormula after enforcing
        the AST whitelist.

        Args:
            source: A pure-arithmetic expression. Allowed constructs:
                + - * /, parentheses, unary +/-, numeric literals, and
                bare name references that will be resolved against the
                values dict supplied to `evaluate()`.

        Returns:
            A CompiledFormula whose AST is guaranteed safe to walk.

        Raises:
            ValueError: If the source is not parseable as a Python
                expression, or if it parses but contains any disallowed
                node type. The error message names the offending node.

        Example:
            compiled = FormulaEvaluator().compile("(x + y) * 2")
        """
        # Parse in 'eval' mode: this immediately rejects statements
        # at the parser level - they raise SyntaxError before our walk
        # ever runs.
        try:
            tree = ast.parse(source, mode="eval")
        except SyntaxError as exc:
            # Re-raise as ValueError so callers have a single exception
            # type to catch for "the formula was rejected".
            raise ValueError(
                f"Formula failed to parse as an arithmetic expression: {source!r} ({exc.msg})"
            ) from exc

        # Walk every node and assert it is on the whitelist. We use
        # ast.walk so nested structures (e.g. a Call hidden inside a
        # BinOp) cannot slip through.
        for node in ast.walk(tree):
            if type(node) not in _ALLOWED_NODES:
                raise ValueError(
                    f"Disallowed syntax in formula {source!r}: "
                    f"{type(node).__name__} is not permitted. "
                    f"Allowed: arithmetic (+ - * /), parentheses, unary "
                    f"sign, numeric literals, and bare indicator-id names."
                )
            # Constant-literal type check: reject anything that is not
            # a plain int or float (rules out strings, None, bytes, etc.).
            if isinstance(node, ast.Constant):
                # Reject bool first because bool is a subclass of int.
                if isinstance(node.value, bool):
                    raise ValueError(
                        f"Disallowed literal in formula {source!r}: "
                        f"boolean constants are not permitted."
                    )
                if not isinstance(node.value, (int, float)):
                    raise ValueError(
                        f"Disallowed literal in formula {source!r}: "
                        f"only int and float constants are permitted, "
                        f"got {type(node.value).__name__}."
                    )

        return CompiledFormula(source=source, tree=tree)


# ---------------------------------------------------------------------------
# Internal evaluation helper
# ---------------------------------------------------------------------------


def _eval_node(node: ast.AST, values: dict[str, float]) -> float:
    """
    Recursively evaluate a whitelisted AST node against a values dict.

    This function is module-level rather than a method to keep
    CompiledFormula immutable and trivially re-entrant. It receives
    `values` as an argument on every call, so two concurrent threads
    walking two different trees with two different dicts do not share
    any mutable state.

    Args:
        node: An AST node previously validated by FormulaEvaluator.compile().
        values: Mapping from name to numeric value.

    Returns:
        The numeric value of the sub-expression rooted at `node`.

    Raises:
        ValueError: If a Name node references a key missing from `values`.
        AssertionError: If an unexpected node type slips through (would
            indicate a bug in the compile-time whitelist; should be
            unreachable in practice).
    """
    # Numeric literal - return its value directly. Bool/str/None were
    # rejected at compile time.
    if isinstance(node, ast.Constant):
        return float(node.value)

    # Name reference - look up in the supplied values dict only. There
    # is no fallback to globals or builtins; the whitelist forbids any
    # syntax that could reach them anyway.
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise ValueError(
                f"Formula references unknown indicator id {node.id!r}; "
                f"available ids: {sorted(values.keys())!r}."
            )
        return float(values[node.id])

    # Unary +/- - recurse on the operand, then apply the sign.
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, values)
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise AssertionError(  # pragma: no cover
            f"Unexpected unary op {type(node.op).__name__}"
        )

    # Binary +, -, *, / - recurse on both sides and apply.
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, values)
        right = _eval_node(node.right, values)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            # Numpy convention: divide-by-zero yields nan, not an
            # exception. Strategy code that triggers this should treat
            # nan as "no signal" rather than crash.
            if right == 0.0:
                return math.nan
            return left / right
        raise AssertionError(  # pragma: no cover
            f"Unexpected binary op {type(node.op).__name__}"
        )

    raise AssertionError(  # pragma: no cover
        f"Unexpected AST node {type(node).__name__} reached evaluator"
    )

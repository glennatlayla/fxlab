"""
Tests for the FXLab Strategy DSL Validator.

Verifies:
- Valid expressions parse successfully.
- Indicator argument count validation.
- Syntax error detection with line/column positions.
- Logical operators (AND, OR, NOT).
- Arithmetic operators (+, -, *, /).
- Parenthesised sub-expressions.
- Empty input handling.
- Built-in variable recognition.
- Unknown indicator warnings.

Example:
    pytest tests/unit/test_dsl_validator.py -v
"""

from __future__ import annotations

import pytest

from services.api.services.dsl_validator import (
    DslSyntaxError,
    get_builtin_variables,
    get_supported_indicators,
    tokenize,
    validate_dsl,
)

# ---------------------------------------------------------------------------
# Valid expressions
# ---------------------------------------------------------------------------


class TestValidExpressions:
    """Tests for syntactically correct DSL expressions."""

    def test_simple_indicator_comparison(self) -> None:
        """RSI(14) < 30 should be valid with RSI indicator detected."""
        result = validate_dsl("RSI(14) < 30")
        assert result.is_valid
        assert "RSI" in result.indicators_used
        assert len(result.errors) == 0

    def test_indicator_with_variable(self) -> None:
        """price > SMA(200) should detect both variable and indicator."""
        result = validate_dsl("price > SMA(200)")
        assert result.is_valid
        assert "SMA" in result.indicators_used
        assert "price" in result.variables_used

    def test_and_operator(self) -> None:
        """RSI(14) < 30 AND price > SMA(200) uses two indicators."""
        result = validate_dsl("RSI(14) < 30 AND price > SMA(200)")
        assert result.is_valid
        assert result.indicators_used == {"RSI", "SMA"}
        assert "price" in result.variables_used

    def test_or_operator(self) -> None:
        """RSI(14) > 70 OR close < EMA(50) uses OR correctly."""
        result = validate_dsl("RSI(14) > 70 OR close < EMA(50)")
        assert result.is_valid
        assert result.indicators_used == {"RSI", "EMA"}
        assert "close" in result.variables_used

    def test_not_operator(self) -> None:
        """NOT RSI(14) > 70 uses NOT prefix."""
        result = validate_dsl("NOT RSI(14) > 70")
        assert result.is_valid

    def test_parenthesised_expression(self) -> None:
        """(RSI(14) < 30) AND (price > SMA(200)) with parens."""
        result = validate_dsl("(RSI(14) < 30) AND (price > SMA(200))")
        assert result.is_valid

    def test_multi_arg_indicator_macd(self) -> None:
        """MACD(12, 26, 9) with three arguments."""
        result = validate_dsl("MACD(12, 26, 9) > 0")
        assert result.is_valid
        assert "MACD" in result.indicators_used

    def test_zero_arg_indicator_vwap(self) -> None:
        """VWAP() with no arguments."""
        result = validate_dsl("price > VWAP()")
        assert result.is_valid
        assert "VWAP" in result.indicators_used

    def test_arithmetic_operations(self) -> None:
        """price + SMA(20) > 100 uses arithmetic."""
        result = validate_dsl("price + SMA(20) > 100")
        assert result.is_valid

    def test_comparison_operators(self) -> None:
        """All comparison operators should be valid."""
        for op in ["<", ">", "<=", ">=", "==", "!="]:
            result = validate_dsl(f"RSI(14) {op} 50")
            assert result.is_valid, f"Failed for operator: {op}"

    def test_decimal_number(self) -> None:
        """RSI(14) < 30.5 with decimal literal."""
        result = validate_dsl("RSI(14) < 30.5")
        assert result.is_valid

    def test_nested_arithmetic(self) -> None:
        """SMA(20) - EMA(50) > 0 with subtraction."""
        result = validate_dsl("SMA(20) - EMA(50) > 0")
        assert result.is_valid
        assert result.indicators_used == {"SMA", "EMA"}

    def test_all_builtin_variables(self) -> None:
        """All built-in variables should be recognised."""
        for var in ("price", "open", "high", "low", "close", "volume"):
            result = validate_dsl(f"{var} > 100")
            assert result.is_valid, f"Variable '{var}' not recognized"
            assert var in result.variables_used

    def test_complex_expression(self) -> None:
        """Complex multi-condition expression."""
        expr = "(RSI(14) < 30 AND price > SMA(200)) OR (MACD(12, 26, 9) > 0 AND volume > 1000000)"
        result = validate_dsl(expr)
        assert result.is_valid
        assert result.indicators_used == {"RSI", "SMA", "MACD"}
        assert "price" in result.variables_used
        assert "volume" in result.variables_used


# ---------------------------------------------------------------------------
# Indicator argument validation
# ---------------------------------------------------------------------------


class TestIndicatorArguments:
    """Tests for indicator argument count enforcement."""

    def test_rsi_requires_one_arg(self) -> None:
        """RSI() without arguments should fail."""
        result = validate_dsl("RSI() < 30")
        assert not result.is_valid
        assert any("RSI requires 1 argument" in e.message for e in result.errors)

    def test_macd_requires_three_args(self) -> None:
        """MACD(12) with too few arguments should fail."""
        result = validate_dsl("MACD(12) > 0")
        assert not result.is_valid
        assert any("MACD requires 3 arguments" in e.message for e in result.errors)

    def test_macd_too_many_args(self) -> None:
        """MACD(12, 26, 9, 4) with too many arguments should fail."""
        result = validate_dsl("MACD(12, 26, 9, 4) > 0")
        assert not result.is_valid

    def test_vwap_no_args_valid(self) -> None:
        """VWAP() with zero arguments should be valid."""
        result = validate_dsl("VWAP() > 100")
        assert result.is_valid

    def test_vwap_with_args_invalid(self) -> None:
        """VWAP(14) with an argument should fail."""
        result = validate_dsl("VWAP(14) > 100")
        assert not result.is_valid
        assert any("VWAP requires 0 arguments" in e.message for e in result.errors)

    def test_bbands_one_or_two_args(self) -> None:
        """BBANDS accepts 1 or 2 arguments."""
        assert validate_dsl("BBANDS(20) > 0").is_valid
        assert validate_dsl("BBANDS(20, 2) > 0").is_valid
        assert not validate_dsl("BBANDS() > 0").is_valid

    def test_stoch_two_or_three_args(self) -> None:
        """STOCH accepts 2 or 3 arguments."""
        assert validate_dsl("STOCH(14, 3) > 80").is_valid
        assert validate_dsl("STOCH(14, 3, 3) > 80").is_valid
        assert not validate_dsl("STOCH(14) > 80").is_valid


# ---------------------------------------------------------------------------
# Error detection
# ---------------------------------------------------------------------------


class TestSyntaxErrors:
    """Tests for syntax error detection with positions."""

    def test_empty_expression(self) -> None:
        """Empty string should report empty expression error."""
        result = validate_dsl("")
        assert not result.is_valid
        assert any("Empty expression" in e.message for e in result.errors)

    def test_whitespace_only(self) -> None:
        """Whitespace-only input should report empty expression."""
        result = validate_dsl("   ")
        assert not result.is_valid

    def test_unknown_indicator(self) -> None:
        """Unknown function name should be flagged."""
        result = validate_dsl("FOOBAR(14) < 30")
        assert not result.is_valid
        assert any("Unknown indicator" in e.message for e in result.errors)

    def test_indicator_without_parens(self) -> None:
        """RSI without parens should suggest adding them."""
        result = validate_dsl("RSI < 30")
        assert not result.is_valid
        assert any("did you mean RSI(...)?" in e.message for e in result.errors)

    def test_unclosed_paren(self) -> None:
        """Unclosed parenthesis should be detected."""
        result = validate_dsl("(RSI(14) < 30")
        assert not result.is_valid
        assert any("RPAREN" in e.message for e in result.errors)

    def test_unexpected_character(self) -> None:
        """Special characters like @ should fail during tokenization."""
        result = validate_dsl("RSI(14) @ 30")
        assert not result.is_valid
        assert any("Unexpected character" in e.message for e in result.errors)

    def test_error_has_line_and_column(self) -> None:
        """Errors should include line and column positions."""
        result = validate_dsl("RSI() < 30")
        assert not result.is_valid
        assert result.errors[0].line >= 1
        assert result.errors[0].column >= 1

    def test_error_has_suggestion(self) -> None:
        """Argument count errors should include suggestions."""
        result = validate_dsl("RSI() < 30")
        assert not result.is_valid
        assert result.errors[0].suggestion is not None


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


class TestUtilities:
    """Tests for helper functions."""

    def test_get_supported_indicators(self) -> None:
        """get_supported_indicators returns the registry."""
        indicators = get_supported_indicators()
        assert "RSI" in indicators
        assert "MACD" in indicators
        assert indicators["RSI"] == (1, 1)
        assert indicators["MACD"] == (3, 3)

    def test_get_builtin_variables(self) -> None:
        """get_builtin_variables returns the variable list."""
        variables = get_builtin_variables()
        assert "price" in variables
        assert "close" in variables
        assert "volume" in variables

    def test_tokenize_simple(self) -> None:
        """Tokenizer produces correct token count for simple expression."""
        tokens = tokenize("RSI(14) < 30")
        # RSI, (, 14, ), <, 30, EOF = 7 tokens
        assert len(tokens) == 7

    def test_tokenize_unexpected_char_raises(self) -> None:
        """Tokenizer raises DslSyntaxError on unexpected characters."""
        with pytest.raises(DslSyntaxError):
            tokenize("RSI(14) @ 30")

"""
FXLab Strategy DSL Validator.

Responsibilities:
- Tokenize strategy condition expressions into typed tokens.
- Parse token streams to validate syntactic correctness.
- Report line/column positions for syntax errors.
- Validate indicator function names and argument counts.

Does NOT:
- Execute or evaluate conditions (runtime engine responsibility).
- Access external data (pure syntactic validation).
- Contain strategy business logic (service layer responsibility).

Dependencies:
- None (pure Python, no external dependencies).

Supported DSL grammar (EBNF):

    expression  ::= comparison (('AND' | 'OR') comparison)*
    comparison  ::= term (('<' | '>' | '<=' | '>=' | '==' | '!=') term)?
    term        ::= unary (('+' | '-') unary)*
    unary       ::= ('NOT' | '-')? primary
    primary     ::= NUMBER | IDENTIFIER | function_call | '(' expression ')'
    function_call ::= IDENTIFIER '(' (expression (',' expression)*)? ')'

Supported indicators:
    RSI(period), SMA(period), EMA(period), MACD(fast, slow, signal),
    BBANDS(period, stddev), ATR(period), STOCH(k, d, smooth),
    VWAP(), ADX(period), CCI(period), MFI(period), OBV(),
    WILLR(period), ROC(period)

Built-in variables:
    price, open, high, low, close, volume

Error conditions:
- DslSyntaxError: raised with message, line, column, and suggestion.

Example:
    result = validate_dsl("RSI(14) < 30 AND price > SMA(200)")
    assert result.is_valid
    assert result.errors == []

    result = validate_dsl("RSI() < 30")
    assert not result.is_valid
    assert "RSI requires 1 argument" in result.errors[0].message
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, auto

# ---------------------------------------------------------------------------
# Token types and lexer
# ---------------------------------------------------------------------------


class TokenType(Enum):
    """Token categories for the DSL lexer."""

    NUMBER = auto()
    IDENTIFIER = auto()
    OPERATOR = auto()  # <, >, <=, >=, ==, !=
    LOGIC = auto()  # AND, OR
    NOT = auto()  # NOT
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    """
    A single lexical token from the DSL source.

    Attributes:
        type: Token category.
        value: Raw text of the token.
        line: 1-based line number.
        column: 1-based column number.
    """

    type: TokenType
    value: str
    line: int
    column: int


# Reserved keywords mapped to token types
_KEYWORDS: dict[str, TokenType] = {
    "AND": TokenType.LOGIC,
    "OR": TokenType.LOGIC,
    "NOT": TokenType.NOT,
}

# Comparison operators (longest match first)
_OPERATORS = ["<=", ">=", "==", "!=", "<", ">"]

# Pattern for numeric literals (integers and decimals)
_NUMBER_PATTERN = re.compile(r"\d+(\.\d+)?")

# Pattern for identifiers (alphanumeric + underscores, starting with letter)
_IDENT_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def tokenize(source: str) -> list[Token]:
    """
    Tokenize a DSL condition expression into a list of tokens.

    Handles multi-line input. Whitespace is consumed but not emitted.
    The final token is always EOF.

    Args:
        source: Raw DSL condition string.

    Returns:
        List of Token objects ending with EOF.

    Raises:
        DslSyntaxError: On unexpected characters.

    Example:
        tokens = tokenize("RSI(14) < 30")
        # [Token(IDENTIFIER, "RSI"), Token(LPAREN, "("), Token(NUMBER, "14"),
        #  Token(RPAREN, ")"), Token(OPERATOR, "<"), Token(NUMBER, "30"), Token(EOF, "")]
    """
    tokens: list[Token] = []
    pos = 0
    line = 1
    col = 1

    while pos < len(source):
        ch = source[pos]

        # Newlines
        if ch == "\n":
            line += 1
            col = 1
            pos += 1
            continue

        # Whitespace
        if ch in " \t\r":
            pos += 1
            col += 1
            continue

        # Multi-char operators (<=, >=, ==, !=)
        matched_op = False
        for op in _OPERATORS:
            if source[pos : pos + len(op)] == op:
                tokens.append(Token(TokenType.OPERATOR, op, line, col))
                pos += len(op)
                col += len(op)
                matched_op = True
                break
        if matched_op:
            continue

        # Single-char tokens
        if ch == "(":
            tokens.append(Token(TokenType.LPAREN, "(", line, col))
            pos += 1
            col += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenType.RPAREN, ")", line, col))
            pos += 1
            col += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenType.COMMA, ",", line, col))
            pos += 1
            col += 1
            continue
        if ch == "+":
            tokens.append(Token(TokenType.PLUS, "+", line, col))
            pos += 1
            col += 1
            continue
        if ch == "-":
            tokens.append(Token(TokenType.MINUS, "-", line, col))
            pos += 1
            col += 1
            continue
        if ch == "*":
            tokens.append(Token(TokenType.STAR, "*", line, col))
            pos += 1
            col += 1
            continue
        if ch == "/":
            tokens.append(Token(TokenType.SLASH, "/", line, col))
            pos += 1
            col += 1
            continue

        # Number literals
        m = _NUMBER_PATTERN.match(source, pos)
        if m and (pos == 0 or not source[pos - 1].isalpha()):
            value = m.group(0)
            tokens.append(Token(TokenType.NUMBER, value, line, col))
            pos += len(value)
            col += len(value)
            continue

        # Identifiers and keywords
        m = _IDENT_PATTERN.match(source, pos)
        if m:
            value = m.group(0)
            upper_value = value.upper()
            token_type = _KEYWORDS.get(upper_value, TokenType.IDENTIFIER)
            tokens.append(Token(token_type, value, line, col))
            pos += len(value)
            col += len(value)
            continue

        # Unexpected character
        raise DslSyntaxError(
            message=f"Unexpected character: '{ch}'",
            line=line,
            column=col,
        )

    tokens.append(Token(TokenType.EOF, "", line, col))
    return tokens


# ---------------------------------------------------------------------------
# Error types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DslError:
    """
    A single DSL validation error with position and suggestion.

    Attributes:
        message: Human-readable error description.
        line: 1-based line number where the error was detected.
        column: 1-based column number.
        suggestion: Optional fix suggestion.
    """

    message: str
    line: int
    column: int
    suggestion: str | None = None


class DslSyntaxError(Exception):
    """
    Raised during DSL tokenization or parsing on syntax errors.

    Attributes:
        message: Error description.
        line: 1-based line of the error.
        column: 1-based column of the error.
        suggestion: Optional suggested fix.
    """

    def __init__(
        self,
        message: str,
        line: int = 1,
        column: int = 1,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.line = line
        self.column = column
        self.suggestion = suggestion


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DslValidationResult:
    """
    Result of DSL validation.

    Attributes:
        is_valid: True if the expression is syntactically correct.
        errors: List of DslError describing each issue found.
        indicators_used: Set of indicator function names referenced.
        variables_used: Set of built-in variable names referenced.
    """

    is_valid: bool
    errors: list[DslError] = field(default_factory=list)
    indicators_used: set[str] = field(default_factory=set)
    variables_used: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Indicator registry — name → (min_args, max_args)
# ---------------------------------------------------------------------------

SUPPORTED_INDICATORS: dict[str, tuple[int, int]] = {
    "RSI": (1, 1),
    "SMA": (1, 1),
    "EMA": (1, 1),
    "MACD": (3, 3),
    "BBANDS": (1, 2),
    "ATR": (1, 1),
    "STOCH": (2, 3),
    "VWAP": (0, 0),
    "ADX": (1, 1),
    "CCI": (1, 1),
    "MFI": (1, 1),
    "OBV": (0, 0),
    "WILLR": (1, 1),
    "ROC": (1, 1),
}

BUILTIN_VARIABLES: set[str] = {
    "price",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _Parser:
    """
    Recursive-descent parser for the FXLab DSL.

    Validates syntactic correctness and collects semantic information
    (indicators used, variables referenced) in a single pass.

    Grammar:
        expression    ::= comparison (('AND' | 'OR') comparison)*
        comparison    ::= term (('<' | '>' | '<=' | '>=' | '==' | '!=') term)?
        term          ::= unary (('+' | '-') unary)*
        unary         ::= ('NOT' | '-')? primary
        primary       ::= NUMBER | IDENTIFIER | function_call | '(' expression ')'
        function_call ::= IDENTIFIER '(' (expression (',' expression)*)? ')'
    """

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._errors: list[DslError] = []
        self._indicators: set[str] = set()
        self._variables: set[str] = set()

    @property
    def _current(self) -> Token:
        """Return the token at the current position."""
        return self._tokens[min(self._pos, len(self._tokens) - 1)]

    def _advance(self) -> Token:
        """Consume and return the current token, advancing the position."""
        tok = self._current
        if self._pos < len(self._tokens) - 1:
            self._pos += 1
        return tok

    def _match(self, *types: TokenType) -> Token | None:
        """Consume the current token if it matches any of the given types."""
        if self._current.type in types:
            return self._advance()
        return None

    def _expect(self, token_type: TokenType, context: str = "") -> Token | None:
        """
        Consume the current token if it matches; record error if not.

        Args:
            token_type: Expected token type.
            context: Additional context for the error message.

        Returns:
            The consumed token, or None if mismatch.
        """
        if self._current.type == token_type:
            return self._advance()

        msg = f"Expected {token_type.name}"
        if context:
            msg += f" {context}"
        msg += f", got '{self._current.value}'"

        self._errors.append(
            DslError(
                message=msg,
                line=self._current.line,
                column=self._current.column,
            )
        )
        return None

    def parse(self) -> DslValidationResult:
        """
        Parse the full token stream and return validation results.

        Returns:
            DslValidationResult with is_valid, errors, indicators_used, variables_used.
        """
        if self._current.type == TokenType.EOF:
            return DslValidationResult(
                is_valid=False,
                errors=[
                    DslError("Empty expression", 1, 1, "Enter a condition like 'RSI(14) < 30'")
                ],
            )

        self._parse_expression()

        if self._current.type != TokenType.EOF:
            self._errors.append(
                DslError(
                    message=f"Unexpected token '{self._current.value}' after expression",
                    line=self._current.line,
                    column=self._current.column,
                )
            )

        return DslValidationResult(
            is_valid=len(self._errors) == 0,
            errors=list(self._errors),
            indicators_used=set(self._indicators),
            variables_used=set(self._variables),
        )

    def _parse_expression(self) -> None:
        """Parse: expression ::= comparison (('AND' | 'OR') comparison)*"""
        self._parse_comparison()
        while self._current.type == TokenType.LOGIC:
            self._advance()
            self._parse_comparison()

    def _parse_comparison(self) -> None:
        """Parse: comparison ::= term (('<' | '>' | ...) term)?"""
        self._parse_term()
        if self._current.type == TokenType.OPERATOR:
            self._advance()
            self._parse_term()

    def _parse_term(self) -> None:
        """Parse: term ::= unary (('+' | '-') unary)*"""
        self._parse_unary()
        while self._current.type in (TokenType.PLUS, TokenType.MINUS):
            self._advance()
            self._parse_unary()

    def _parse_unary(self) -> None:
        """Parse: unary ::= ('NOT' | '-')? primary"""
        if self._current.type in (TokenType.NOT, TokenType.MINUS):
            self._advance()
        self._parse_primary()

    def _parse_primary(self) -> None:
        """
        Parse: primary ::= NUMBER | IDENTIFIER | function_call | '(' expression ')'

        Differentiates between plain identifiers (variables) and function
        calls (identifiers followed by '(').
        """
        # Number literal
        if self._match(TokenType.NUMBER):
            return

        # Parenthesized expression
        if self._match(TokenType.LPAREN):
            self._parse_expression()
            self._expect(TokenType.RPAREN, "to close '('")
            return

        # Identifier or function call
        if self._current.type == TokenType.IDENTIFIER:
            ident_token = self._advance()
            name = ident_token.value
            upper_name = name.upper()

            # Function call: IDENTIFIER '(' args ')'
            if self._current.type == TokenType.LPAREN:
                self._advance()  # consume '('
                args_count = 0

                if self._current.type != TokenType.RPAREN:
                    self._parse_expression()
                    args_count = 1
                    while self._match(TokenType.COMMA):
                        self._parse_expression()
                        args_count += 1

                self._expect(TokenType.RPAREN, f"to close {name}()")

                # Validate indicator
                if upper_name in SUPPORTED_INDICATORS:
                    self._indicators.add(upper_name)
                    min_args, max_args = SUPPORTED_INDICATORS[upper_name]
                    if args_count < min_args or args_count > max_args:
                        if min_args == max_args:
                            expected = f"{min_args} argument{'s' if min_args != 1 else ''}"
                        else:
                            expected = f"{min_args}-{max_args} arguments"
                        self._errors.append(
                            DslError(
                                message=f"{upper_name} requires {expected}, got {args_count}",
                                line=ident_token.line,
                                column=ident_token.column,
                                suggestion=f"Use {upper_name}({', '.join(['<value>'] * min_args)})",
                            )
                        )
                else:
                    # Unknown function — warn but don't block (could be user-defined)
                    self._errors.append(
                        DslError(
                            message=f"Unknown indicator function '{name}'",
                            line=ident_token.line,
                            column=ident_token.column,
                            suggestion=f"Supported indicators: {', '.join(sorted(SUPPORTED_INDICATORS))}",
                        )
                    )
                return

            # Plain identifier — treat as variable reference
            if name.lower() in BUILTIN_VARIABLES:
                self._variables.add(name.lower())
            elif upper_name in SUPPORTED_INDICATORS:
                # User wrote indicator name without parentheses
                self._errors.append(
                    DslError(
                        message=f"'{name}' is an indicator — did you mean {upper_name}(...)?",
                        line=ident_token.line,
                        column=ident_token.column,
                        suggestion=f"Add parentheses: {upper_name}(14)",
                    )
                )
            else:
                # Unknown variable — could be a custom parameter, allow it
                self._variables.add(name)
            return

        # Nothing matched — report error
        tok = self._current
        suggestion = None
        if tok.type == TokenType.EOF:
            suggestion = "Complete the expression"
        elif tok.type == TokenType.LOGIC:
            suggestion = "Add a condition before the logical operator"

        self._errors.append(
            DslError(
                message=f"Unexpected token '{tok.value}'",
                line=tok.line,
                column=tok.column,
                suggestion=suggestion,
            )
        )
        # Consume the bad token to avoid infinite loops
        self._advance()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_dsl(source: str) -> DslValidationResult:
    """
    Validate a FXLab strategy DSL expression.

    Performs lexical analysis (tokenization) and syntactic parsing.
    Returns structured validation results with error positions and
    suggestions.

    Args:
        source: Raw DSL condition string, e.g. "RSI(14) < 30 AND price > SMA(200)".

    Returns:
        DslValidationResult with is_valid flag, errors list,
        and sets of indicators and variables used.

    Example:
        result = validate_dsl("RSI(14) < 30 AND price > SMA(200)")
        assert result.is_valid
        assert "RSI" in result.indicators_used
        assert "price" in result.variables_used

        result = validate_dsl("RSI() < 30")
        assert not result.is_valid
        assert len(result.errors) == 1
    """
    if not source or not source.strip():
        return DslValidationResult(
            is_valid=False,
            errors=[DslError("Empty expression", 1, 1, "Enter a condition like 'RSI(14) < 30'")],
        )

    try:
        tokens = tokenize(source.strip())
    except DslSyntaxError as e:
        return DslValidationResult(
            is_valid=False,
            errors=[DslError(str(e), e.line, e.column, e.suggestion)],
        )

    parser = _Parser(tokens)
    return parser.parse()


def get_supported_indicators() -> dict[str, tuple[int, int]]:
    """
    Return the registry of supported indicator functions.

    Returns:
        Dict mapping indicator name to (min_args, max_args) tuple.

    Example:
        indicators = get_supported_indicators()
        assert indicators["RSI"] == (1, 1)
        assert indicators["MACD"] == (3, 3)
    """
    return dict(SUPPORTED_INDICATORS)


def get_builtin_variables() -> Sequence[str]:
    """
    Return the list of built-in variable names.

    Returns:
        Sorted list of built-in variable names (price, open, high, low, close, volume).

    Example:
        vars = get_builtin_variables()
        assert "price" in vars
    """
    return sorted(BUILTIN_VARIABLES)

"""
Unit tests for services/api/_validation.py helpers.

Covers:
- require_uri: URI scheme validation, path component enforcement
- require_min_length: String length constraints
- require_max_length: String length constraints
- require_non_empty: Empty string rejection
- require_ulid: ULID format validation
- require_pattern: Regex pattern matching
- require_ge, require_le: Numeric constraints

Test naming convention:
    test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.exceptions import HTTPException

from services.api._validation import (
    require_ge,
    require_le,
    require_max_length,
    require_min_length,
    require_non_empty,
    require_pattern,
    require_ulid,
    require_uri,
)

# ---------------------------------------------------------------------------
# require_uri — URI validation with path component enforcement
# (M14-T9 Gap 8: Evidence link validation)
# ---------------------------------------------------------------------------


class TestRequireUri:
    """Tests for require_uri (SOC 2 Evidence of Review validation)."""

    def test_require_uri_accepts_valid_jira_url(self) -> None:
        """
        A valid Jira ticket URL with non-root path is accepted.
        """
        require_uri(
            "https://jira.example.com/browse/FX-001",
            field="evidence_link",
        )
        # If no exception is raised, the test passes.

    def test_require_uri_accepts_valid_confluence_url(self) -> None:
        """
        A valid Confluence page URL with non-root path is accepted.
        """
        require_uri(
            "https://confluence.example.com/display/PROJ/Design-Doc",
            field="evidence_link",
        )

    def test_require_uri_accepts_http_scheme(self) -> None:
        """
        HTTP (not just HTTPS) is accepted if in the schemes tuple.
        """
        require_uri(
            "http://jira.example.com/browse/FX-123",
            field="evidence_link",
        )

    def test_require_uri_rejects_bare_domain_without_slash(self) -> None:
        """
        Gap 8: Bare domain without any path component is rejected.
        https://example.com (no trailing slash) must be rejected.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_uri(
                "https://example.com",
                field="evidence_link",
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "specific resource path" in exc_info.value.detail

    def test_require_uri_rejects_bare_domain_with_root_slash(self) -> None:
        """
        Gap 8: Root path only (https://example.com/) is rejected.
        The path component after stripping trailing slashes is empty.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_uri(
                "https://example.com/",
                field="evidence_link",
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "specific resource path" in exc_info.value.detail

    def test_require_uri_accepts_path_with_single_segment(self) -> None:
        """
        A path with a single segment (e.g., /doc) is accepted.
        """
        require_uri(
            "https://example.com/doc",
            field="evidence_link",
        )

    def test_require_uri_accepts_path_with_multiple_segments(self) -> None:
        """
        A path with multiple segments (e.g., /doc/123) is accepted.
        """
        require_uri(
            "https://example.com/doc/123",
            field="evidence_link",
        )

    def test_require_uri_rejects_non_http_scheme(self) -> None:
        """
        Non-HTTP/HTTPS schemes (e.g., ftp://) are rejected.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_uri(
                "ftp://example.com/file",
                field="evidence_link",
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "scheme" in exc_info.value.detail

    def test_require_uri_rejects_empty_value(self) -> None:
        """
        An empty string is rejected.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_uri(
                "",
                field="evidence_link",
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "required" in exc_info.value.detail.lower()

    def test_require_uri_respects_custom_schemes(self) -> None:
        """
        Only schemes in the allowed tuple are accepted.
        """
        # Should accept https when in the tuple
        require_uri(
            "https://example.com/doc",
            field="evidence_link",
            schemes=("https",),
        )

        # Should reject http when not in the tuple
        with pytest.raises(HTTPException):
            require_uri(
                "http://example.com/doc",
                field="evidence_link",
                schemes=("https",),
            )

    def test_require_uri_path_with_query_string(self) -> None:
        """
        A path with query parameters is accepted (query string doesn't affect path).
        """
        require_uri(
            "https://example.com/search?q=test",
            field="evidence_link",
        )

    def test_require_uri_path_with_fragment(self) -> None:
        """
        A path with a fragment is accepted (fragment doesn't affect path).
        """
        require_uri(
            "https://example.com/doc#section1",
            field="evidence_link",
        )


# ---------------------------------------------------------------------------
# require_min_length — Minimum string length constraint
# ---------------------------------------------------------------------------


class TestRequireMinLength:
    """Tests for require_min_length."""

    def test_require_min_length_accepts_valid_length(self) -> None:
        """
        A string with length >= min_len is accepted.
        """
        require_min_length(
            "This is a valid rationale with sufficient length.",
            field="rationale",
            min_len=20,
        )

    def test_require_min_length_accepts_exact_length(self) -> None:
        """
        A string with length == min_len is accepted.
        """
        require_min_length(
            "12345678901234567890",  # exactly 20 chars
            field="test_field",
            min_len=20,
        )

    def test_require_min_length_rejects_too_short(self) -> None:
        """
        A string with length < min_len is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_min_length(
                "Too short.",
                field="rationale",
                min_len=20,
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "at least" in exc_info.value.detail


# ---------------------------------------------------------------------------
# require_max_length — Maximum string length constraint
# ---------------------------------------------------------------------------


class TestRequireMaxLength:
    """Tests for require_max_length."""

    def test_require_max_length_accepts_valid_length(self) -> None:
        """
        A string with length <= max_len is accepted.
        """
        require_max_length(
            "Short text",
            field="name",
            max_len=255,
        )

    def test_require_max_length_accepts_exact_length(self) -> None:
        """
        A string with length == max_len is accepted.
        """
        require_max_length(
            "12345",
            field="test_field",
            max_len=5,
        )

    def test_require_max_length_rejects_too_long(self) -> None:
        """
        A string with length > max_len is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_max_length(
                "This string is definitely too long.",
                field="name",
                max_len=10,
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "at most" in exc_info.value.detail


# ---------------------------------------------------------------------------
# require_non_empty — Non-empty string validation
# ---------------------------------------------------------------------------


class TestRequireNonEmpty:
    """Tests for require_non_empty."""

    def test_require_non_empty_accepts_non_empty_string(self) -> None:
        """
        A non-empty string is accepted.
        """
        require_non_empty(
            "Valid content",
            field="name",
        )

    def test_require_non_empty_rejects_empty_string(self) -> None:
        """
        An empty string is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_non_empty("", field="name")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "required" in exc_info.value.detail.lower()

    def test_require_non_empty_rejects_whitespace_only(self) -> None:
        """
        A whitespace-only string is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_non_empty("   ", field="name")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_require_non_empty_rejects_none(self) -> None:
        """
        None is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_non_empty(None, field="name")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# require_ulid — ULID format validation
# ---------------------------------------------------------------------------


class TestRequireUlid:
    """Tests for require_ulid."""

    def test_require_ulid_accepts_valid_ulid(self) -> None:
        """
        A valid 26-character Crockford Base32 ULID is accepted.
        """
        require_ulid(
            "01HABCDEF00000000000000099",
            field="user_id",
        )

    def test_require_ulid_accepts_lowercase(self) -> None:
        """
        Lowercase ULIDs are accepted (case-insensitive).
        """
        require_ulid(
            "01habcdef00000000000000099",
            field="user_id",
        )

    def test_require_ulid_rejects_invalid_alphabet(self) -> None:
        """
        Characters not in the Crockford Base32 alphabet are rejected.
        I and U are forbidden in Crockford Base32.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_ulid(
                "01HABCDEF0000000000000000I",  # I is not in the alphabet
                field="user_id",
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_require_ulid_rejects_wrong_length(self) -> None:
        """
        A string that is not 26 characters is rejected.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_ulid(
                "01HABCDEF000000000000",  # 21 chars instead of 26
                field="user_id",
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# require_pattern — Regex pattern matching
# ---------------------------------------------------------------------------


class TestRequirePattern:
    """Tests for require_pattern."""

    def test_require_pattern_accepts_matching_string(self) -> None:
        """
        A string matching the pattern is accepted.
        """
        require_pattern(
            "1.2.3",
            field="version",
            pattern=r"^\d+\.\d+\.\d+$",
            description="semantic version",
        )

    def test_require_pattern_rejects_non_matching_string(self) -> None:
        """
        A string not matching the pattern is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_pattern(
                "1.2",
                field="version",
                pattern=r"^\d+\.\d+\.\d+$",
                description="semantic version",
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# require_ge — Greater-than-or-equal numeric constraint
# ---------------------------------------------------------------------------


class TestRequireGe:
    """Tests for require_ge."""

    def test_require_ge_accepts_equal_value(self) -> None:
        """
        A value equal to the minimum is accepted.
        """
        require_ge(
            10,
            field="page_size",
            minimum=10,
        )

    def test_require_ge_accepts_greater_value(self) -> None:
        """
        A value greater than the minimum is accepted.
        """
        require_ge(
            20,
            field="page_size",
            minimum=10,
        )

    def test_require_ge_rejects_lesser_value(self) -> None:
        """
        A value less than the minimum is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_ge(
                5,
                field="page_size",
                minimum=10,
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "≥" in exc_info.value.detail or ">=" in exc_info.value.detail


# ---------------------------------------------------------------------------
# require_le — Less-than-or-equal numeric constraint
# ---------------------------------------------------------------------------


class TestRequireLe:
    """Tests for require_le."""

    def test_require_le_accepts_equal_value(self) -> None:
        """
        A value equal to the maximum is accepted.
        """
        require_le(
            100,
            field="page_size",
            maximum=100,
        )

    def test_require_le_accepts_lesser_value(self) -> None:
        """
        A value less than the maximum is accepted.
        """
        require_le(
            50,
            field="page_size",
            maximum=100,
        )

    def test_require_le_rejects_greater_value(self) -> None:
        """
        A value greater than the maximum is rejected with 422.
        """
        with pytest.raises(HTTPException) as exc_info:
            require_le(
                150,
                field="page_size",
                maximum=100,
            )
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "≤" in exc_info.value.detail or "<=" in exc_info.value.detail

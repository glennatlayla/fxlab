"""
Unit tests for libs.strategy_ir.oanda_creds.

Scope:
    Verify the config-only Oanda credential surface:

        * load_oanda_creds_from_env happy path with all three vars set.
        * Missing OANDA_API_TOKEN raises with that var name in the
          message.
        * Missing OANDA_ACCOUNT_ID raises with that var name in the
          message.
        * Missing both vars raises listing both.
        * OANDA_ENVIRONMENT defaults to fxpractice when unset.
        * OANDA_ENVIRONMENT must be one of the supported literals.
        * verify_oanda_creds_format accepts well-formed inputs.
        * verify_oanda_creds_format rejects too-short tokens.
        * verify_oanda_creds_format rejects malformed account_id.
        * verify_oanda_creds_format rejects bad token characters.
        * Whitespace in env vars is trimmed (paste-error tolerance).
        * OandaCreds is frozen (mutation forbidden).
"""

from __future__ import annotations

import pytest

from libs.strategy_ir.oanda_creds import (
    ENV_ACCOUNT_ID,
    ENV_API_TOKEN,
    ENV_ENVIRONMENT,
    OandaCreds,
    OandaCredsMissingError,
    load_oanda_creds_from_env,
    verify_oanda_creds_format,
)

# A token that satisfies the format check (≥30 chars, alphanumeric+`-`).
_VALID_TOKEN = "abcdef0123456789-abcdef0123456789-abcdef"
_VALID_ACCOUNT = "001-002-1234567-001"


# ---------------------------------------------------------------------------
# load_oanda_creds_from_env -- happy path
# ---------------------------------------------------------------------------


def test_load_oanda_creds_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three vars set => populated OandaCreds returned."""
    monkeypatch.setenv(ENV_API_TOKEN, _VALID_TOKEN)
    monkeypatch.setenv(ENV_ACCOUNT_ID, _VALID_ACCOUNT)
    monkeypatch.setenv(ENV_ENVIRONMENT, "fxtrade")

    creds = load_oanda_creds_from_env()
    assert isinstance(creds, OandaCreds)
    assert creds.api_token == _VALID_TOKEN
    assert creds.account_id == _VALID_ACCOUNT
    assert creds.environment == "fxtrade"


def test_load_oanda_creds_defaults_environment_to_fxpractice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset OANDA_ENVIRONMENT defaults to fxpractice."""
    monkeypatch.setenv(ENV_API_TOKEN, _VALID_TOKEN)
    monkeypatch.setenv(ENV_ACCOUNT_ID, _VALID_ACCOUNT)
    monkeypatch.delenv(ENV_ENVIRONMENT, raising=False)

    creds = load_oanda_creds_from_env()
    assert creds.environment == "fxpractice"


def test_load_oanda_creds_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leading/trailing whitespace in env vars is trimmed."""
    monkeypatch.setenv(ENV_API_TOKEN, f"  {_VALID_TOKEN}\n")
    monkeypatch.setenv(ENV_ACCOUNT_ID, f"\t{_VALID_ACCOUNT}  ")
    monkeypatch.setenv(ENV_ENVIRONMENT, " fxpractice ")

    creds = load_oanda_creds_from_env()
    assert creds.api_token == _VALID_TOKEN
    assert creds.account_id == _VALID_ACCOUNT
    assert creds.environment == "fxpractice"


# ---------------------------------------------------------------------------
# load_oanda_creds_from_env -- missing vars
# ---------------------------------------------------------------------------


def test_load_oanda_creds_missing_api_token_raises_named_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing OANDA_API_TOKEN must name that variable in the message."""
    monkeypatch.delenv(ENV_API_TOKEN, raising=False)
    monkeypatch.setenv(ENV_ACCOUNT_ID, _VALID_ACCOUNT)

    with pytest.raises(OandaCredsMissingError) as exc_info:
        load_oanda_creds_from_env()
    assert ENV_API_TOKEN in str(exc_info.value)


def test_load_oanda_creds_blank_api_token_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank-string token is treated as missing."""
    monkeypatch.setenv(ENV_API_TOKEN, "   ")
    monkeypatch.setenv(ENV_ACCOUNT_ID, _VALID_ACCOUNT)

    with pytest.raises(OandaCredsMissingError) as exc_info:
        load_oanda_creds_from_env()
    assert ENV_API_TOKEN in str(exc_info.value)


def test_load_oanda_creds_missing_account_id_raises_named_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing OANDA_ACCOUNT_ID must name that variable in the message."""
    monkeypatch.setenv(ENV_API_TOKEN, _VALID_TOKEN)
    monkeypatch.delenv(ENV_ACCOUNT_ID, raising=False)

    with pytest.raises(OandaCredsMissingError) as exc_info:
        load_oanda_creds_from_env()
    assert ENV_ACCOUNT_ID in str(exc_info.value)


def test_load_oanda_creds_missing_both_lists_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both required vars are missing, both names appear in the message."""
    monkeypatch.delenv(ENV_API_TOKEN, raising=False)
    monkeypatch.delenv(ENV_ACCOUNT_ID, raising=False)

    with pytest.raises(OandaCredsMissingError) as exc_info:
        load_oanda_creds_from_env()
    msg = str(exc_info.value)
    assert ENV_API_TOKEN in msg
    assert ENV_ACCOUNT_ID in msg


# ---------------------------------------------------------------------------
# OANDA_ENVIRONMENT validation
# ---------------------------------------------------------------------------


def test_load_oanda_creds_rejects_unsupported_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unsupported OANDA_ENVIRONMENT string raises OandaCredsMissingError."""
    monkeypatch.setenv(ENV_API_TOKEN, _VALID_TOKEN)
    monkeypatch.setenv(ENV_ACCOUNT_ID, _VALID_ACCOUNT)
    monkeypatch.setenv(ENV_ENVIRONMENT, "production")

    with pytest.raises(OandaCredsMissingError) as exc_info:
        load_oanda_creds_from_env()
    assert ENV_ENVIRONMENT in str(exc_info.value)


# ---------------------------------------------------------------------------
# verify_oanda_creds_format
# ---------------------------------------------------------------------------


def test_verify_oanda_creds_format_accepts_well_formed_inputs() -> None:
    """A well-formed OandaCreds passes the format check silently."""
    creds = OandaCreds(
        api_token=_VALID_TOKEN,
        account_id=_VALID_ACCOUNT,
        environment="fxpractice",
    )
    # Must not raise.
    verify_oanda_creds_format(creds)


def test_verify_oanda_creds_format_rejects_too_short_token() -> None:
    """A token shorter than 30 characters is rejected with a useful message."""
    short_token = "short-token-123"  # 15 chars
    creds = OandaCreds(
        api_token=short_token,
        account_id=_VALID_ACCOUNT,
        environment="fxpractice",
    )
    with pytest.raises(OandaCredsMissingError) as exc_info:
        verify_oanda_creds_format(creds)
    assert ENV_API_TOKEN in str(exc_info.value)


def test_verify_oanda_creds_format_rejects_token_with_bad_characters() -> None:
    """A token with characters outside [A-Za-z0-9-] is rejected."""
    # Long enough to pass length, but contains a space.
    bad_token = "abcdef0123456789 abcdef0123456789-abcdef"
    creds = OandaCreds(
        api_token=bad_token,
        account_id=_VALID_ACCOUNT,
        environment="fxpractice",
    )
    with pytest.raises(OandaCredsMissingError) as exc_info:
        verify_oanda_creds_format(creds)
    assert ENV_API_TOKEN in str(exc_info.value)


def test_verify_oanda_creds_format_rejects_malformed_account_id() -> None:
    """An account ID that is not NNN-NNN-NNNNNNN-NNN is rejected."""
    creds = OandaCreds(
        api_token=_VALID_TOKEN,
        account_id="not-a-valid-account",
        environment="fxpractice",
    )
    with pytest.raises(OandaCredsMissingError) as exc_info:
        verify_oanda_creds_format(creds)
    assert ENV_ACCOUNT_ID in str(exc_info.value)


def test_verify_oanda_creds_format_rejects_account_id_with_three_groups() -> None:
    """Account ID with too few dash-separated groups is rejected."""
    creds = OandaCreds(
        api_token=_VALID_TOKEN,
        account_id="001-002-1234567",  # only 3 groups
        environment="fxpractice",
    )
    with pytest.raises(OandaCredsMissingError):
        verify_oanda_creds_format(creds)


# ---------------------------------------------------------------------------
# OandaCreds frozen / extra=forbid
# ---------------------------------------------------------------------------


def test_oanda_creds_is_frozen() -> None:
    """OandaCreds must be immutable after construction."""
    creds = OandaCreds(
        api_token=_VALID_TOKEN,
        account_id=_VALID_ACCOUNT,
        environment="fxpractice",
    )
    with pytest.raises(Exception):  # pydantic ValidationError
        creds.api_token = "mutated"  # type: ignore[misc]


def test_oanda_creds_rejects_extra_fields() -> None:
    """Unknown fields must be rejected at construction (extra='forbid')."""
    with pytest.raises(Exception):  # pydantic ValidationError
        OandaCreds(
            api_token=_VALID_TOKEN,
            account_id=_VALID_ACCOUNT,
            environment="fxpractice",
            extra_unknown_field="should-fail",  # type: ignore[call-arg]
        )

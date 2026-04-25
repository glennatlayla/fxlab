"""
Oanda credential surface (M4.E1 prep — config-only, no HTTP).

==============================================================================
M4.E1 SWAP POINT -- READ THIS BEFORE EXTENDING
==============================================================================

This module is the **config-only** half of Track E milestone M4.E1
(verify Oanda credentials and account reachability).

It exists today so that:

    *   The expected environment-variable contract for Oanda
        (OANDA_API_TOKEN, OANDA_ACCOUNT_ID, OANDA_ENVIRONMENT) is
        codified, typed, and tested. The moment the operator finishes
        Oanda signup and writes the values into ``.env``, every
        downstream call site can ``load_oanda_creds_from_env()`` and
        get either a frozen :class:`OandaCreds` or a typed
        :class:`OandaCredsMissingError` with a useful message.

    *   The format of the credentials can be sanity-checked before any
        network call is attempted (catches paste errors, leading/
        trailing whitespace, account-ID typos).

Once M4.E1 is fully landed (when creds and network are available), the
following swap is purely additive:

    1.  Add a new function ``verify_oanda_account_reachable(creds:
        OandaCreds) -> None`` to this module that issues a
        ``GET /v3/accounts/{account_id}`` call against the Oanda v20
        REST endpoint corresponding to ``creds.environment``. The
        function MUST:

            *   Time out fast (≤ 5 s) so a misconfigured environment
                does not block app start.
            *   Translate 401 / 403 into :class:`OandaCredsMissingError`
                (with the message clearly distinguishing "credentials
                rejected" from "credentials missing").
            *   Translate transient failure into a TransientError
                (so retry policy in the caller can take over).

    2.  Wire :func:`verify_oanda_creds_format` and the new
        ``verify_oanda_account_reachable`` together at app start so
        the bootstrap path either confirms reachability or refuses to
        come up. This module's existing public API is unchanged.

==============================================================================

Responsibilities:
    - Define :class:`OandaCreds`, an immutable Pydantic v2 value
      object holding the three fields every Oanda v20 caller needs.
    - Define :class:`OandaCredsMissingError`, a typed exception used
      everywhere Oanda credentials are required but absent or
      malformed.
    - Provide :func:`load_oanda_creds_from_env`, which reads the three
      environment variables and returns a populated
      :class:`OandaCreds` (or raises a useful error).
    - Provide :func:`verify_oanda_creds_format`, a network-free sanity
      check on token shape and account-ID format.

Does NOT:
    - Make any HTTP call. Network reachability is an M4.E1 follow-up
      documented in the swap point banner above.
    - Read or write the ``.env`` file -- it consumes
      :func:`os.environ` only, so the operator's chosen secret loader
      (direnv, docker compose, systemd EnvironmentFile) is honoured.
    - Persist or cache the credentials. Each caller gets a fresh,
      frozen value object.

Dependencies:
    - Pydantic v2 (BaseModel, ConfigDict, Field, field_validator).
    - Standard library only (os, re, typing).

Example::

    from libs.strategy_ir.oanda_creds import (
        OandaCredsMissingError,
        load_oanda_creds_from_env,
        verify_oanda_creds_format,
    )

    try:
        creds = load_oanda_creds_from_env()
        verify_oanda_creds_format(creds)
    except OandaCredsMissingError as exc:
        log.error("oanda creds unusable", error=str(exc))
        raise
"""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Public typed exception
# ---------------------------------------------------------------------------


class OandaCredsMissingError(Exception):
    """
    Raised when Oanda credentials are missing, blank, or malformed.

    Used by:
        - :func:`load_oanda_creds_from_env` when one or more env vars
          are unset or empty.
        - :func:`verify_oanda_creds_format` when a credential is
          present but does not look like a real Oanda value.
        - :class:`libs.strategy_ir.interfaces.market_data_provider_interface.OandaMarketDataProvider`
          and
          :class:`libs.strategy_ir.interfaces.broker_adapter_interface.OandaBrokerAdapter`
          when constructed without a working Oanda v20 client.

    The message must always name the specific problem (which variable,
    which validation) so the operator can fix it without reading the
    code.
    """


# ---------------------------------------------------------------------------
# Environment-variable names (single source of truth)
# ---------------------------------------------------------------------------

#: Environment variable holding the personal-access API token issued by
#: Oanda's developer portal. Required.
ENV_API_TOKEN = "OANDA_API_TOKEN"

#: Environment variable holding the Oanda account ID
#: (format ``NNN-NNN-NNNNNNN-NNN``). Required.
ENV_ACCOUNT_ID = "OANDA_ACCOUNT_ID"

#: Environment variable selecting the Oanda v20 environment. Optional
#: (defaults to ``fxpractice`` so an unconfigured deployment cannot
#: accidentally route orders to a live account).
ENV_ENVIRONMENT = "OANDA_ENVIRONMENT"

#: Default Oanda environment when :data:`ENV_ENVIRONMENT` is unset.
DEFAULT_ENVIRONMENT: Literal["fxpractice", "fxtrade"] = "fxpractice"

# ---------------------------------------------------------------------------
# Format constants used by verify_oanda_creds_format
# ---------------------------------------------------------------------------

#: Minimum number of characters in a real Oanda personal-access token.
#: The official tokens are 65 hexadecimal-with-dash strings, but we
#: accept anything ≥ 30 to leave room for future format changes; the
#: real reachability check (M4.E1 follow-up) is the authoritative
#: rejection point.
_MIN_TOKEN_LENGTH = 30

#: Characters allowed in an Oanda personal-access token. The real token
#: is hex; we allow alphanumeric + ``-`` to stay forward-compatible.
_TOKEN_CHARSET_RE = re.compile(r"^[A-Za-z0-9-]+$")

#: Account ID format published by Oanda: four dash-separated digit
#: groups, e.g. ``001-002-1234567-001``. Strict to catch paste errors.
_ACCOUNT_ID_RE = re.compile(r"^\d+-\d+-\d+-\d+$")


# ---------------------------------------------------------------------------
# Public value object
# ---------------------------------------------------------------------------


class OandaCreds(BaseModel):
    """
    Immutable, validated bundle of Oanda v20 credentials.

    Attributes:
        api_token: Personal-access token issued by Oanda. Treated as a
            secret -- never logged.
        account_id: Oanda account identifier (``NNN-NNN-NNNNNNN-NNN``).
            Safe to log because it is not sufficient to authenticate.
        environment: Either ``"fxpractice"`` (Oanda demo / paper) or
            ``"fxtrade"`` (Oanda live). Determines which v20 host the
            adapter calls.

    Why frozen and extra='forbid':
        - frozen: credentials must never be mutated in-place; any
          rotation produces a new value object so audit logs cleanly
          show the moment of change.
        - extra='forbid': catches typos at config-load time
          (``OANDA_TOKN`` would otherwise be silently ignored).

    Example::

        creds = OandaCreds(
            api_token="abc123-...-xyz",
            account_id="001-002-1234567-001",
            environment="fxpractice",
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_token: str = Field(
        ...,
        min_length=1,
        description="Oanda personal-access API token (treat as secret; never log).",
    )
    account_id: str = Field(
        ...,
        min_length=1,
        description="Oanda account ID, format NNN-NNN-NNNNNNN-NNN.",
    )
    environment: Literal["fxpractice", "fxtrade"] = Field(
        default=DEFAULT_ENVIRONMENT,
        description="Oanda v20 environment; selects fxpractice (demo) or fxtrade (live).",
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_oanda_creds_from_env() -> OandaCreds:
    """
    Read Oanda credentials from the process environment.

    Returns:
        Populated, frozen :class:`OandaCreds`.

    Raises:
        OandaCredsMissingError: If any required variable
            (:data:`ENV_API_TOKEN`, :data:`ENV_ACCOUNT_ID`) is unset
            or blank. The exception message names every missing
            variable so the operator can fix them in one pass.
        OandaCredsMissingError: If :data:`ENV_ENVIRONMENT` is set to a
            value other than ``"fxpractice"`` or ``"fxtrade"``. We
            translate Pydantic's ValidationError into the typed
            project exception so callers only need to catch one type.

    Example::

        os.environ["OANDA_API_TOKEN"] = "abc-...-xyz"
        os.environ["OANDA_ACCOUNT_ID"] = "001-002-1234567-001"
        creds = load_oanda_creds_from_env()
        # creds.environment == "fxpractice"
    """
    # Resolve raw values once; .strip() catches the common copy-paste
    # mistake of trailing whitespace / newline in a .env entry.
    raw_token = os.environ.get(ENV_API_TOKEN, "").strip()
    raw_account = os.environ.get(ENV_ACCOUNT_ID, "").strip()
    raw_env = os.environ.get(ENV_ENVIRONMENT, "").strip()

    # Collect every missing required variable in one pass so the
    # operator can fix them all at once instead of running, fixing,
    # re-running.
    missing: list[str] = []
    if not raw_token:
        missing.append(ENV_API_TOKEN)
    if not raw_account:
        missing.append(ENV_ACCOUNT_ID)
    if missing:
        raise OandaCredsMissingError(
            "Required Oanda environment variable(s) missing or blank: "
            + ", ".join(missing)
            + ". Populate them in .env (see CLAUDE.md §17 for which file owns secrets)."
        )

    # Default the environment when unset; the Pydantic Literal will
    # reject any non-default unsupported value below.
    environment_value: str = raw_env or DEFAULT_ENVIRONMENT

    try:
        return OandaCreds(
            api_token=raw_token,
            account_id=raw_account,
            environment=environment_value,  # type: ignore[arg-type]
        )
    except Exception as exc:
        # Pydantic ValidationError shows up here when environment is
        # an unsupported literal. Re-raise as the project-typed error
        # so callers only have to handle one exception class.
        raise OandaCredsMissingError(
            f"{ENV_ENVIRONMENT} must be 'fxpractice' or 'fxtrade'; "
            f"got {environment_value!r}. Underlying error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Format-only verifier (no HTTP)
# ---------------------------------------------------------------------------


def verify_oanda_creds_format(creds: OandaCreds) -> None:
    """
    Sanity-check the format of :class:`OandaCreds` without any I/O.

    M4.E1 stub -- replace with a real ``GET /v3/accounts/{id}`` ping
    once the operator's Oanda credentials and network reachability
    are available. The function is a defence-in-depth check today so
    obvious paste errors fail fast at process boot rather than at the
    first market-data fetch.

    Args:
        creds: The credentials to validate.

    Raises:
        OandaCredsMissingError: If the API token is shorter than
            :data:`_MIN_TOKEN_LENGTH` characters, contains characters
            outside ``[A-Za-z0-9-]``, or the account ID does not match
            ``NNN-NNN-NNNNNNN-NNN``.

    Example::

        creds = load_oanda_creds_from_env()
        verify_oanda_creds_format(creds)
        # No exception => credentials look plausible enough to try
        # making an HTTP call against (which the M4.E1 follow-up will
        # actually do).
    """
    # Token length check first; a short value almost always means the
    # operator pasted a fragment of the token instead of the whole
    # thing.
    if len(creds.api_token) < _MIN_TOKEN_LENGTH:
        raise OandaCredsMissingError(
            f"{ENV_API_TOKEN} must be at least {_MIN_TOKEN_LENGTH} characters; "
            f"got {len(creds.api_token)}. Re-copy the token from the Oanda "
            "developer portal and ensure no characters were truncated."
        )

    # Charset check after length so the message order matches what
    # the operator is most likely to have done wrong.
    if not _TOKEN_CHARSET_RE.match(creds.api_token):
        raise OandaCredsMissingError(
            f"{ENV_API_TOKEN} contains characters outside [A-Za-z0-9-]. "
            "Check for stray whitespace, quotes, or accidental newlines."
        )

    # Account ID has a strict published format; failing this almost
    # always means the operator pasted the wrong field from the Oanda
    # account portal (e.g. the username instead of the ID).
    if not _ACCOUNT_ID_RE.match(creds.account_id):
        raise OandaCredsMissingError(
            f"{ENV_ACCOUNT_ID} must match the format NNN-NNN-NNNNNNN-NNN "
            f"(four dash-separated digit groups); got {creds.account_id!r}."
        )


__all__ = [
    "DEFAULT_ENVIRONMENT",
    "ENV_ACCOUNT_ID",
    "ENV_API_TOKEN",
    "ENV_ENVIRONMENT",
    "OandaCreds",
    "OandaCredsMissingError",
    "load_oanda_creds_from_env",
    "verify_oanda_creds_format",
]

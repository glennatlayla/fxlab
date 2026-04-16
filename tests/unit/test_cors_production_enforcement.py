"""
Unit tests for C2 — CORS plaintext / LAN rejection in production (2026-04-15).

Context
-------
The minitux install log showed ``CORS_ALLOWED_ORIGINS`` resolved to
``http://192.168.x.x:3000`` — plain HTTP on a LAN address. In
production that is a policy violation:

  1. Plain HTTP origins allow a MITM on the network path to forge the
     ``Origin`` header and pass CORS.
  2. Private-IP origins bypass the intended boundary between the
     cluster ingress (public HTTPS) and internal traffic.

C2 introduces a production-only CORS origin validator with a narrow,
audited escape hatch for the rare case where plaintext LAN is
legitimately required (e.g. a temporary bring-up of a staging
environment behind a private load balancer).

Policy
------
When ``ENVIRONMENT=production``:

  * Every CORS origin must have scheme ``https`` AND a non-private
    host. Loopback (``localhost``, ``127.0.0.1``, ``::1``) and all
    standard private ranges (10/8, 172.16/12, 192.168/16, 169.254/16
    link-local, fe80::/10 IPv6 link-local) are rejected.
  * Escape hatch: ``CORS_ORIGINS_ALLOW_PLAINTEXT_LAN=true`` disables
    the gate, BUT requires ``CORS_PLAINTEXT_JUSTIFICATION`` to be set
    to a non-empty string. The justification is logged at INFO on
    every startup so the bypass leaves an audit trail.
  * The escape hatch without a justification still raises.

In any non-production environment (``development``, ``staging``,
``test``), every origin shape is accepted — ``minitux`` is designated
``development``, so local workflows against ``http://localhost:3000``
or ``http://192.168.x.x:3000`` remain frictionless.

The validator is a pure function operating on the list of origins and
the environment-supplied configuration; it makes no I/O calls and
runs in microseconds.

Naming convention: ``test_<unit>_<scenario>_<expected_outcome>``.
"""

from __future__ import annotations

import pytest

from libs.contracts.errors import ConfigError
from services.api.main import (
    CorsOriginPolicyError,
    _classify_cors_origin,
    _validate_cors_origins,
)

# ---------------------------------------------------------------------------
# Origin fixtures — classified as "safe in production" vs "weak in production".
# ---------------------------------------------------------------------------

#: Origins that are safe to allow from a production deployment. These
#: all pair ``https`` with a public-looking host.
PROD_SAFE_ORIGINS: tuple[str, ...] = (
    "https://app.fxlab.example.com",
    "https://beta.fxlab.example.com",
    "https://fxlab.example.com:8443",
    "https://app.fxlab.example.com:443",
)

#: Origins that are weak in production — either plaintext, or private-IP,
#: or loopback. Each one is paired with the human-readable reason so
#: failure messages can be asserted precisely.
PROD_WEAK_ORIGINS: tuple[tuple[str, str], ...] = (
    # Plain HTTP, even to a public hostname, is rejected.
    ("http://app.fxlab.example.com", "scheme"),
    ("http://fxlab.example.com:3000", "scheme"),
    # Private-IP literals (RFC 1918) — rejected regardless of scheme.
    ("http://192.168.1.42:3000", "private"),
    ("https://192.168.1.42:3000", "private"),
    ("http://10.0.0.1", "private"),
    ("https://172.20.5.10", "private"),
    ("http://172.31.255.255", "private"),
    # Link-local (RFC 3927) — rejected.
    ("http://169.254.1.1", "private"),
    # Loopback — rejected (should never appear in a prod CORS list).
    ("http://localhost:3000", "loopback"),
    ("http://127.0.0.1:3000", "loopback"),
    ("https://localhost", "loopback"),
    # IPv6 loopback and link-local.
    ("http://[::1]:3000", "loopback"),
    ("https://[fe80::1]", "private"),
)


# ---------------------------------------------------------------------------
# Classification helper — unit-tested directly so failure messages are
# easy to diagnose if a regex edge case regresses.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", PROD_SAFE_ORIGINS)
def test_classify_cors_origin_identifies_safe_origin(origin: str) -> None:
    """Safe origins classify as ``ok`` so the validator accepts them."""
    assert _classify_cors_origin(origin) == "ok", f"{origin!r} should classify as 'ok'"


@pytest.mark.parametrize(("origin", "reason"), PROD_WEAK_ORIGINS)
def test_classify_cors_origin_identifies_weak_origin(origin: str, reason: str) -> None:
    """Every weak origin returns its exact classification key.

    The key is surfaced in the error message so the operator can map
    the failure to the precise rule without re-deriving it.
    """
    assert _classify_cors_origin(origin) == reason, f"{origin!r} should classify as {reason!r}"


def test_classify_cors_origin_rejects_malformed_origin() -> None:
    """Unparseable origins classify as ``malformed`` so they never pass.

    An origin without a scheme (e.g. ``example.com``) cannot be safely
    allowed because the browser's ``Origin`` header always has one.
    Failing closed is correct.
    """
    assert _classify_cors_origin("example.com") == "malformed"
    assert _classify_cors_origin("") == "malformed"
    assert _classify_cors_origin("://nohost") == "malformed"


# ---------------------------------------------------------------------------
# Production — safe origins pass, weak ones raise.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("origin", PROD_SAFE_ORIGINS)
def test_production_accepts_safe_origin(origin: str) -> None:
    """Every safe origin must pass production validation unchanged."""
    _validate_cors_origins(
        origins=[origin],
        environment="production",
        allow_plaintext_lan=False,
        plaintext_justification="",
    )


@pytest.mark.parametrize(("origin", "reason"), PROD_WEAK_ORIGINS)
def test_production_rejects_weak_origin(origin: str, reason: str) -> None:
    """Every weak origin must raise in production.

    The error:
      * Names the offending origin (so grep works on the secret manifest).
      * Cites the reason category (scheme / private / loopback / malformed).
      * Mentions the escape hatch so operators know the audited bypass
        exists.
    """
    with pytest.raises(CorsOriginPolicyError) as exc_info:
        _validate_cors_origins(
            origins=[origin],
            environment="production",
            allow_plaintext_lan=False,
            plaintext_justification="",
        )
    message = str(exc_info.value)
    assert origin in message, f"Error must name the bad origin. Got: {message!r}"
    assert reason in message, f"Error must cite reason {reason!r}. Got: {message!r}"
    assert "CORS_ORIGINS_ALLOW_PLAINTEXT_LAN" in message, (
        f"Error must mention the escape hatch. Got: {message!r}"
    )


def test_production_rejects_mixed_list_on_first_weak_origin() -> None:
    """A list with one bad origin fails even if the others are safe.

    Defence in depth: a single weak origin in the allowlist is enough
    for a MITM attacker to mount a forgery. Mixing must not be
    silently accepted.
    """
    origins = [
        "https://app.fxlab.example.com",
        "http://192.168.1.10:3000",  # weak
        "https://beta.fxlab.example.com",
    ]
    with pytest.raises(CorsOriginPolicyError, match="192.168.1.10"):
        _validate_cors_origins(
            origins=origins,
            environment="production",
            allow_plaintext_lan=False,
            plaintext_justification="",
        )


# ---------------------------------------------------------------------------
# Escape hatch — explicit opt-in with audited justification.
# ---------------------------------------------------------------------------


def test_production_escape_hatch_requires_justification() -> None:
    """Turning the gate off without a justification still raises.

    A silent escape hatch defeats the purpose. The justification lands
    in the startup log; that is the audit trail.
    """
    with pytest.raises(CorsOriginPolicyError, match="CORS_PLAINTEXT_JUSTIFICATION"):
        _validate_cors_origins(
            origins=["http://192.168.1.10:3000"],
            environment="production",
            allow_plaintext_lan=True,
            plaintext_justification="",  # empty — must trip the justification gate
        )


def test_production_escape_hatch_with_justification_passes() -> None:
    """A valid justification allows a weak origin to pass in production.

    The caller is responsible for logging the justification — the
    validator's job is to enforce that one exists.
    """
    _validate_cors_origins(
        origins=["http://192.168.1.10:3000"],
        environment="production",
        allow_plaintext_lan=True,
        plaintext_justification=(
            "TEMPORARY: staging brought up on private LB "
            "2026-04-20 for load test — rollback ticket FX-1234"
        ),
    )


def test_production_escape_hatch_justification_must_be_nontrivial() -> None:
    """A one-word or whitespace-only justification is rejected.

    The audit trail must be meaningful. A single character would
    satisfy a trivial "non-empty" check but says nothing; require a
    minimum length threshold so rubber-stamp overrides get caught in
    review.
    """
    for junk in (" ", "x", "ok", "   \n  "):
        with pytest.raises(CorsOriginPolicyError, match="CORS_PLAINTEXT_JUSTIFICATION"):
            _validate_cors_origins(
                origins=["http://192.168.1.10:3000"],
                environment="production",
                allow_plaintext_lan=True,
                plaintext_justification=junk,
            )


# ---------------------------------------------------------------------------
# Non-production — all origin shapes are accepted.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("environment", ["development", "staging", "test"])
@pytest.mark.parametrize(
    "origin",
    [o for o, _ in PROD_WEAK_ORIGINS] + list(PROD_SAFE_ORIGINS),
)
def test_non_production_accepts_any_origin(environment: str, origin: str) -> None:
    """Non-production must accept every origin shape.

    Minitux is designated ``development`` per the environment policy.
    Blocking ``http://localhost:3000`` or ``http://192.168.x.x:3000``
    in development would break the standard inner-loop workflow for
    zero security benefit.
    """
    _validate_cors_origins(
        origins=[origin],
        environment=environment,
        allow_plaintext_lan=False,
        plaintext_justification="",
    )


# ---------------------------------------------------------------------------
# Regression guard — exact minitux scenario.
# ---------------------------------------------------------------------------


def test_production_rejects_lan_plaintext_named_regression() -> None:
    """Named regression guard for the exact 2026-04-15 minitux scenario.

    The installer produced ``CORS_ALLOWED_ORIGINS=http://192.168.x.x:3000``
    and the api booted without warning. If a refactor weakens the
    policy and re-admits this shape under ``ENVIRONMENT=production``,
    this test trips by name so the reviewer connects it to the
    incident.

    See ``docs/remediation/2026-04-15-minitux-install-failure.md``
    (Commit 9, C2).
    """
    with pytest.raises(CorsOriginPolicyError, match="192.168"):
        _validate_cors_origins(
            origins=["http://192.168.1.50:3000"],
            environment="production",
            allow_plaintext_lan=False,
            plaintext_justification="",
        )


# ---------------------------------------------------------------------------
# Empty list — acceptable; produces no CORS allowance.
# ---------------------------------------------------------------------------


def test_empty_origin_list_is_allowed_in_production() -> None:
    """An empty allowlist is a valid configuration.

    It denies every cross-origin request, which is correct for a
    backend-only deployment (e.g. an internal-only API behind a
    reverse proxy that handles CORS upstream).
    """
    _validate_cors_origins(
        origins=[],
        environment="production",
        allow_plaintext_lan=False,
        plaintext_justification="",
    )


# ---------------------------------------------------------------------------
# Error hierarchy — v2 remediation structural guarantees.
# ---------------------------------------------------------------------------


def test_cors_policy_error_is_config_error_subclass() -> None:
    """CorsOriginPolicyError must subclass ConfigError, not RuntimeError.

    The lifespan handler's ``except ConfigError`` block (D1 exit(3)
    pattern) must catch CORS policy violations. Prior to v2, this class
    subclassed RuntimeError and escaped the handler, causing uvicorn to
    respawn-loop on the unhandled exception instead of emitting a
    deterministic exit(3).

    See ``docs/remediation/2026-04-15-remediation-plan-v2.md``, Phase 2.
    """
    assert issubclass(CorsOriginPolicyError, ConfigError), (
        "CorsOriginPolicyError must subclass ConfigError so the lifespan "
        "exit(3) handler catches it. Got bases: "
        f"{CorsOriginPolicyError.__bases__}"
    )


def test_cors_policy_error_not_runtime_error_subclass() -> None:
    """CorsOriginPolicyError must NOT subclass RuntimeError.

    Regression guard: if someone adds RuntimeError back as a base class
    (e.g. via multiple inheritance), the exception would match bare
    ``except RuntimeError`` catches in framework code and be silently
    swallowed instead of reaching the ConfigError handler.
    """
    assert not issubclass(CorsOriginPolicyError, RuntimeError), (
        "CorsOriginPolicyError must not subclass RuntimeError. "
        f"Got bases: {CorsOriginPolicyError.__bases__}"
    )


def test_cors_validation_not_called_at_module_import_time() -> None:
    """CORS validation must run in lifespan, not at module import.

    The validator function exists at module scope (it's defined there),
    but the _call_ to ``_validate_cors_origins()`` must happen inside
    the lifespan handler. This test verifies the structural property
    by reading the source and confirming no bare call to
    ``_validate_cors_origins(`` exists between the function definition
    and the ``async def lifespan`` / ``def lifespan`` marker.

    See ``docs/remediation/2026-04-15-remediation-plan-v2.md``, Phase 2.
    """
    import inspect
    import re

    import services.api.main as main_module

    source = inspect.getsource(main_module)

    # Find where the function definition ends and where lifespan begins.
    # We want to check that between these two markers, there's no
    # bare call to _validate_cors_origins( that is NOT in a comment.
    func_def_end = source.find("def _validate_cors_origins(")
    lifespan_start = source.find("def lifespan(")

    assert func_def_end != -1, "_validate_cors_origins definition not found"
    assert lifespan_start != -1, "lifespan definition not found"

    # Find the end of the _validate_cors_origins function body.
    # Look for the next top-level def/class after func_def_end.
    next_def = re.search(
        r"^(?:def |class |async def )",
        source[func_def_end + 1 :],
        re.MULTILINE,
    )
    func_body_end = func_def_end + 1 + next_def.start() if next_def else func_def_end + 500

    # The zone between function body end and lifespan definition is
    # module-scope code. Check for bare calls to the validator.
    module_scope_zone = source[func_body_end:lifespan_start]

    # Strip comments from each line before checking for the call.
    call_pattern = re.compile(r"^\s*_validate_cors_origins\(", re.MULTILINE)
    code_lines = []
    for line in module_scope_zone.split("\n"):
        stripped = line.split("#")[0]  # remove inline comments
        code_lines.append(stripped)
    code_only = "\n".join(code_lines)

    assert not call_pattern.search(code_only), (
        "_validate_cors_origins() is called at module scope (between its "
        "definition and lifespan). It must only be called inside lifespan "
        "so the ConfigError handler can catch policy violations."
    )


def test_cors_validation_called_inside_lifespan() -> None:
    """CORS validation must be called inside the lifespan function.

    Complements ``test_cors_validation_not_called_at_module_import_time``
    by confirming the call exists within the lifespan body.
    """
    import inspect

    import services.api.main as main_module

    source = inspect.getsource(main_module)

    lifespan_start = source.find("def lifespan(")
    assert lifespan_start != -1, "lifespan definition not found"

    # Extract lifespan body (approximate — find the next top-level def).
    lifespan_body = source[lifespan_start:]

    assert "_validate_cors_origins(" in lifespan_body, (
        "_validate_cors_origins() is not called inside lifespan. "
        "The CORS policy must be enforced during startup so the "
        "ConfigError → exit(3) handler can catch violations."
    )

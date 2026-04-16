#!/usr/bin/env bash
# ===========================================================================
# Tests for install.sh::_is_private_ip() and setup_env() LAN detection
# ===========================================================================
#
# Purpose:
#     Verify the v2 remediation's environment designation logic:
#       - _is_private_ip() correctly classifies RFC 1918 / loopback /
#         link-local addresses as private.
#       - setup_env() sets ENVIRONMENT=development when the server's
#         primary IP is private (LAN-only install).
#       - setup_env() preserves ENVIRONMENT=production when the server's
#         primary IP is public.
#       - setup_env() writes POSTGRES_SSLMODE=disable alongside
#         ENVIRONMENT=development for LAN hosts (dev postgres container
#         has no SSL, so 'prefer' triggers a silent plaintext fallback
#         that the production libpq gate rejects).
#       - setup_env() writes POSTGRES_SSLMODE=require alongside
#         ENVIRONMENT=production for public hosts (fail-safe strict SSL
#         posture for any routable deployment).
#       - FXLAB_ENVIRONMENT_OVERRIDE takes precedence over auto-detection
#         and drives POSTGRES_SSLMODE consistent with the chosen env.
#
# Why this matters:
#     The C2 CORS validator rejects plaintext HTTP origins on private IPs
#     in production. install.sh auto-detects CORS origins as
#     http://<LAN_IP> — the combination is a guaranteed crash at startup.
#     Setting ENVIRONMENT=development on LAN hosts sidesteps the policy
#     without weakening the production security posture.
#
#     Additionally: the production _enforce_postgres_sslmode gate rejects
#     sslmode in {disable, allow, prefer}. docker-compose.prod.yml's
#     DATABASE_URL now resolves sslmode from ${POSTGRES_SSLMODE:-require};
#     install.sh must write the correct value into .env so the container
#     receives a consistent ENVIRONMENT/sslmode pair. (See 2026-04-16
#     minitux failure #4 in docs/remediation/.)
#
# Why shell-native (no bats):
#     Matches the existing pattern in tests/shell/test_install_pull_latest.sh.
#     The target is a bash function graph; we source install.sh and call
#     the functions directly.
#
# Run:
#     bash tests/shell/test_install_env_detection.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
# ===========================================================================

set -uo pipefail  # NOT -e: continue after failures for complete reporting.

# ---------------------------------------------------------------------------
# Test framework (minimal — mirrors test_install_pull_latest.sh)
# ---------------------------------------------------------------------------

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

assert_eq() {
    local expected="$1" actual="$2" msg="${3:-}"
    if [[ "$expected" == "$actual" ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      expected: ${expected}"
    echo "      actual  : ${actual}"
    return 1
}

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    if [[ "$haystack" == *"$needle"* ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      expected substring: ${needle}"
    echo "      actual (first 400): ${haystack:0:400}"
    return 1
}

run_test() {
    local name="$1"; shift
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "  · ${name}"
    if ( "$@" ); then
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$name")
    fi
}

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

INSTALL_SH="$(cd "$(dirname "$0")/../.." && pwd)/install.sh"

source_install_sh() {
    # shellcheck disable=SC1090
    source "$INSTALL_SH"
}

make_env_fixture() {
    # Create a temp directory with a .env file from the production template.
    # Returns the temp dir path.
    local root
    root="$(mktemp -d -t fxlab-env-XXXXXX)"
    touch "${root}/install.log"

    # Minimal .env.production.template content — only what setup_env needs.
    cat > "${root}/.env.production.template" <<'TMPL'
ENVIRONMENT=production
JWT_SECRET_KEY=CHANGE_ME
POSTGRES_PASSWORD=CHANGE_ME
CORS_ALLOWED_ORIGINS=CHANGE_ME
FXLAB_HTTP_PORT=80
FXLAB_HTTPS_PORT=443
TMPL
    echo "$root"
}

cleanup_fixture() {
    local root="$1"
    [[ -n "$root" && -d "$root" ]] && rm -rf "$root"
}

# ---------------------------------------------------------------------------
# _is_private_ip unit tests
# ---------------------------------------------------------------------------

test_private_ip_10_network() {
    source_install_sh
    _is_private_ip "10.0.0.1" || { echo "    FAIL: 10.0.0.1 should be private"; return 1; }
    _is_private_ip "10.255.255.255" || { echo "    FAIL: 10.255.255.255 should be private"; return 1; }
}

test_private_ip_172_network() {
    source_install_sh
    _is_private_ip "172.16.0.1" || { echo "    FAIL: 172.16.0.1 should be private"; return 1; }
    _is_private_ip "172.31.255.255" || { echo "    FAIL: 172.31.255.255 should be private"; return 1; }
    # 172.15.x and 172.32.x are NOT private.
    if _is_private_ip "172.15.0.1"; then
        echo "    FAIL: 172.15.0.1 should NOT be private"
        return 1
    fi
    if _is_private_ip "172.32.0.1"; then
        echo "    FAIL: 172.32.0.1 should NOT be private"
        return 1
    fi
}

test_private_ip_192_168_network() {
    source_install_sh
    _is_private_ip "192.168.1.5" || { echo "    FAIL: 192.168.1.5 should be private"; return 1; }
    _is_private_ip "192.168.0.1" || { echo "    FAIL: 192.168.0.1 should be private"; return 1; }
    _is_private_ip "192.168.255.255" || { echo "    FAIL: 192.168.255.255 should be private"; return 1; }
}

test_private_ip_loopback() {
    source_install_sh
    _is_private_ip "127.0.0.1" || { echo "    FAIL: 127.0.0.1 should be private"; return 1; }
    _is_private_ip "127.255.255.255" || { echo "    FAIL: 127.255.255.255 should be private"; return 1; }
}

test_private_ip_link_local() {
    source_install_sh
    _is_private_ip "169.254.1.1" || { echo "    FAIL: 169.254.1.1 should be private"; return 1; }
    _is_private_ip "169.254.255.255" || { echo "    FAIL: 169.254.255.255 should be private"; return 1; }
}

test_public_ip_returns_false() {
    source_install_sh
    if _is_private_ip "20.42.0.50"; then
        echo "    FAIL: 20.42.0.50 (Azure) should NOT be private"
        return 1
    fi
    if _is_private_ip "8.8.8.8"; then
        echo "    FAIL: 8.8.8.8 should NOT be private"
        return 1
    fi
    if _is_private_ip "52.170.38.1"; then
        echo "    FAIL: 52.170.38.1 (Azure) should NOT be private"
        return 1
    fi
}

test_non_ip_string_returns_false() {
    source_install_sh
    # Non-IP strings (e.g. "localhost") should NOT match as private.
    # This is fail-safe: unknown strings default to "not private"
    # so the caller falls through to the production path.
    if _is_private_ip "localhost"; then
        echo "    FAIL: 'localhost' string should return false (not an IP)"
        return 1
    fi
    if _is_private_ip ""; then
        echo "    FAIL: empty string should return false"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# setup_env integration tests (environment detection path)
# ---------------------------------------------------------------------------

test_setup_env_sets_development_for_lan_ip() {
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    unset FXLAB_ENVIRONMENT_OVERRIDE 2>/dev/null || true
    source_install_sh

    # Copy template to .env (simulating first-run path).
    cp "${root}/.env.production.template" "${root}/.env"

    # Shadow hostname to return a LAN IP.
    hostname() { echo "192.168.1.5 "; }
    export -f hostname

    setup_env 2>/dev/null

    local env_value
    env_value="$(grep '^ENVIRONMENT=' "${root}/.env" | cut -d= -f2)"
    assert_eq "development" "$env_value" \
        "ENVIRONMENT should be 'development' for LAN IP 192.168.1.5" || return 1
}

test_setup_env_keeps_production_for_public_ip() {
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    unset FXLAB_ENVIRONMENT_OVERRIDE 2>/dev/null || true
    source_install_sh

    cp "${root}/.env.production.template" "${root}/.env"

    # Shadow hostname to return an Azure public IP.
    hostname() { echo "20.42.0.50 "; }
    export -f hostname

    setup_env 2>/dev/null

    local env_value
    env_value="$(grep '^ENVIRONMENT=' "${root}/.env" | cut -d= -f2)"
    assert_eq "production" "$env_value" \
        "ENVIRONMENT should remain 'production' for public IP 20.42.0.50" || return 1
}

test_setup_env_override_takes_precedence() {
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    export FXLAB_ENVIRONMENT_OVERRIDE="staging"
    source_install_sh

    cp "${root}/.env.production.template" "${root}/.env"

    # Even though the IP is private, the override should win.
    hostname() { echo "192.168.1.5 "; }
    export -f hostname

    setup_env 2>/dev/null

    local env_value
    env_value="$(grep '^ENVIRONMENT=' "${root}/.env" | cut -d= -f2)"
    assert_eq "staging" "$env_value" \
        "FXLAB_ENVIRONMENT_OVERRIDE=staging should set ENVIRONMENT=staging" || return 1
}

test_setup_env_production_override_on_lan() {
    # Operator explicitly wants production on a LAN host — must be honoured.
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    export FXLAB_ENVIRONMENT_OVERRIDE="production"
    source_install_sh

    cp "${root}/.env.production.template" "${root}/.env"

    hostname() { echo "192.168.1.5 "; }
    export -f hostname

    setup_env 2>/dev/null

    local env_value
    env_value="$(grep '^ENVIRONMENT=' "${root}/.env" | cut -d= -f2)"
    assert_eq "production" "$env_value" \
        "Explicit FXLAB_ENVIRONMENT_OVERRIDE=production must be honoured on LAN" || return 1
}

# ---------------------------------------------------------------------------
# POSTGRES_SSLMODE coupling tests (2026-04-16 failure #4 remediation)
# ---------------------------------------------------------------------------
#
# docker-compose.prod.yml resolves sslmode from ${POSTGRES_SSLMODE:-require}.
# install.sh must write the correct value into .env so the container's
# DATABASE_URL carries a sslmode consistent with the ENVIRONMENT it runs in:
#
#   LAN / development           → POSTGRES_SSLMODE=disable
#   public-IP / production      → POSTGRES_SSLMODE=require
#   FXLAB_ENVIRONMENT_OVERRIDE  → mirrors the override decision
#
# Rationale for 'disable' in dev: postgres:15-alpine does not ship SSL
# certs. 'prefer' silently falls back to plaintext on negotiation failure
# (the exact libpq behaviour the production gate rejects); 'disable'
# makes the plaintext intent explicit and avoids a pointless SSL probe
# on every connection.

test_setup_env_lan_ip_writes_sslmode_disable() {
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    unset FXLAB_ENVIRONMENT_OVERRIDE 2>/dev/null || true
    source_install_sh

    cp "${root}/.env.production.template" "${root}/.env"

    hostname() { echo "192.168.1.5 "; }
    export -f hostname

    setup_env 2>/dev/null

    local sslmode
    sslmode="$(grep '^POSTGRES_SSLMODE=' "${root}/.env" | cut -d= -f2)"
    assert_eq "disable" "$sslmode" \
        "LAN IP install must write POSTGRES_SSLMODE=disable to .env" || return 1
}

test_setup_env_public_ip_writes_sslmode_require() {
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    unset FXLAB_ENVIRONMENT_OVERRIDE 2>/dev/null || true
    source_install_sh

    cp "${root}/.env.production.template" "${root}/.env"

    hostname() { echo "20.42.0.50 "; }
    export -f hostname

    setup_env 2>/dev/null

    local sslmode
    sslmode="$(grep '^POSTGRES_SSLMODE=' "${root}/.env" | cut -d= -f2)"
    assert_eq "require" "$sslmode" \
        "Public IP install must write POSTGRES_SSLMODE=require to .env" || return 1
}

test_setup_env_production_override_writes_sslmode_require() {
    # Operator explicitly chose production on a LAN host — sslmode must be
    # strict to match, otherwise the production gate rejects the DSN.
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    export FXLAB_ENVIRONMENT_OVERRIDE="production"
    source_install_sh

    cp "${root}/.env.production.template" "${root}/.env"

    hostname() { echo "192.168.1.5 "; }
    export -f hostname

    setup_env 2>/dev/null

    local sslmode
    sslmode="$(grep '^POSTGRES_SSLMODE=' "${root}/.env" | cut -d= -f2)"
    assert_eq "require" "$sslmode" \
        "FXLAB_ENVIRONMENT_OVERRIDE=production must yield POSTGRES_SSLMODE=require" || return 1
}

test_setup_env_development_override_on_public_ip_writes_sslmode_disable() {
    # Operator explicitly chose development on a public-IP host (e.g.
    # a staging box on Azure). Non-production skips the sslmode gate,
    # so 'disable' is correct — it signals the operator's intent.
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443
    export FXLAB_ENVIRONMENT_OVERRIDE="development"
    source_install_sh

    cp "${root}/.env.production.template" "${root}/.env"

    hostname() { echo "20.42.0.50 "; }
    export -f hostname

    setup_env 2>/dev/null

    local sslmode
    sslmode="$(grep '^POSTGRES_SSLMODE=' "${root}/.env" | cut -d= -f2)"
    assert_eq "disable" "$sslmode" \
        "FXLAB_ENVIRONMENT_OVERRIDE=development must yield POSTGRES_SSLMODE=disable" || return 1
}

test_setup_env_sslmode_matches_environment_invariant() {
    # Structural invariant: every branch of setup_env must leave .env
    # with an ENVIRONMENT / POSTGRES_SSLMODE pair that satisfies:
    #
    #   ENVIRONMENT=production       → POSTGRES_SSLMODE in {require,verify-ca,verify-full}
    #   ENVIRONMENT!=production      → POSTGRES_SSLMODE in {disable,prefer,allow,require,verify-ca,verify-full}
    #                                  (gate is advisory; any value works)
    #
    # This test exercises the four meaningful combinations and asserts
    # the invariant holds in each.
    local root
    root="$(make_env_fixture)"
    trap "cleanup_fixture '$root'" RETURN

    export FXLAB_HOME="$root"
    export LOG_FILE="${root}/install.log"
    export FXLAB_HTTP_PORT=80
    export FXLAB_HTTPS_PORT=443

    local cases=(
        "lan|development|disable|192.168.1.5|"
        "public|production|require|20.42.0.50|"
        "override_prod_lan|production|require|192.168.1.5|production"
        "override_dev_public|development|disable|20.42.0.50|development"
    )

    local case_spec label want_env want_sslmode ip override
    for case_spec in "${cases[@]}"; do
        IFS='|' read -r label want_env want_sslmode ip override <<< "$case_spec"
        if [[ -n "$override" ]]; then
            export FXLAB_ENVIRONMENT_OVERRIDE="$override"
        else
            unset FXLAB_ENVIRONMENT_OVERRIDE 2>/dev/null || true
        fi
        # Fresh .env for each scenario so we see the write, not a leftover.
        cp "${root}/.env.production.template" "${root}/.env"
        source_install_sh
        hostname() { echo "$ip "; }
        export -f hostname

        setup_env 2>/dev/null

        local got_env got_ssl
        got_env="$(grep '^ENVIRONMENT=' "${root}/.env" | cut -d= -f2)"
        got_ssl="$(grep '^POSTGRES_SSLMODE=' "${root}/.env" | cut -d= -f2)"

        if [[ "$got_env" != "$want_env" ]]; then
            echo "    FAIL [$label]: ENVIRONMENT expected=$want_env actual=$got_env"
            return 1
        fi
        if [[ "$got_ssl" != "$want_sslmode" ]]; then
            echo "    FAIL [$label]: POSTGRES_SSLMODE expected=$want_sslmode actual=$got_ssl"
            return 1
        fi
        # Production invariant check
        if [[ "$got_env" == "production" ]]; then
            case "$got_ssl" in
                require|verify-ca|verify-full) ;;
                *)
                    echo "    FAIL [$label]: ENVIRONMENT=production but sslmode=$got_ssl is not strict"
                    return 1
                    ;;
            esac
        fi
    done
}

# ---------------------------------------------------------------------------
# Structural assertion: _is_private_ip exists in install.sh
# ---------------------------------------------------------------------------

test_is_private_ip_function_exists_in_install_sh() {
    grep -q '^_is_private_ip()' "$INSTALL_SH" || {
        echo "    FAIL: _is_private_ip() function not found in install.sh"
        return 1
    }
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$INSTALL_SH" ]]; then
        echo "ERROR: install.sh not found at ${INSTALL_SH}"
        exit 2
    fi

    echo "install.sh environment detection test suite"
    echo "--------------------------------------------"

    run_test "_is_private_ip: 10.x.x.x network"                    test_private_ip_10_network
    run_test "_is_private_ip: 172.16-31.x.x network"               test_private_ip_172_network
    run_test "_is_private_ip: 192.168.x.x network"                 test_private_ip_192_168_network
    run_test "_is_private_ip: 127.x loopback"                      test_private_ip_loopback
    run_test "_is_private_ip: 169.254.x link-local"                test_private_ip_link_local
    run_test "_is_private_ip: public IPs return false"              test_public_ip_returns_false
    run_test "_is_private_ip: non-IP strings return false"          test_non_ip_string_returns_false
    run_test "setup_env: LAN IP → ENVIRONMENT=development"          test_setup_env_sets_development_for_lan_ip
    run_test "setup_env: public IP → ENVIRONMENT=production"        test_setup_env_keeps_production_for_public_ip
    run_test "setup_env: FXLAB_ENVIRONMENT_OVERRIDE takes precedence" test_setup_env_override_takes_precedence
    run_test "setup_env: explicit production on LAN is honoured"     test_setup_env_production_override_on_lan
    run_test "setup_env: LAN IP → POSTGRES_SSLMODE=disable"          test_setup_env_lan_ip_writes_sslmode_disable
    run_test "setup_env: public IP → POSTGRES_SSLMODE=require"       test_setup_env_public_ip_writes_sslmode_require
    run_test "setup_env: override=production → sslmode=require"      test_setup_env_production_override_writes_sslmode_require
    run_test "setup_env: override=development → sslmode=disable"     test_setup_env_development_override_on_public_ip_writes_sslmode_disable
    run_test "setup_env: ENVIRONMENT/sslmode pairing invariant"      test_setup_env_sslmode_matches_environment_invariant
    run_test "structural: _is_private_ip exists in install.sh"       test_is_private_ip_function_exists_in_install_sh

    echo
    echo "--------------------------------------------"
    echo "Ran:    ${TESTS_RUN}"
    echo "Passed: ${TESTS_PASSED}"
    echo "Failed: ${TESTS_FAILED}"
    if [[ ${TESTS_FAILED} -gt 0 ]]; then
        echo
        echo "Failed tests:"
        for name in "${FAILED_TESTS[@]}"; do
            echo "  - ${name}"
        done
        exit 1
    fi
    exit 0
}

main "$@"

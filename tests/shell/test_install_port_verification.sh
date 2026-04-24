#!/usr/bin/env bash
# ===========================================================================
# Tests for install.sh post-teardown port verification (Tranche E —
# 2026-04-24 hardening).
# ===========================================================================
#
# Purpose:
#     On 2026-04-24 minitux install.sh logged "Teardown complete — ports
#     and volumes are free." and then immediately failed the port check
#     with "Port 80 (HTTP) is already in use by docker-proxy". The
#     teardown message was a lie: docker compose down only removes
#     services defined in the current compose project, so orphan
#     containers, stale docker-proxies, or host binaries still holding
#     the port are invisible to it. Nothing verified the claim before
#     it was printed.
#
#     Tranche E adds an _assert_ports_actually_free helper that:
#
#       1. Checks each port with ss/netstat. If free, pass.
#       2. If a container is still publishing the port (docker ps -a
#          --filter publish=<port>), force-remove it — logged by name.
#       3. Retry up to N times with 1s backoff (daemon needs a moment
#          to release the proxy after container removal).
#       4. If STILL bound, identify the holder (stale docker-proxy vs
#          host binary like apache2 / system nginx) and fail with a
#          specific, actionable error naming the holder.
#
#     The helper is called at the end of teardown_existing BEFORE the
#     "Teardown complete — ports and volumes are free." log line, so
#     that message only fires when true.
#
# Why shell-native (no bats):
#     The target is a bash function graph inside install.sh. Shadowing
#     `docker`, `ss`, and `netstat` with bash functions is the cleanest
#     way to drive _assert_ports_actually_free through each scenario
#     without touching a real docker daemon. Mirrors the pattern in
#     tests/shell/test_install_diagnostics.sh and
#     tests/shell/test_install_pull_latest.sh.
#
# Run:
#     bash tests/shell/test_install_port_verification.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
# ===========================================================================

set -uo pipefail  # NOT -e: we want the summary to report every broken test.

# ---------------------------------------------------------------------------
# Test framework (mirrors tests/shell/test_install_diagnostics.sh)
# ---------------------------------------------------------------------------

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    if [[ "$haystack" == *"$needle"* ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      expected substring: ${needle}"
    echo "      actual (first 400) : ${haystack:0:400}"
    return 1
}

assert_not_contains() {
    local haystack="$1" needle="$2" msg="${3:-}"
    if [[ "$haystack" != *"$needle"* ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      unwanted substring: ${needle}"
    echo "      actual (first 400): ${haystack:0:400}"
    return 1
}

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

run_test() {
    local name="$1"; shift
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "  · ${name}"
    # Subshell isolation — env / function shadows / cwd don't leak,
    # AND `fail` calling exit 1 inside the helper doesn't abort us.
    if ( "$@" ); then
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        TESTS_FAILED=$((TESTS_FAILED + 1))
        FAILED_TESTS+=("$name")
    fi
}

# ---------------------------------------------------------------------------
# Fixture setup
# ---------------------------------------------------------------------------

INSTALL_SH="$(cd "$(dirname "$0")/../.." && pwd)/install.sh"

#: Per-test tempdir — holds LOG_FILE and the state files used by the
#: ss/docker shadows (counter for "port is bound" transitions, list of
#: containers currently "publishing" each port, etc.).
make_fixture_dir() {
    local root
    root="$(mktemp -d -t fxlab-tranche-e-XXXXXX)"
    touch "${root}/install.log"
    echo "$root"
}

cleanup_fixture_dir() {
    local root="$1"
    [[ -n "$root" && -d "$root" ]] && rm -rf "$root"
}

prime_env() {
    local root="$1"
    export LOG_FILE="${root}/install.log"
    export FXLAB_LOG_DIR="$root"
    export FXLAB_HTTP_PORT="${FXLAB_HTTP_PORT:-80}"
    export FXLAB_HTTPS_PORT="${FXLAB_HTTPS_PORT:-443}"
    # State files used by shadows.
    export _TE_SS_STATE_DIR="${root}/ss"
    export _TE_DOCKER_STATE_DIR="${root}/docker"
    mkdir -p "$_TE_SS_STATE_DIR" "$_TE_DOCKER_STATE_DIR"
}

source_install_sh() {
    # BASH_SOURCE guard at the bottom of install.sh prevents main()
    # from executing on source.
    # shellcheck disable=SC1090
    source "$INSTALL_SH"
}

# ---------------------------------------------------------------------------
# ss / netstat shadows
# ---------------------------------------------------------------------------
#
# The ss shadow reads the state file _TE_SS_STATE_DIR/<port>.txt for each
# invocation. Each read decrements the number on the first line (until 0)
# and emits the rest of the file as ss output. When the counter hits 0,
# the file is rewritten as "<N>\nFREE" — meaning port is free on every
# subsequent call. This lets us simulate "port bound for first N attempts,
# then becomes free after cleanup".
#
# Shape of state file:
#     BOUND_REMAINING=<N>
#     <exact line ss would emit while port is bound, or the word FREE>
#
# We shadow both `ss` and `netstat` since _port_is_bound tries each.

_set_ss_bound_for() {
    # _set_ss_bound_for <port> <remaining_attempts> "<ss output line>"
    local port="$1" remaining="$2" line="$3"
    printf '%s\n%s\n' "$remaining" "$line" > "${_TE_SS_STATE_DIR}/${port}.txt"
}

_set_ss_free() {
    # _set_ss_free <port>   — port is free from now on.
    local port="$1"
    printf '0\nFREE\n' > "${_TE_SS_STATE_DIR}/${port}.txt"
}

install_ss_shadow() {
    ss() {
        # We only support `ss -tlnp` which is what install.sh uses.
        local want_port=""
        for arg in "$@"; do
            case "$arg" in
                -tlnp|-ltnp|-tnlp|-lntp|-plnt|-pltn|-nlpt|-nltp) ;;
                *) ;;
            esac
        done
        # Emit one synthetic line per port that's currently "bound".
        local state_file
        for state_file in "${_TE_SS_STATE_DIR}"/*.txt; do
            [[ -f "$state_file" ]] || continue
            local port
            port="$(basename "$state_file" .txt)"
            local remaining line
            { read -r remaining; IFS= read -r line; } < "$state_file"
            if [[ "$line" == "FREE" ]]; then
                continue
            fi
            # Emit the canned line (shaped like ss output's last column).
            echo "LISTEN 0 128 0.0.0.0:${port} 0.0.0.0:*     ${line}"
            if (( remaining > 0 )); then
                remaining=$(( remaining - 1 ))
                if (( remaining == 0 )); then
                    _set_ss_free "$port"
                else
                    printf '%s\n%s\n' "$remaining" "$line" > "$state_file"
                fi
            fi
        done
        return 0
    }
    export -f ss

    netstat() {
        # install.sh's _port_is_bound falls back to netstat. We always
        # return nothing here — the ss shadow is the single source of
        # truth for port state so tests remain readable.
        return 0
    }
    export -f netstat
}

# ---------------------------------------------------------------------------
# docker shadow
# ---------------------------------------------------------------------------
#
# _set_docker_publishers <port> "<cid1> <cname1>|<cid2> <cname2>|..."
#     Configure which containers should appear to be publishing <port>
#     on subsequent `docker ps -a --filter publish=<port>` calls.
#     Use "" to simulate "no containers publishing".
#
# The shadow consumes the "publishers" list when `docker rm -f` is called
# on a container ID — after removal, subsequent publish-filter queries
# will no longer return that ID. This lets tests verify that the helper
# actually removes orphans.

_set_docker_publishers() {
    # Empty publishers → truncate file (no containers publishing port).
    # Non-empty → write with trailing newline so `while read` processes
    # every line (bash `read` returns non-zero on the final unterminated
    # line and drops it).
    local port="$1" publishers="${2:-}"
    if [[ -z "$publishers" ]]; then
        : > "${_TE_DOCKER_STATE_DIR}/publish_${port}.txt"
    else
        printf '%s\n' "$publishers" > "${_TE_DOCKER_STATE_DIR}/publish_${port}.txt"
    fi
}

install_docker_shadow() {
    docker() {
        if [[ "${1:-}" == "ps" ]]; then
            shift
            # Look for --filter publish=<port>
            local port=""
            local fmt=""
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    --filter)
                        if [[ "${2:-}" == publish=* ]]; then
                            port="${2#publish=}"
                        fi
                        shift 2
                        ;;
                    --filter=publish=*)
                        port="${1#--filter=publish=}"
                        shift
                        ;;
                    --format)
                        fmt="${2:-}"
                        shift 2
                        ;;
                    --format=*)
                        fmt="${1#--format=}"
                        shift
                        ;;
                    *)
                        shift
                        ;;
                esac
            done
            if [[ -n "$port" ]]; then
                local file="${_TE_DOCKER_STATE_DIR}/publish_${port}.txt"
                [[ -f "$file" ]] || return 0
                local line
                while IFS= read -r line; do
                    [[ -z "$line" ]] && continue
                    # line format: "<cid> <cname>"
                    echo "$line"
                done < <(tr '|' '\n' < "$file")
            fi
            return 0
        fi

        if [[ "${1:-}" == "rm" ]]; then
            shift
            # docker rm -f <id>
            local target=""
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    -f|--force) shift ;;
                    *) target="$1"; shift ;;
                esac
            done
            [[ -z "$target" ]] && return 1
            # Remove any entries matching this ID from every publisher file.
            local pf
            for pf in "${_TE_DOCKER_STATE_DIR}"/publish_*.txt; do
                [[ -f "$pf" ]] || continue
                # Rebuild file excluding the entry matching this ID.
                local kept=""
                local entry
                while IFS= read -r entry; do
                    [[ -z "$entry" ]] && continue
                    # Entry format: "<cid> <cname>"
                    local cid="${entry%% *}"
                    if [[ "$cid" != "$target" ]]; then
                        kept+="${entry}|"
                    fi
                done < <(tr '|' '\n' < "$pf")
                # Strip trailing |
                kept="${kept%|}"
                printf '%s' "$kept" > "$pf"
            done
            return 0
        fi

        # Any other docker subcommand: no-op.
        return 0
    }
    export -f docker
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test_passes_when_ports_already_free() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_ss_shadow
    install_docker_shadow
    # Both ports start free.
    _set_ss_free 80
    _set_ss_free 443

    local output
    output="$(_assert_ports_actually_free 80 443 2>&1)" || {
        echo "    FAIL: helper exited non-zero when both ports were free."
        echo "    output: ${output:0:400}"
        return 1
    }

    assert_contains "$output" "Port 80 is confirmed free" \
        "log must confirm port 80 after success" || return 1
    assert_contains "$output" "Port 443 is confirmed free" \
        "log must confirm port 443 after success" || return 1
}

test_removes_orphan_container_and_succeeds() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_ss_shadow
    install_docker_shadow

    # Port 80 is bound by a leftover fxlab-nginx for ONE attempt.
    # After the shadow's counter hits zero (or the container is
    # removed — whichever first), subsequent ss calls report free.
    _set_ss_bound_for 80 3 'users:(("docker-proxy",pid=999,fd=7))'
    _set_docker_publishers 80 "abc123 fxlab-nginx-old"

    local output
    output="$(_assert_ports_actually_free 80 2>&1)" || {
        echo "    FAIL: helper should succeed after removing orphan."
        echo "    output: ${output:0:400}"
        return 1
    }

    assert_contains "$output" "fxlab-nginx-old" \
        "log must name the orphan container that was removed" || return 1
    assert_contains "$output" "Port 80 is confirmed free" \
        "log must confirm port 80 after cleanup" || return 1
}

test_fails_when_host_binary_holds_port() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_ss_shadow
    install_docker_shadow

    # Port held by apache2 for all attempts (counter larger than retry
    # ceiling). No container publisher — so no orphan to remove.
    _set_ss_bound_for 80 99 'users:(("apache2",pid=1234,fd=4))'
    _set_docker_publishers 80 ""

    local output
    if output="$(_assert_ports_actually_free 80 2>&1)"; then
        echo "    FAIL: helper should have failed with apache2 holding port."
        echo "    output: ${output:0:400}"
        return 1
    fi

    assert_contains "$output" "apache2" \
        "error must name the host binary holding the port" || return 1
    assert_not_contains "$output" "Port 80 is confirmed free" \
        "success line must NOT appear when helper fails" || return 1
}

test_fails_with_systemctl_hint_when_docker_proxy_is_stale() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_ss_shadow
    install_docker_shadow

    # Port held by docker-proxy, no container behind it (daemon leak).
    _set_ss_bound_for 80 99 'users:(("docker-proxy",pid=2808804,fd=7))'
    _set_docker_publishers 80 ""

    local output
    if output="$(_assert_ports_actually_free 80 2>&1)"; then
        echo "    FAIL: helper should have failed with stale docker-proxy."
        echo "    output: ${output:0:400}"
        return 1
    fi

    assert_contains "$output" "docker-proxy" \
        "error must identify docker-proxy as holder" || return 1
    assert_contains "$output" "systemctl restart docker" \
        "error must tell operator the single corrective command" || return 1
}

test_teardown_existing_does_not_print_success_when_port_still_bound() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_ss_shadow
    install_docker_shadow

    # Bypass the compose-level teardown steps inside teardown_existing:
    # set FXLAB_HOME to a dir with no compose file so the "direct docker"
    # branch runs, and shadow docker to be a no-op for its calls.
    export FXLAB_HOME="$root"

    # After all docker cleanup in teardown_existing, port 80 is STILL
    # bound by apache2. The new guard should refuse to print the
    # "Teardown complete — ports and volumes are free." message.
    _set_ss_bound_for 80 99 'users:(("apache2",pid=1234,fd=4))'
    _set_ss_free 443
    _set_docker_publishers 80 ""
    _set_docker_publishers 443 ""

    local output
    output="$(teardown_existing 2>&1)" || true

    assert_not_contains "$output" "Teardown complete — ports and volumes are free." \
        "teardown must NOT print the success line when a port is still bound" \
        || return 1
    assert_contains "$output" "apache2" \
        "teardown's failure message must surface the host binary holding the port" \
        || return 1
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$INSTALL_SH" ]]; then
        echo "ERROR: install.sh not found at ${INSTALL_SH}"
        exit 2
    fi

    echo "install.sh Tranche E port-verification test suite"
    echo "--------------------------------------------------"

    run_test "passes when both ports are already free"                                 test_passes_when_ports_already_free
    run_test "removes orphan container still publishing port, then succeeds"          test_removes_orphan_container_and_succeeds
    run_test "fails with host-binary name when apache2 holds port"                     test_fails_when_host_binary_holds_port
    run_test "fails with systemctl-restart hint when docker-proxy is stale"            test_fails_with_systemctl_hint_when_docker_proxy_is_stale
    run_test "teardown_existing does not print success when port is still bound"       test_teardown_existing_does_not_print_success_when_port_still_bound

    echo
    echo "--------------------------------------------------"
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

#!/usr/bin/env bash
# ===========================================================================
# Tests for install.sh diagnostic output on service-health failure (D4)
# ===========================================================================
#
# Purpose:
#     Verify that when `wait_for_healthy` fails, install.sh emits a
#     diagnostic banner that:
#
#       1. Names every failing service in the FIRST 20 lines of output
#          (so the root-cause service is visible without scrolling
#          through interleaved compose logs).
#       2. Distinguishes "restart budget exhausted" (State=exited,
#          ExitCode != 0 — compose will not restart further because of
#          the B3/D1 on-failure:3 policy) from "still starting" /
#          "unhealthy" / "blocked on deps" states.
#       3. Writes each failing service's FULL log to a dedicated
#          per-service file under FXLAB_LOG_DIR and prints the file
#          path so the operator can grep, diff, or attach it to a
#          support ticket without re-running the install.
#       4. Emits only the failing services' tails inline — NOT the
#          healthy services' logs. This is the specific 2026-04-15
#          minitux remediation: the installer used to print all
#          containers' logs interleaved, burying api's Redis EINVAL
#          under cadvisor / node-exporter noise.
#       5. Supports an --all-logs mode (INSTALL_ALL_LOGS=1) that
#          dumps full logs to stdout instead of writing per-service
#          files, for operators who prefer the single-stream view.
#
# Why shell-native (no bats):
#     The target is a bash function graph. Shadowing `docker` with a
#     bash function is the cleanest way to drive the diagnostic
#     without spinning up a real compose stack, and matches the
#     existing pattern in tests/shell/test_install_pull_latest.sh.
#
# Run:
#     bash tests/shell/test_install_diagnostics.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
# ===========================================================================

set -uo pipefail  # NOT -e: we want to keep running tests after failures so
                  # the final summary reports every broken assertion.

# ---------------------------------------------------------------------------
# Test framework (minimal — mirrors tests/shell/test_install_pull_latest.sh)
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

assert_file_exists() {
    local path="$1" msg="${2:-}"
    if [[ -f "$path" ]]; then
        return 0
    fi
    echo "    FAIL: ${msg}"
    echo "      path does not exist: ${path}"
    return 1
}

run_test() {
    local name="$1"; shift
    TESTS_RUN=$((TESTS_RUN + 1))
    echo "  · ${name}"
    # Subshell isolation — env / function shadows / cwd don't leak.
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

#: Absolute path to install.sh — resolved relative to this test file so
#: the suite runs correctly from any cwd.
INSTALL_SH="$(cd "$(dirname "$0")/../.." && pwd)/install.sh"

make_fixture_dir() {
    # Create a fresh tempdir that will hold the install log + per-service
    # log files. Echoing the path so callers can capture it.
    local root
    root="$(mktemp -d -t fxlab-d4-XXXXXX)"
    touch "${root}/install.log"
    echo "$root"
}

cleanup_fixture_dir() {
    local root="$1"
    [[ -n "$root" && -d "$root" ]] && rm -rf "$root"
}

prime_env() {
    # Configure all install.sh variables the diagnostic path needs.
    # FXLAB_LOG_DIR is the new (D4) knob for per-service log output —
    # defaults to /var/log/fxlab in production but must be redirectable
    # for tests that cannot write to system dirs.
    local root="$1"
    export FXLAB_LOG_DIR="$root"
    export LOG_FILE="${root}/install.log"
    # Reset INSTALL_ALL_LOGS between tests; each test sets it explicitly.
    unset INSTALL_ALL_LOGS 2>/dev/null || true
}

source_install_sh() {
    # BASH_SOURCE guard at the bottom of install.sh prevents main()
    # from executing on source.
    # shellcheck disable=SC1090
    source "$INSTALL_SH"
}

# ---------------------------------------------------------------------------
# Canned docker-compose state helpers
# ---------------------------------------------------------------------------
#
# These emit the JSON shape `docker compose ps --format json` produces
# (one JSON object per line — not a JSON array). Tests install a
# `docker` function that dispatches to the scenario the test wants.

_emit_ps_single_api_exhausted() {
    # api exited with code 3 (ConfigError per D1 exit(3) convention);
    # compose will not restart it because B3/D1 on-failure:3 is exhausted.
    # redis + postgres are healthy; web is stuck in created (depends_on
    # api, even under service_started it won't start until api container
    # reaches "started" state — and api is in "exited", not "started").
    cat <<'EOF'
{"Service":"api","Name":"fxlab-api","State":"exited","Health":"","ExitCode":3,"Status":"Exited (3) 15 seconds ago"}
{"Service":"redis","Name":"fxlab-redis","State":"running","Health":"healthy","ExitCode":0,"Status":"Up 2 minutes (healthy)"}
{"Service":"postgres","Name":"fxlab-postgres","State":"running","Health":"healthy","ExitCode":0,"Status":"Up 2 minutes (healthy)"}
{"Service":"web","Name":"fxlab-web","State":"created","Health":"","ExitCode":0,"Status":"Created"}
EOF
}

_emit_ps_still_starting() {
    # api is running but healthcheck hasn't passed yet; everything else
    # healthy. This is the "transient" state — NOT an exhaustion.
    cat <<'EOF'
{"Service":"api","Name":"fxlab-api","State":"running","Health":"starting","ExitCode":0,"Status":"Up 5 seconds (health: starting)"}
{"Service":"redis","Name":"fxlab-redis","State":"running","Health":"healthy","ExitCode":0,"Status":"Up 2 minutes (healthy)"}
EOF
}

_emit_ps_unhealthy_running() {
    # api is running but healthcheck has failed — compose kept it running
    # but marked Health=unhealthy. Distinct from exhausted.
    cat <<'EOF'
{"Service":"api","Name":"fxlab-api","State":"running","Health":"unhealthy","ExitCode":0,"Status":"Up 3 minutes (unhealthy)"}
{"Service":"redis","Name":"fxlab-redis","State":"running","Health":"healthy","ExitCode":0,"Status":"Up 3 minutes (healthy)"}
EOF
}

_emit_ps_all_healthy() {
    cat <<'EOF'
{"Service":"api","Name":"fxlab-api","State":"running","Health":"healthy","ExitCode":0,"Status":"Up 2 minutes (healthy)"}
{"Service":"redis","Name":"fxlab-redis","State":"running","Health":"healthy","ExitCode":0,"Status":"Up 2 minutes (healthy)"}
EOF
}

_emit_ps_two_exhausted() {
    # Simulate a postgres + api double-failure (e.g. wrong POSTGRES_PASSWORD
    # cascades into api migration failure). Both should be named.
    cat <<'EOF'
{"Service":"postgres","Name":"fxlab-postgres","State":"exited","Health":"","ExitCode":1,"Status":"Exited (1) 30 seconds ago"}
{"Service":"api","Name":"fxlab-api","State":"exited","Health":"","ExitCode":3,"Status":"Exited (3) 15 seconds ago"}
{"Service":"redis","Name":"fxlab-redis","State":"running","Health":"healthy","ExitCode":0,"Status":"Up 1 minute (healthy)"}
EOF
}

# ---------------------------------------------------------------------------
# Docker shadow installer
# ---------------------------------------------------------------------------
#
# install_docker_shadow scenario_fn
#   scenario_fn: name of one of the _emit_ps_* functions above
#
# After install, any call to `docker compose ...` inside install.sh
# functions routes to the shadow instead of the real docker binary.

install_docker_shadow() {
    local ps_emitter="$1"

    # Export the emitter name so the nested function can read it.
    export _D4_TEST_PS_EMITTER="$ps_emitter"

    docker() {
        # Only pattern we intercept: `docker compose -f <file> <subcmd> ...`
        if [[ "${1:-}" != "compose" ]]; then
            echo "unexpected docker invocation: docker $*" >&2
            return 2
        fi
        # Skip past "-f <compose-file>" if present.
        shift
        if [[ "${1:-}" == "-f" ]]; then
            shift 2
        fi

        local subcmd="${1:-}"; shift || true
        case "$subcmd" in
            ps)
                # Emit canned JSON only when --format json is requested.
                # For other ps invocations (no --format), emit a simple
                # table so the calling code's `| tee -a` doesn't choke.
                local want_json=0
                for arg in "$@"; do
                    [[ "$arg" == "json" ]] && want_json=1
                done
                if [[ "$want_json" -eq 1 ]]; then
                    "${_D4_TEST_PS_EMITTER}"
                else
                    echo "NAME                STATE"
                    "${_D4_TEST_PS_EMITTER}" | \
                        python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    svc = json.loads(line)
    print(f\"{svc.get('Name','?'):<20}{svc.get('State','?')}\")
"
                fi
                ;;
            logs)
                # Find the service name after any flags (--tail N etc.).
                # Strategy: the service name is the last positional arg,
                # which is the last token that does not start with '-'
                # and is not a numeric flag value.
                local svc="" prev=""
                for arg in "$@"; do
                    if [[ "$arg" != -* ]] && [[ "$prev" != "--tail" ]]; then
                        svc="$arg"
                    fi
                    prev="$arg"
                done
                # Emit distinctive canned log content so the tests can
                # verify that the RIGHT service's logs ended up in the
                # banner and the per-service log files.
                echo "[CANNED-LOG ${svc}] line-1"
                echo "[CANNED-LOG ${svc}] line-2"
                echo "[CANNED-LOG ${svc}] line-3"
                ;;
            *)
                # Silently accept any other compose subcommand — the
                # diagnostic path shouldn't call them, but be defensive.
                return 0
                ;;
        esac
    }
    export -f docker
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test_banner_names_failed_service_in_first_20_lines() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_single_api_exhausted

    local output first_20
    output="$(_report_install_failure 2>&1)" || true
    # Take the first 20 lines so the assertion tracks the acceptance
    # criterion from the remediation doc.
    first_20="$(printf '%s\n' "$output" | head -n 20)"

    assert_contains "$first_20" "api" "api must be named in the first 20 lines" || return 1
    assert_contains "$first_20" "FAILED" "first 20 lines must carry a FAILED banner" || return 1
}

test_exhausted_classification_is_shown() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_single_api_exhausted

    local output
    output="$(_report_install_failure 2>&1)" || true

    assert_contains "$output" "restart budget exhausted" \
        "exited+nonzero service must be labeled 'restart budget exhausted'" || return 1
    # The exit code is the operator's hint — D1 exit(3) means ConfigError.
    assert_contains "$output" "exit code 3" \
        "exit code must be surfaced alongside the classification" || return 1
}

test_still_starting_is_classified_distinctly_from_exhausted() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_still_starting

    local output
    output="$(_report_install_failure 2>&1)" || true

    assert_contains "$output" "still starting" \
        "running+health=starting must be labeled 'still starting'" || return 1
    assert_not_contains "$output" "restart budget exhausted" \
        "still-starting must not be confused with exhausted" || return 1
}

test_unhealthy_running_is_classified_distinctly() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_unhealthy_running

    local output
    output="$(_report_install_failure 2>&1)" || true

    assert_contains "$output" "unhealthy" \
        "running+health=unhealthy must be labeled as such" || return 1
    assert_not_contains "$output" "restart budget exhausted" \
        "unhealthy-running must not be confused with exhausted" || return 1
}

test_healthy_services_are_not_in_output() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_single_api_exhausted

    local output
    output="$(_report_install_failure 2>&1)" || true

    # redis/postgres are healthy in this scenario — their canned log
    # content ([CANNED-LOG redis] / [CANNED-LOG postgres]) must NOT
    # appear in the banner output. This is the 2026-04-15 "stop
    # interleaving all containers' logs" fix.
    assert_not_contains "$output" "[CANNED-LOG redis]" \
        "healthy redis logs must not be dumped" || return 1
    assert_not_contains "$output" "[CANNED-LOG postgres]" \
        "healthy postgres logs must not be dumped" || return 1
    # api IS unhealthy → its logs should be present.
    assert_contains "$output" "[CANNED-LOG api]" \
        "failing service's logs must be dumped" || return 1
}

test_per_service_log_file_is_created() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_single_api_exhausted

    local output
    output="$(_report_install_failure 2>&1)" || true

    # The per-service log file path must appear in the banner output so
    # the operator can locate it from the install output alone.
    # Filename convention: failed-<service>-<timestamp>.log
    local matched_path
    matched_path="$(printf '%s\n' "$output" | \
        grep -oE "${root}/failed-api-[0-9]+\.log" | head -n 1)"
    [[ -n "$matched_path" ]] || {
        echo "    FAIL: no per-service log path matched pattern 'failed-api-<ts>.log'"
        echo "      output (first 400): ${output:0:400}"
        return 1
    }
    assert_file_exists "$matched_path" "per-service log file must exist on disk" || return 1
    # File contents must be the canned log for the failing service.
    local contents
    contents="$(cat "$matched_path")"
    assert_contains "$contents" "[CANNED-LOG api]" \
        "per-service log file must contain the failing service's logs" || return 1
}

test_no_log_file_for_healthy_services() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_single_api_exhausted

    _report_install_failure >/dev/null 2>&1 || true

    # redis and postgres are healthy in this scenario — no file should
    # be written for them.
    local stray
    stray="$(find "$root" -maxdepth 1 -name 'failed-redis-*.log' -o -name 'failed-postgres-*.log' 2>/dev/null || true)"
    assert_eq "" "$stray" "no per-service log files should exist for healthy services" || return 1
}

test_multiple_failures_all_named_in_banner() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_two_exhausted

    local output first_20
    output="$(_report_install_failure 2>&1)" || true
    first_20="$(printf '%s\n' "$output" | head -n 20)"

    assert_contains "$first_20" "postgres" "postgres must be named in first 20 lines" || return 1
    assert_contains "$first_20" "api" "api must be named in first 20 lines" || return 1
}

test_all_logs_mode_dumps_full_logs_to_stdout() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    export INSTALL_ALL_LOGS=1
    source_install_sh
    install_docker_shadow _emit_ps_single_api_exhausted

    local output
    output="$(_report_install_failure 2>&1)" || true

    # In --all-logs mode the failing service's logs appear inline
    # (behavior same as default for the failing service) AND a banner
    # line records that --all-logs mode is active so the operator isn't
    # surprised.
    assert_contains "$output" "INSTALL_ALL_LOGS=1" \
        "all-logs mode must be announced so the operator understands why the output is large" || return 1
    assert_contains "$output" "[CANNED-LOG api]" \
        "all-logs mode must still show failing service logs" || return 1
    # In --all-logs mode, no per-service files should be written — the
    # operator opted into stdout dumping.
    local stray
    stray="$(find "$root" -maxdepth 1 -name 'failed-*.log' 2>/dev/null || true)"
    assert_eq "" "$stray" "all-logs mode must not create per-service log files" || return 1
}

test_all_healthy_produces_no_banner() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_all_healthy

    local output
    output="$(_report_install_failure 2>&1)" || true

    # When every service is healthy, the diagnostic banner must NOT
    # fire — calling _report_install_failure on a healthy stack
    # returns cleanly without a noisy "FAILED" announcement.
    assert_not_contains "$output" "FAILED SERVICES" \
        "healthy stack must not emit a FAILED banner" || return 1
}

test_identify_unhealthy_services_emits_tsv() {
    local root; root="$(make_fixture_dir)"
    trap "cleanup_fixture_dir '$root'" RETURN

    prime_env "$root"
    source_install_sh
    install_docker_shadow _emit_ps_single_api_exhausted

    # The underlying identification helper should be callable on its
    # own (it's the building block _report_install_failure composes).
    # It reads JSON from stdin and emits one TSV line per unhealthy
    # service: "<service>\t<classification>\t<exit_code>".
    local lines
    lines="$(_emit_ps_single_api_exhausted | _identify_unhealthy_services)"

    # Must contain exactly one line for api (exhausted) and one for
    # web (created — blocked on deps). Healthy services must be absent.
    local api_line web_line redis_line
    api_line="$(printf '%s\n' "$lines" | grep $'^api\t' || true)"
    web_line="$(printf '%s\n' "$lines" | grep $'^web\t' || true)"
    redis_line="$(printf '%s\n' "$lines" | grep $'^redis\t' || true)"

    [[ -n "$api_line" ]] || { echo "    FAIL: api not in identifier output"; echo "    got: $lines"; return 1; }
    [[ -n "$web_line" ]] || { echo "    FAIL: web (created) not in identifier output"; echo "    got: $lines"; return 1; }
    assert_eq "" "$redis_line" "healthy redis must be excluded" || return 1

    assert_contains "$api_line" "exhausted" "api must be classified as exhausted" || return 1
    assert_contains "$api_line" $'\t3' "api exit code 3 must be in the TSV" || return 1
    assert_contains "$web_line" "blocked" "web (created) must be classified as blocked" || return 1
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$INSTALL_SH" ]]; then
        echo "ERROR: install.sh not found at ${INSTALL_SH}"
        exit 2
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: python3 required for JSON fixture emission"
        exit 2
    fi

    echo "install.sh D4 diagnostic test suite"
    echo "-----------------------------------"

    run_test "banner names failed service in first 20 lines"            test_banner_names_failed_service_in_first_20_lines
    run_test "exhausted classification surfaces exit code"              test_exhausted_classification_is_shown
    run_test "still-starting classified distinctly from exhausted"      test_still_starting_is_classified_distinctly_from_exhausted
    run_test "unhealthy-running classified distinctly"                  test_unhealthy_running_is_classified_distinctly
    run_test "healthy services' logs are not in output"                 test_healthy_services_are_not_in_output
    run_test "per-service log file is written for each failure"         test_per_service_log_file_is_created
    run_test "no per-service log file for healthy services"             test_no_log_file_for_healthy_services
    run_test "multiple failures all named in banner"                    test_multiple_failures_all_named_in_banner
    run_test "--all-logs mode dumps full logs to stdout"                test_all_logs_mode_dumps_full_logs_to_stdout
    run_test "all-healthy input produces no banner"                     test_all_healthy_produces_no_banner
    run_test "_identify_unhealthy_services emits well-formed TSV"       test_identify_unhealthy_services_emits_tsv

    echo
    echo "-----------------------------------"
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

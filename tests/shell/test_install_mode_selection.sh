#!/usr/bin/env bash
# ===========================================================================
# Tests for install.sh install-mode selection and teardown flow
# ===========================================================================
#
# Purpose:
#     Pin the user-facing install-mode selection introduced after the
#     2026-04-16 minitux reinstall failure (port 80 in use by old
#     docker-proxy). install.sh must:
#
#       1. Detect existing FXLab Docker artifacts (containers, volumes)
#          regardless of whether .env exists (the "reinstall" scenario
#          is: user deleted /opt/fxlab but old containers are running).
#
#       2. When artifacts exist, prompt the user to choose between a
#          "fresh" install (full teardown) or "refresh" (pull code,
#          rebuild, restart — preserves data).
#
#       3. Offer --fresh and --refresh CLI flags for non-interactive use.
#
#       4. Tear down existing containers/volumes/images BEFORE the port
#          check (fresh mode). The 2026-04-16 failure occurred because
#          check_ports() ran before build_and_start()'s stale-state
#          cleanup, so the old docker-proxy was still holding port 80.
#
#       5. The update/refresh path must skip the port check (existing
#          containers legitimately hold ports).
#
# Why structural tests (not functional):
#     install.sh runs as root, calls docker, and modifies the host. We
#     assert structural invariants of the script text — function
#     existence, call order, flag parsing — without needing a live
#     Docker daemon.
#
# Run:
#     bash tests/shell/test_install_mode_selection.sh
#
# Exit code:
#     0 — all tests passed.
#     1 — at least one test failed.
# ===========================================================================

set -uo pipefail

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

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

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSTALL_SH="${REPO_ROOT}/install.sh"

# ---------------------------------------------------------------------------
# Helper: extract a function body from install.sh
# ---------------------------------------------------------------------------
extract_function() {
    local fn_name="$1"
    awk -v fn="$fn_name" '
        $0 ~ "^" fn "\\(\\)" { capturing = 1; print; next }
        capturing && /^[a-zA-Z_]+\(\)/ { capturing = 0 }
        capturing && /^}/ { print; capturing = 0; next }
        capturing { print }
    ' "$INSTALL_SH"
}

# ---------------------------------------------------------------------------
# 1. Docker artifact detection
# ---------------------------------------------------------------------------

test_detect_mode_checks_docker_artifacts() {
    # detect_mode (or the mode selection flow) must probe for existing
    # FXLab Docker containers or volumes — not rely solely on .env.
    # Without this, a reinstall (deleted /opt/fxlab, old containers
    # running) is classified as "fresh" and the port check fails.
    local body
    body="$(cat "$INSTALL_SH")"

    # Must check for docker containers or volumes somewhere in the
    # mode detection logic
    if ! echo "$body" | grep -qE 'docker (compose.*ps|ps.*fxlab|volume)'; then
        echo "    FAIL: install.sh does not check for existing Docker artifacts during mode detection"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 2. Interactive mode prompt
# ---------------------------------------------------------------------------

test_install_has_mode_prompt() {
    # When existing artifacts are detected, install.sh must present
    # the user with a choice. Look for the prompt text.
    local body
    body="$(cat "$INSTALL_SH")"

    if ! echo "$body" | grep -qiE '(fresh|clean).*(install|start)|refresh.*pull.*restart|select.*\['; then
        echo "    FAIL: install.sh does not prompt for fresh vs refresh install mode"
        return 1
    fi
}

test_prompt_offers_fresh_option() {
    # The prompt must offer a "fresh install" that tears everything down.
    local body
    body="$(cat "$INSTALL_SH")"

    if ! echo "$body" | grep -qiE 'fresh.*(install|teardown|clean|remove)|stop.*services.*remove'; then
        echo "    FAIL: prompt does not describe a fresh install / teardown option"
        return 1
    fi
}

test_prompt_offers_refresh_option() {
    # The prompt must offer a "refresh" that preserves data.
    local body
    body="$(cat "$INSTALL_SH")"

    if ! echo "$body" | grep -qiE 'refresh.*pull.*code|refresh.*rebuild|preserv'; then
        echo "    FAIL: prompt does not describe a refresh / code-update option"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 3. CLI flags for non-interactive use
# ---------------------------------------------------------------------------

test_fresh_flag_is_parsed() {
    # --fresh must be a recognized CLI argument.
    if ! grep -qE -- '--fresh\)' "$INSTALL_SH"; then
        echo "    FAIL: install.sh does not parse --fresh flag"
        return 1
    fi
}

test_refresh_flag_is_parsed() {
    # --refresh must be a recognized CLI argument.
    if ! grep -qE -- '--refresh\)' "$INSTALL_SH"; then
        echo "    FAIL: install.sh does not parse --refresh flag"
        return 1
    fi
}

test_flags_documented_in_help() {
    # Both flags must appear in the --help output.
    local help_section
    help_section="$(awk '/^  *-h\|--help/,/exit 0/' "$INSTALL_SH")"

    local ok=0
    echo "$help_section" | grep -q -- '--fresh' || { echo "    FAIL: --fresh not in --help"; return 1; }
    echo "$help_section" | grep -q -- '--refresh' || { echo "    FAIL: --refresh not in --help"; return 1; }
}

# ---------------------------------------------------------------------------
# 4. Teardown function and ordering
# ---------------------------------------------------------------------------

test_teardown_existing_function_exists() {
    # A dedicated teardown function must exist for the fresh-install path.
    if ! grep -qE '^teardown_existing\(\)' "$INSTALL_SH"; then
        echo "    FAIL: install.sh does not define teardown_existing()"
        return 1
    fi
}

test_teardown_removes_containers_and_volumes() {
    # The teardown must remove containers, volumes, and optionally images.
    local body
    body="$(extract_function teardown_existing)"

    if ! echo "$body" | grep -qE 'docker compose.*down.*--volumes|docker.*rm|docker.*volume'; then
        echo "    FAIL: teardown_existing() does not remove containers/volumes"
        return 1
    fi
}

test_teardown_removes_images() {
    # Fresh install should also remove old FXLab images to avoid stale layers.
    local body
    body="$(extract_function teardown_existing)"

    if ! echo "$body" | grep -qE 'rmi|--rmi'; then
        echo "    FAIL: teardown_existing() does not remove Docker images"
        return 1
    fi
}

test_teardown_runs_before_port_check() {
    # Critical ordering: teardown_existing must be called BEFORE
    # check_ports in main(). This is the actual bug that caused the
    # 2026-04-16 failure — the old containers held port 80, and
    # check_ports killed the script before teardown ever ran.
    #
    # We filter out comment lines (starting with # after optional
    # whitespace) so references in inline documentation do not
    # produce false matches.
    local main_body
    main_body="$(awk '/^main\(\)/,/^}/' "$INSTALL_SH" | grep -v '^[[:space:]]*#')"

    local teardown_line port_line
    teardown_line="$(echo "$main_body" | grep -nE 'teardown_existing' | head -1 | cut -d: -f1)"
    port_line="$(echo "$main_body" | grep -nE 'check_ports' | head -1 | cut -d: -f1)"

    if [[ -z "$teardown_line" ]]; then
        echo "    FAIL: teardown_existing not called in main()"
        return 1
    fi
    if [[ -z "$port_line" ]]; then
        echo "    FAIL: check_ports not called in main()"
        return 1
    fi
    if [[ "$teardown_line" -ge "$port_line" ]]; then
        echo "    FAIL: teardown_existing (line $teardown_line) runs at or after check_ports (line $port_line)"
        echo "    The old containers hold the ports — teardown must happen first."
        return 1
    fi
}

test_update_mode_still_skips_port_check() {
    # Refresh/update mode must continue to skip the port check.
    # (Existing services legitimately hold the ports.)
    local body
    body="$(extract_function check_ports)"

    if ! echo "$body" | grep -qE 'update.*skip|refresh.*skip|INSTALL_MODE.*(update|refresh)'; then
        echo "    FAIL: check_ports does not skip in update/refresh mode"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 5. Non-interactive safety
# ---------------------------------------------------------------------------

test_non_interactive_requires_flag() {
    # If stdin is not a terminal (piped/scripted), the script must not
    # hang waiting for input. It should require --fresh or --refresh.
    local body
    body="$(cat "$INSTALL_SH")"

    # Must check for terminal (tty) or detect non-interactive mode
    if ! echo "$body" | grep -qE 'tty|isatty|/dev/tty|\-t 0|\-t 1|INSTALL_MODE_FLAG'; then
        echo "    FAIL: install.sh does not detect non-interactive mode for the install prompt"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

main() {
    if [[ ! -f "$INSTALL_SH" ]]; then
        echo "ERROR: install.sh not found at ${INSTALL_SH}"
        exit 2
    fi

    echo "install-mode selection & teardown test suite"
    echo "---------------------------------------------"

    run_test "detection: checks Docker artifacts, not just .env"      test_detect_mode_checks_docker_artifacts
    run_test "prompt: offers install mode selection"                   test_install_has_mode_prompt
    run_test "prompt: describes fresh install option"                  test_prompt_offers_fresh_option
    run_test "prompt: describes refresh option"                        test_prompt_offers_refresh_option
    run_test "cli: --fresh flag is parsed"                             test_fresh_flag_is_parsed
    run_test "cli: --refresh flag is parsed"                           test_refresh_flag_is_parsed
    run_test "cli: flags documented in --help"                         test_flags_documented_in_help
    run_test "teardown: teardown_existing() function exists"           test_teardown_existing_function_exists
    run_test "teardown: removes containers and volumes"                test_teardown_removes_containers_and_volumes
    run_test "teardown: removes images"                                test_teardown_removes_images
    run_test "ordering: teardown runs before port check"               test_teardown_runs_before_port_check
    run_test "ordering: update/refresh mode still skips port check"    test_update_mode_still_skips_port_check
    run_test "safety: non-interactive mode requires CLI flag"          test_non_interactive_requires_flag

    echo
    echo "---------------------------------------------"
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

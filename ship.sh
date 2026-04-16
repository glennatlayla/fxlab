#!/usr/bin/env bash
# ===========================================================================
# FXLab — Ship Script
# ===========================================================================
#
# Quality-gated commit-and-push to main with optional AI-assisted auto-fix.
#
# Usage:
#   ./ship.sh                           # Auto-generate commit message
#   ./ship.sh "feat: add kill switch"   # Custom commit message
#   ./ship.sh --dry-run                 # Run gates only, no commit/push
#   ./ship.sh --skip-tests              # Skip pytest (format + lint only)
#   ./ship.sh --no-ai                   # Fail on errors, no auto-fix
#
# Requirements:
#   - Working Python venv at .venv/ with ruff, pytest installed
#   - Git configured with SSH access to origin
#   - Claude Code CLI (optional): npm i -g @anthropic-ai/claude-code
#
# ===========================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${SCRIPT_DIR}/.venv"
BRANCH="main"
MAX_AI_FIX_ATTEMPTS=2

# Source directories — only these are linted/formatted/tested
SRC_DIRS=(services/ libs/ tests/)

# All project directories that should be tracked in git.
# commit_and_push() stages these; preflight warns about untracked files in them.
PROJECT_DIRS=(
    services/ libs/ tests/ frontend/ migrations/
    deploy/ config/ infra/ scripts/ docs/
)

# Tool commands — set in preflight() after locating Python
PY=()      # e.g. ("/path/to/.venv/bin/python")
RUFF=()    # e.g. ("/path/to/.venv/bin/python" -m ruff)
PYTEST=()  # e.g. ("/path/to/.venv/bin/python" -m pytest)

# Colors (empty if not a terminal)
if [[ -t 1 ]]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; NC=''
fi

# Flags
DRY_RUN=0
SKIP_TESTS=0
NO_AI=0
COMMIT_MSG=""

# Temp file tracking for cleanup
TEMP_FILES=()

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)    DRY_RUN=1; shift ;;
        --skip-tests) SKIP_TESTS=1; shift ;;
        --no-ai)      NO_AI=1; shift ;;
        --help|-h)
            sed -n '2,/^$/{ s/^# //; s/^#$//; p; }' "$0"
            exit 0
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}" >&2
            echo "Run ./ship.sh --help for usage." >&2
            exit 1
            ;;
        *)
            COMMIT_MSG="$1"; shift ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

step()     { echo -e "\n${BLUE}${BOLD}==>${NC} ${BOLD}$1${NC}"; }
ok()       { echo -e "${GREEN}[PASS]${NC} $1"; }
warn()     { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail_msg() { echo -e "${RED}[FAIL]${NC} $1"; }

# Create a temp file and register it for cleanup on exit
make_temp() {
    local f
    f="$(mktemp /tmp/fxlab-ship-XXXXXX)"
    TEMP_FILES+=("$f")
    echo "$f"
}

cleanup() {
    for f in ${TEMP_FILES[@]+"${TEMP_FILES[@]}"}; do
        rm -f "$f"
    done
}
trap cleanup EXIT

# Global error trap — never die silently.
# set -e can terminate the script from any uncaught non-zero exit deep in
# a pipeline or command substitution.  Without this trap, the user sees
# the script stop mid-output with no explanation.  The trap fires on ERR,
# prints the line that killed us, and exits non-zero so CI catches it.
_on_error() {
    local line_no="$1"
    echo "" >&2
    echo -e "${RED}${BOLD}ship.sh: unexpected failure at line ${line_no}.${NC}" >&2
    echo -e "Re-run with ${BOLD}bash -x ./ship.sh${NC} for a full trace." >&2
    exit 1
}
trap '_on_error ${LINENO}' ERR

has_claude_code() {
    command -v claude &>/dev/null
}

# Run a command, show output on failure. Returns the command's exit code.
# Usage: run_showing_errors "Label" cmd arg1 arg2 ...
run_showing_errors() {
    local label="$1"; shift
    local outfile
    outfile="$(make_temp)"

    if "$@" > "$outfile" 2>&1; then
        ok "$label"
        return 0
    else
        local rc=$?
        fail_msg "$label (exit ${rc})"
        if [[ -s "$outfile" ]]; then
            echo -e "${YELLOW}--- last 40 lines ---${NC}"
            tail -40 "$outfile"
            echo -e "${YELLOW}--- end ---${NC}"
        fi
        # Store for AI repair
        LAST_GATE_OUTPUT="$outfile"
        return "$rc"
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight: validate environment
# ---------------------------------------------------------------------------

preflight() {
    step "Pre-flight checks"

    # Must be a git repo
    if ! git rev-parse --is-inside-work-tree &>/dev/null; then
        echo -e "${RED}Not a git repository.${NC}" >&2; exit 1
    fi

    # Must be on the right branch
    local current_branch
    current_branch="$(git rev-parse --abbrev-ref HEAD)"
    if [[ "$current_branch" != "$BRANCH" ]]; then
        echo -e "${RED}Not on ${BRANCH} (currently on ${current_branch}).${NC}" >&2
        echo "Switch first: git checkout ${BRANCH}" >&2
        exit 1
    fi

    # --------------- Python / venv validation ---------------

    # Step 1: venv must exist
    if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
        echo -e "${RED}No venv at ${VENV_DIR}${NC}" >&2
        echo "Create it:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
        exit 1
    fi

    # Step 2: the venv's Python must actually work
    local venv_python="${VENV_DIR}/bin/python"
    if ! [[ -x "$venv_python" ]] || ! "$venv_python" -c "import sys" 2>/dev/null; then
        # Broken symlink — try to auto-repair
        if ! repair_venv; then
            # repair_venv already printed instructions
            exit 1
        fi
    fi

    # Step 3: verify the interpreter + packages
    PY=("$venv_python")
    if ! "${PY[@]}" -c "import ruff" 2>/dev/null; then
        echo -e "${RED}ruff not installed in venv.${NC}" >&2
        echo "Run:  ${VENV_DIR}/bin/pip install ruff" >&2
        exit 1
    fi
    if ! "${PY[@]}" -c "import pytest" 2>/dev/null; then
        echo -e "${RED}pytest not installed in venv.${NC}" >&2
        echo "Run:  ${VENV_DIR}/bin/pip install pytest" >&2
        exit 1
    fi

    RUFF=("${PY[@]}" -m ruff)
    PYTEST=("${PY[@]}" -m pytest)

    ok "Python: $("${PY[@]}" --version 2>&1) at ${venv_python}"

    # --------------- Node.js / npm (via nodeenv) ---------------
    # nodeenv installs Node.js and npm into .venv/bin so the entire
    # toolchain (Python + Node) lives inside the venv. This ensures
    # 'npm run build' works in tests without requiring a system Node install.

    # Ensure .venv/bin is on PATH so subprocess calls (e.g. from pytest)
    # can find npm without needing an absolute path.
    export PATH="${VENV_DIR}/bin:${PATH}"

    local npm_bin="${VENV_DIR}/bin/npm"
    local node_bin="${VENV_DIR}/bin/node"

    if [[ ! -x "$node_bin" ]] || [[ ! -x "$npm_bin" ]]; then
        echo -e "  ${BLUE}Installing Node.js LTS into venv via nodeenv...${NC}"

        if ! "${PY[@]}" -c "import nodeenv" 2>/dev/null; then
            echo -e "${RED}nodeenv not installed in venv.${NC}" >&2
            echo "Run:  ${VENV_DIR}/bin/pip install nodeenv" >&2
            exit 1
        fi

        if ! "${PY[@]}" -m nodeenv --python-virtualenv --node=lts --prebuilt "$VENV_DIR" 2>&1; then
            echo -e "${RED}nodeenv failed to install Node.js into venv.${NC}" >&2
            echo "Try manually:  ${VENV_DIR}/bin/python -m nodeenv --python-virtualenv --node=lts --prebuilt .venv" >&2
            exit 1
        fi

        # Verify installation succeeded
        if [[ ! -x "$npm_bin" ]]; then
            echo -e "${RED}nodeenv ran but npm not found at ${npm_bin}.${NC}" >&2
            exit 1
        fi
    fi

    ok "Node: $("$node_bin" --version 2>&1), npm: $("$npm_bin" --version 2>&1)"

    # --------------- Git state ---------------

    if [[ "$DRY_RUN" -eq 0 ]]; then
        # Anything to ship?
        if git diff --quiet && git diff --cached --quiet \
           && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
            echo -e "${YELLOW}Nothing to ship — working tree is clean.${NC}"
            exit 0
        fi

        # Remote configured?
        local remote_url
        remote_url="$(git remote get-url origin 2>/dev/null || echo "")"
        if [[ -z "$remote_url" ]]; then
            echo -e "${RED}No 'origin' remote configured.${NC}" >&2
            echo "Add one: git remote add origin git@github.com:glennatlayla/fxlab.git" >&2
            exit 1
        fi
        ok "Remote: ${remote_url}"
    fi

    # --------------- Optional: Claude Code CLI ---------------

    if [[ "$NO_AI" -eq 0 ]] && ! has_claude_code; then
        warn "Claude Code CLI not found — AI auto-fix disabled."
        NO_AI=1
    fi

    ok "Pre-flight passed"
}

# ---------------------------------------------------------------------------
# Venv repair — called only when .venv/bin/python is broken
# ---------------------------------------------------------------------------

repair_venv() {
    local pyvenv_cfg="${VENV_DIR}/pyvenv.cfg"
    if [[ ! -f "$pyvenv_cfg" ]]; then
        echo -e "${RED}.venv exists but has no pyvenv.cfg — cannot determine Python version.${NC}" >&2
        echo "Rebuild:  python3 -m venv .venv --clear && .venv/bin/pip install -r requirements.txt" >&2
        return 1
    fi

    # What Python version built this venv? e.g. "3.12"
    local venv_py_ver
    venv_py_ver="$(grep -E '^version\s*=' "$pyvenv_cfg" \
        | sed 's/^version[[:space:]]*=[[:space:]]*//' \
        | cut -d. -f1,2 \
        | tr -d '[:space:]')"

    if [[ -z "$venv_py_ver" ]]; then
        echo -e "${RED}Cannot parse Python version from pyvenv.cfg.${NC}" >&2
        echo "Rebuild:  python3 -m venv .venv --clear && .venv/bin/pip install -r requirements.txt" >&2
        return 1
    fi

    warn "Venv broken — was built with Python ${venv_py_ver}"

    # Search for a matching interpreter
    local found_python=""
    local search_paths=(
        # pyvenv.cfg records where the original Python lived
        "$(grep -E '^home\s*=' "$pyvenv_cfg" | sed 's/^home[[:space:]]*=[[:space:]]*//' | tr -d '[:space:]')/python3"
        # Common Homebrew locations (Apple Silicon + Intel)
        "/opt/homebrew/bin/python${venv_py_ver}"
        "/usr/local/bin/python${venv_py_ver}"
        "/opt/homebrew/opt/python@${venv_py_ver}/bin/python3"
        "/usr/local/opt/python@${venv_py_ver}/bin/python3"
    )

    for candidate in "${search_paths[@]}"; do
        if [[ -x "$candidate" ]] && "$candidate" -c "pass" 2>/dev/null; then
            found_python="$candidate"
            break
        fi
    done

    if [[ -z "$found_python" ]]; then
        echo "" >&2
        echo -e "${RED}Python ${venv_py_ver} not found on this system.${NC}" >&2
        echo "" >&2
        echo -e "  ${BOLD}Option A — Install it:${NC}  brew install python@${venv_py_ver}" >&2
        echo -e "  ${BOLD}Option B — Rebuild venv:${NC}" >&2
        echo -e "    python3 -m venv .venv --clear" >&2
        echo -e "    .venv/bin/pip install -r requirements.txt" >&2
        echo "" >&2
        return 1
    fi

    echo -e "  Found python${venv_py_ver} at ${found_python}"
    echo -e "  ${BLUE}Repairing venv...${NC}"

    # Python's venv module chokes on dangling symlinks in the bin dir.
    # Remove them before re-creating so 'python -m venv' can write fresh ones.
    local bin_dir="${VENV_DIR}/bin"
    if [[ -d "$bin_dir" ]]; then
        find "$bin_dir" -maxdepth 1 -type l ! -exec test -e {} \; -delete 2>/dev/null || true
    fi

    # 'python -m venv <dir>' on an existing venv rebuilds symlinks
    # without wiping site-packages. Show errors — don't swallow them.
    local repair_log
    repair_log="$(make_temp)"

    if "$found_python" -m venv "$VENV_DIR" > "$repair_log" 2>&1; then
        local venv_python="${VENV_DIR}/bin/python"
        if [[ -x "$venv_python" ]] && "$venv_python" -c "import sys" 2>/dev/null; then
            ok "Venv repaired"
            return 0
        fi
    fi

    # Show what went wrong
    echo -e "${RED}Venv repair failed:${NC}" >&2
    cat "$repair_log" >&2
    echo "" >&2
    echo "Rebuild manually:" >&2
    echo "  ${found_python} -m venv .venv --clear" >&2
    echo "  .venv/bin/pip install -r requirements.txt" >&2
    return 1
}

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

run_quality_gates() {
    step "Quality gates"

    local all_passed=1
    LAST_GATE_OUTPUT=""

    # Gate 1: Format — auto-fix is always safe for formatting
    if ! run_showing_errors "Format (ruff)" "${RUFF[@]}" format --check "${SRC_DIRS[@]}"; then
        echo -e "  ${BLUE}Auto-formatting...${NC}"
        if "${RUFF[@]}" format "${SRC_DIRS[@]}"; then
            ok "Format — auto-fixed"
        else
            fail_msg "ruff format itself errored — check ruff installation"
            all_passed=0
        fi
    fi

    # Gate 2: Lint — try ruff --fix, then AI, then fail
    if ! run_showing_errors "Lint (ruff)" "${RUFF[@]}" check "${SRC_DIRS[@]}"; then
        echo -e "  ${BLUE}Applying ruff auto-fixes...${NC}"
        "${RUFF[@]}" check --fix "${SRC_DIRS[@]}" 2>&1 || true

        if ! run_showing_errors "Lint — after auto-fix" "${RUFF[@]}" check "${SRC_DIRS[@]}"; then
            try_ai_repair "Lint (ruff)" "${RUFF[@]}" check "${SRC_DIRS[@]}" || all_passed=0
        fi
    fi

    # Gate 3: Type-check — non-blocking (183 pre-existing errors)
    if ! run_showing_errors "Type-check (mypy)" "${PY[@]}" -m mypy services/ libs/ \
            --ignore-missing-imports --no-strict-optional; then
        warn "Type-check — non-blocking (pre-existing errors)"
    fi

    # Gate 4: Tests
    if [[ "$SKIP_TESTS" -eq 0 ]]; then
        # Run unit tests first (fast, no app import required)
        if ! run_showing_errors "Tests (unit)" "${PYTEST[@]}" tests/unit/ -q --tb=short; then
            try_ai_repair "Tests (unit)" "${PYTEST[@]}" tests/unit/ -q --tb=short || all_passed=0
        fi
    else
        warn "Tests skipped (--skip-tests)"
    fi

    if [[ "$all_passed" -eq 0 ]]; then
        echo -e "\n${RED}${BOLD}Quality gates failed.${NC} Fix the issues above and retry."
        exit 1
    fi

    ok "All quality gates passed"
}

# ---------------------------------------------------------------------------
# AI-assisted repair (optional, requires Claude Code CLI)
# ---------------------------------------------------------------------------

try_ai_repair() {
    local name="$1"; shift
    # Remaining args are the command to re-run (preserves quoting/spaces)
    local cmd=("$@")
    # Flattened string for display in AI prompt only — never executed as-is
    local cmd_display="$*"

    if [[ "$NO_AI" -eq 1 ]]; then
        fail_msg "${name} — fix manually (AI auto-fix not available)"
        return 1
    fi

    local error_text=""
    if [[ -n "$LAST_GATE_OUTPUT" ]] && [[ -s "$LAST_GATE_OUTPUT" ]]; then
        error_text="$(tail -80 "$LAST_GATE_OUTPUT")"
    fi

    for attempt in $(seq 1 "$MAX_AI_FIX_ATTEMPTS"); do
        echo -e "  ${BLUE}AI fix attempt ${attempt}/${MAX_AI_FIX_ATTEMPTS}...${NC}"

        local prompt
        prompt="The following quality gate failed in the FXLab project:

Gate: ${name}
Command: ${cmd_display}

Error output:
\`\`\`
${error_text}
\`\`\`

Fix the issues that caused this gate to fail. Make minimal, targeted fixes.
Do not add stubs, TODOs, or placeholder code. Do not run any commands."

        if claude --print -p "$prompt" 2>/dev/null; then
            # Re-run the gate using the properly-quoted command array
            if run_showing_errors "${name} — after AI fix" "${cmd[@]}"; then
                return 0
            fi
            # Update error text for next attempt
            if [[ -n "$LAST_GATE_OUTPUT" ]] && [[ -s "$LAST_GATE_OUTPUT" ]]; then
                error_text="$(tail -80 "$LAST_GATE_OUTPUT")"
            fi
        else
            fail_msg "${name} — Claude could not auto-fix"
            return 1
        fi
    done

    fail_msg "${name} — still failing after ${MAX_AI_FIX_ATTEMPTS} AI attempts"
    return 1
}

# ---------------------------------------------------------------------------
# Commit & push
# ---------------------------------------------------------------------------

commit_and_push() {
    # Stage, commit, push, and verify that the commit reaches the remote.
    #
    # Every critical operation (stage, commit, push, verify) is wrapped in
    # explicit error handling with a descriptive message.  The script must
    # NEVER die silently in this function — a silent failure here means
    # code passes quality gates but never deploys, which is worse than a
    # loud test failure.
    #
    # Flow:
    #   1. Detect and stage untracked project files.
    #   2. Stage all project directories + root config files + tracked mods.
    #   3. Generate commit message (AI with timeout → deterministic fallback).
    #   4. Commit with explicit error capture.
    #   5. Post-commit: verify no project files remain untracked.
    #   6. Push with retry and explicit error capture.
    #   7. Post-push: verify remote HEAD matches local HEAD.

    step "Commit & push to ${BRANCH}"

    # ---- 1. Safety gate: detect untracked source files ----
    # If any project directory contains untracked files, they won't appear
    # in the commit and the remote clone will be incomplete.  This is the
    # single most common cause of "works locally, fails on deploy".
    local untracked_src=""
    for dir in "${PROJECT_DIRS[@]}"; do
        if [[ -d "$dir" ]]; then
            local found
            found="$(git ls-files --others --exclude-standard -- "$dir" 2>/dev/null | head -20)"
            if [[ -n "$found" ]]; then
                untracked_src+="$found"$'\n'
            fi
        fi
    done

    # Also check standalone project files at repo root.
    local root_files=(
        ship.sh install.sh uninstall.sh build-release.sh
        requirements*.txt pyproject.toml pytest.ini setup.cfg
        .coveragerc .dockerignore .gitignore .env.production.template
        CLAUDE.md README.md README-INSTALL.md DEVELOPMENT.md AUDIT_TRAIL_IMPLEMENTATION.md
        docker-compose*.yml alembic.ini Makefile
    )
    for pattern in "${root_files[@]}"; do
        # shellcheck disable=SC2086
        for f in $pattern; do
            if [[ -f "$f" ]] && ! git ls-files --error-unmatch "$f" &>/dev/null; then
                untracked_src+="$f"$'\n'
            fi
        done
    done

    if [[ -n "$untracked_src" ]]; then
        local untracked_count
        untracked_count="$(echo -n "$untracked_src" | grep -c . || true)"
        warn "${untracked_count} untracked source file(s) found — staging them now:"
        echo "$untracked_src" | head -10 | while IFS= read -r line; do
            [[ -n "$line" ]] && echo -e "  ${YELLOW}+ ${line}${NC}"
        done
        if [[ "$untracked_count" -gt 10 ]]; then
            echo -e "  ${YELLOW}... and $((untracked_count - 10)) more${NC}"
        fi
    fi

    # ---- 2. Stage everything ----
    echo -e "  Staging files..."

    # 2a. All project directories (source, tests, deploy configs, migrations).
    for dir in "${PROJECT_DIRS[@]}"; do
        [[ -d "$dir" ]] && git add -- "$dir" 2>/dev/null || true
    done

    # 2b. Root-level project files (configs, scripts, docs).
    for pattern in "${root_files[@]}"; do
        # shellcheck disable=SC2086
        git add -- $pattern 2>/dev/null || true
    done

    # 2c. Tracked-but-modified files (catches anything the above missed).
    if ! git add -u 2>/dev/null; then
        fail_msg "git add -u failed. Check for index.lock or permission issues."
        echo -e "  Try: ${BOLD}rm -f .git/index.lock${NC}" >&2
        exit 1
    fi

    if git diff --cached --quiet; then
        warn "Nothing to commit after staging."
        return 0
    fi

    # Show what we're committing.
    local staged_count
    staged_count="$(git diff --cached --name-only | wc -l | tr -d ' ')"
    echo -e "  Staged ${BOLD}${staged_count}${NC} file(s):"
    git diff --cached --name-only | head -15 | while IFS= read -r f; do
        echo -e "    ${GREEN}+ ${f}${NC}"
    done
    if [[ "$staged_count" -gt 15 ]]; then
        echo -e "    ${YELLOW}... and $((staged_count - 15)) more${NC}"
    fi

    # ---- 3. Generate commit message ----
    echo -e "  Generating commit message..."
    local msg
    msg="$(generate_commit_msg)" || true

    # Safety net: if generate_commit_msg produced nothing (should not happen
    # given the deterministic fallback, but defence-in-depth), use a
    # timestamp-based message rather than letting git commit fail on an
    # empty -m.
    if [[ -z "$msg" ]]; then
        msg="chore: ship $(date +%Y-%m-%dT%H:%M:%S)"
        warn "Commit message generation returned empty — using fallback: ${msg}"
    fi

    echo -e "  Message: ${BOLD}${msg}${NC}"

    # ---- 4. Commit with explicit error handling ----
    local commit_log
    commit_log="$(make_temp)"

    # Use a simple -m instead of a heredoc to avoid expansion issues with
    # special characters ($, `, ", \) in AI-generated messages.
    if ! git commit -m "$msg" > "$commit_log" 2>&1; then
        fail_msg "git commit failed."
        echo -e "${YELLOW}--- commit output ---${NC}" >&2
        cat "$commit_log" >&2
        echo -e "${YELLOW}--- end ---${NC}" >&2
        echo "" >&2
        echo -e "Common causes:" >&2
        echo -e "  - Pre-commit hook rejected the changes" >&2
        echo -e "  - Empty commit message" >&2
        echo -e "  - Index lock (stale .git/index.lock)" >&2
        echo "" >&2
        echo -e "Staged changes are preserved.  Fix the issue and re-run ./ship.sh" >&2
        exit 1
    fi

    local commit_sha
    commit_sha="$(git rev-parse --short HEAD)"
    ok "Committed: ${commit_sha}"

    # ---- 5. Post-commit: verify no project files remain untracked ----
    local still_untracked=""
    for dir in "${PROJECT_DIRS[@]}"; do
        if [[ -d "$dir" ]]; then
            local found
            found="$(git ls-files --others --exclude-standard -- "$dir" 2>/dev/null | head -5)"
            if [[ -n "$found" ]]; then
                still_untracked+="$found"$'\n'
            fi
        fi
    done

    if [[ -n "$still_untracked" ]]; then
        warn "Source files still untracked after commit (check .gitignore):"
        echo "$still_untracked" | head -5 | while IFS= read -r line; do
            [[ -n "$line" ]] && echo -e "  ${YELLOW}? ${line}${NC}"
        done
    fi

    # ---- 6. Push with retry ----
    step "Pushing to origin/${BRANCH}"

    local push_log max_push_attempts=2
    push_log="$(make_temp)"

    local push_ok=0
    for attempt in $(seq 1 "$max_push_attempts"); do
        if git push -u origin "$BRANCH" > "$push_log" 2>&1; then
            push_ok=1
            break
        fi
        if [[ $attempt -lt $max_push_attempts ]]; then
            warn "Push attempt ${attempt} failed — retrying in 3s..."
            cat "$push_log" >&2
            sleep 2
        fi
    done

    if [[ "$push_ok" -eq 0 ]]; then
        fail_msg "Push to origin/${BRANCH} failed after ${max_push_attempts} attempts."
        echo -e "${YELLOW}--- push output ---${NC}" >&2
        cat "$push_log" >&2
        echo -e "${YELLOW}--- end ---${NC}" >&2
        echo "" >&2
        echo -e "The commit ${BOLD}${commit_sha}${NC} exists locally but did NOT reach the remote." >&2
        echo -e "Troubleshoot:" >&2
        echo -e "  - Check SSH key: ${BOLD}ssh -T git@github.com${NC}" >&2
        echo -e "  - Check remote:  ${BOLD}git remote -v${NC}" >&2
        echo -e "  - Retry push:    ${BOLD}git push origin ${BRANCH}${NC}" >&2
        exit 1
    fi

    ok "Pushed ${commit_sha} to origin/${BRANCH}"

    # ---- 7. Post-push verification ----
    # Confirm the remote actually received the commit.  A push can exit 0
    # in edge cases (shallow clone, partial ref update, proxy interference)
    # without the commit landing.  If verification fails, it's a warning
    # (not fatal) because transient caching at the remote can delay
    # ls-remote updates by a few seconds.
    echo -e "  Verifying remote received commit..."
    local remote_sha
    remote_sha="$(git ls-remote origin "${BRANCH}" 2>/dev/null | awk '{print $1}' | head -1 || true)"
    local local_sha
    local_sha="$(git rev-parse HEAD)"

    if [[ -z "$remote_sha" ]]; then
        warn "Could not verify remote HEAD (ls-remote returned empty). Check manually:"
        echo -e "    ${BOLD}git ls-remote origin ${BRANCH}${NC}"
    elif [[ "$remote_sha" != "$local_sha" ]]; then
        warn "Remote HEAD (${remote_sha:0:7}) does not match local HEAD (${local_sha:0:7})."
        echo -e "  This may be a transient caching delay.  Verify with:"
        echo -e "    ${BOLD}git ls-remote origin ${BRANCH}${NC}"
    else
        ok "Verified: remote HEAD matches local (${local_sha:0:7})"
    fi
}

generate_commit_msg() {
    # Generates a conventional-commit message for the staged changes.
    #
    # Priority:
    #   1. User-supplied message (passed as positional arg to ship.sh).
    #   2. AI-generated message via Claude Code CLI (with a hard timeout
    #      so the script never hangs).
    #   3. Deterministic fallback derived from the staged file types.
    #
    # This function MUST always produce a non-empty string.  Every code
    # path either echoes a message and returns, or falls through to the
    # deterministic fallback at the bottom.  The caller wraps the output
    # in an error check, but the fallback is the safety net.

    # --- 1. User-provided message takes precedence ---
    if [[ -n "$COMMIT_MSG" ]]; then
        echo "$COMMIT_MSG"
        return 0
    fi

    # --- 2. AI-generated message (with timeout) ---
    # The Claude CLI can hang on network issues, model overload, or
    # stdin-tty misdetection.  A 30-second timeout prevents the entire
    # ship pipeline from blocking.  On timeout or any failure, we fall
    # through to the deterministic fallback — no error, no retry.
    if has_claude_code && [[ "$NO_AI" -eq 0 ]]; then
        local diff_summary ai_msg=""
        diff_summary="$(git diff --cached --stat 2>/dev/null || true)"

        # timeout(1) sends SIGTERM after 30s, SIGKILL after 35s.
        # The || true ensures set -e does not kill the script if the
        # command fails or times out.
        if command -v timeout &>/dev/null; then
            ai_msg="$(timeout --signal=TERM --kill-after=5 30 \
                claude --print -p "Generate a one-line conventional commit message \
(format: type(scope): description) for these changes. Types: feat, fix, test, \
refactor, docs, chore, perf. Under 72 chars. Output ONLY the message, no \
explanation.

${diff_summary}" 2>/dev/null || true)"
        else
            # macOS without coreutils: use a background job with kill.
            local ai_outfile
            ai_outfile="$(make_temp)"
            claude --print -p "Generate a one-line conventional commit message \
(format: type(scope): description) for these changes. Types: feat, fix, test, \
refactor, docs, chore, perf. Under 72 chars. Output ONLY the message, no \
explanation.

${diff_summary}" > "$ai_outfile" 2>/dev/null &
            local ai_pid=$!
            local waited=0
            while kill -0 "$ai_pid" 2>/dev/null && [[ $waited -lt 30 ]]; do
                sleep 1
                waited=$((waited + 1))
            done
            if kill -0 "$ai_pid" 2>/dev/null; then
                # Still running after 30s — kill it.
                kill "$ai_pid" 2>/dev/null || true
                wait "$ai_pid" 2>/dev/null || true
                warn "Claude CLI timed out generating commit message — using fallback."
            else
                wait "$ai_pid" 2>/dev/null || true
                ai_msg="$(cat "$ai_outfile" 2>/dev/null || true)"
            fi
        fi

        # Sanitise: strip leading/trailing whitespace, reject multi-line
        # or overly long output (LLM hallucination guard).
        ai_msg="$(echo "$ai_msg" | head -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

        if [[ -n "$ai_msg" ]] && [[ "${#ai_msg}" -lt 100 ]] && [[ "${#ai_msg}" -gt 5 ]]; then
            echo "$ai_msg"
            return 0
        fi
    fi

    # --- 3. Deterministic fallback: infer type from staged files ---
    local py_files test_files doc_files
    py_files="$(git diff --cached --name-only | grep -c '\.py$' || true)"
    test_files="$(git diff --cached --name-only | grep -c 'test' || true)"
    doc_files="$(git diff --cached --name-only | grep -c '\.\(md\|rst\|txt\)$' || true)"

    local prefix="chore"
    if [[ "$test_files" -gt 0 ]] && [[ "$py_files" -eq "$test_files" ]]; then
        prefix="test"
    elif [[ "$doc_files" -gt 0 ]] && [[ "$py_files" -eq 0 ]]; then
        prefix="docs"
    elif [[ "$py_files" -gt 0 ]]; then
        prefix="feat"
    fi

    local files
    files="$(git diff --cached --name-only | head -3 | xargs -I{} basename {} | paste -sd, - || true)"
    echo "${prefix}: update ${files:-files}"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print_summary() {
    echo ""
    echo -e "${GREEN}${BOLD}  Shipped!${NC}"
    echo -e "  Commit:  $(git rev-parse --short HEAD)"
    echo -e "  Branch:  ${BRANCH}"
    echo -e "  Time:    $(git log -1 --format='%ci')"
    echo ""
    echo -e "  Deploy:  ${BOLD}sudo /opt/fxlab/install.sh${NC}"
    echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    echo -e "\n${BOLD}FXLab Ship${NC}"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo -e "${YELLOW}(dry run — no commit or push)${NC}"
    fi

    preflight
    run_quality_gates

    if [[ "$DRY_RUN" -eq 1 ]]; then
        echo -e "\n${GREEN}${BOLD}Dry run passed — all gates green.${NC}"
        exit 0
    fi

    commit_and_push
    print_summary
}

main "$@"

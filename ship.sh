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
    step "Commit & push to ${BRANCH}"

    # ---- Safety gate: warn about untracked source files ----
    # If any project directory contains untracked files, they won't appear
    # in the commit and the remote clone will be incomplete. This is the
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

    # Also check standalone project files at repo root
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

    # ---- Stage everything ----
    # 1. All project directories (source, tests, deploy configs, migrations)
    for dir in "${PROJECT_DIRS[@]}"; do
        [[ -d "$dir" ]] && git add -- "$dir" 2>/dev/null || true
    done

    # 2. Root-level project files (configs, scripts, docs)
    for pattern in "${root_files[@]}"; do
        # shellcheck disable=SC2086
        git add -- $pattern 2>/dev/null || true
    done

    # 3. Tracked-but-modified files (catches anything we missed)
    git add -u

    if git diff --cached --quiet; then
        warn "Nothing to commit after staging."
        return 0
    fi

    # Show what we're committing
    local staged_count
    staged_count="$(git diff --cached --name-only | wc -l | tr -d ' ')"
    echo -e "  Staging ${BOLD}${staged_count}${NC} file(s)"

    # Generate commit message
    local msg
    msg="$(generate_commit_msg)"
    echo -e "  Message: ${BOLD}${msg}${NC}"

    # Commit using heredoc to safely handle special characters
    git commit -m "$(cat <<EOF
${msg}
EOF
)"
    ok "Committed: $(git rev-parse --short HEAD)"

    # ---- Post-commit verification ----
    # Check that no project source files remain untracked after commit.
    # If they do, the commit is incomplete and the deploy will fail.
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

    # Push
    step "Pushing to origin/${BRANCH}"

    if ! git push -u origin "$BRANCH" 2>&1; then
        fail_msg "Push failed."
        exit 1
    fi

    ok "Pushed $(git rev-parse --short HEAD) to origin/${BRANCH}"
}

generate_commit_msg() {
    # User-provided message takes precedence
    if [[ -n "$COMMIT_MSG" ]]; then
        echo "$COMMIT_MSG"
        return
    fi

    # AI-generated message if Claude Code is available
    if has_claude_code && [[ "$NO_AI" -eq 0 ]]; then
        local diff_summary
        diff_summary="$(git diff --cached --stat 2>/dev/null)"
        local ai_msg
        ai_msg="$(claude --print -p "Generate a one-line conventional commit message \
(format: type(scope): description) for these changes. Types: feat, fix, test, \
refactor, docs, chore, perf. Under 72 chars. Output ONLY the message.

${diff_summary}" 2>/dev/null || echo "")"

        if [[ -n "$ai_msg" ]] && [[ "${#ai_msg}" -lt 100 ]]; then
            echo "$ai_msg"
            return
        fi
    fi

    # Fallback: infer type from changed files
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
    files="$(git diff --cached --name-only | head -3 | xargs -I{} basename {} | paste -sd, -)"
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

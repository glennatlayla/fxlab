# scripts/_lib.sh
# Shared shell helpers for FXLab developer-facing scripts.
# Sourced — not executed. Callers control their own shell options.

# ----------------------------- styling ---------------------------------------

if [[ -t 1 ]]; then
    _CLR_RED=$'\033[31m'
    _CLR_GREEN=$'\033[32m'
    _CLR_YELLOW=$'\033[33m'
    _CLR_BLUE=$'\033[34m'
    _CLR_GREY=$'\033[90m'
    _CLR_BOLD=$'\033[1m'
    _CLR_RESET=$'\033[0m'
else
    _CLR_RED= _CLR_GREEN= _CLR_YELLOW= _CLR_BLUE= _CLR_GREY= _CLR_BOLD= _CLR_RESET=
fi

log_info()  { printf '%s[info]%s  %s\n'  "$_CLR_BLUE"   "$_CLR_RESET" "$*"; }
log_ok()    { printf '%s[ ok ]%s  %s\n'  "$_CLR_GREEN"  "$_CLR_RESET" "$*"; }
log_warn()  { printf '%s[warn]%s  %s\n'  "$_CLR_YELLOW" "$_CLR_RESET" "$*"; }
log_err()   { printf '%s[ err]%s  %s\n'  "$_CLR_RED"    "$_CLR_RESET" "$*" >&2; }
log_step()  { printf '\n%s==>%s %s%s%s\n' "$_CLR_BOLD"  "$_CLR_RESET" "$_CLR_BOLD" "$*" "$_CLR_RESET"; }
log_skip()  { printf '%s[skip]%s  %s\n'  "$_CLR_GREY"   "$_CLR_RESET" "$*"; }

die() {
    log_err "$*"
    exit 1
}

# ----------------------------- detection -------------------------------------

have_cmd() { command -v "$1" >/dev/null 2>&1; }

detect_os() {
    case "$(uname -s)" in
        Linux*)  echo linux ;;
        Darwin*) echo darwin ;;
        *)       echo unknown ;;
    esac
}

# Compare two semver-ish version strings.
# Returns 0 if $1 >= $2, 1 otherwise.
version_ge() {
    [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" == "$2" ]]
}

# ----------------------------- summary table ---------------------------------

SUMMARY_FILE="${SUMMARY_FILE:-/tmp/fxlab_bootstrap_summary.tsv}"

summary_init() {
    : >"$SUMMARY_FILE"
}

summary_row() {
    local status="$1" component="$2" detail="$3"
    printf '%s\t%s\t%s\n' "$status" "$component" "$detail" >>"$SUMMARY_FILE"
}

summary_print() {
    [[ -s "$SUMMARY_FILE" ]] || return 0
    log_step "Summary"
    awk -F'\t' '{
        st=$1; comp=$2; detail=$3;
        printf "  %-6s  %-22s  %s\n", st, comp, detail
    }' "$SUMMARY_FILE"
}

summary_has_failures() {
    grep -q '^FAIL' "$SUMMARY_FILE" 2>/dev/null
}

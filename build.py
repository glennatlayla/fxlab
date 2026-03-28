#!/usr/bin/env python3
"""
build.py — FXLab Project Build Menu
====================================
Sits at the project root. On every invocation it:

  1. Loads .env from the project root and validates ANTHROPIC_API_KEY.
  2. Checks for a .venv (Python 3.12+), creates and validates one if missing.
  3. Activates the venv context for subprocess calls.
  4. Scans docs/workplan-tracking/ for active workplan state.
  5. Calls Claude to produce an AI-synthesised session brief.
  6. Presents an interactive menu, including an agentic "drive next milestone
     step with Claude" option.

Usage:
  python build.py            # Interactive menu (default)
  python build.py --no-brief # Skip the AI brief (faster startup)
  python build.py --run t    # Run a single menu action non-interactively
  python build.py --help     # This message

Requirements: Python 3.9+ to run this script itself (it finds 3.12 for the
              venv). No third-party packages needed before the venv exists --
              all API calls use stdlib urllib.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
import ast
import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT         = Path(__file__).resolve().parent
VENV_DIR             = PROJECT_ROOT / ".venv"
TRACKING_DIR         = PROJECT_ROOT / "docs" / "workplan-tracking"
SHARED_LESSONS       = TRACKING_DIR / "SHARED_LESSONS.md"
ACTIVE_WORKPLAN_FILE = TRACKING_DIR / ".active_workplan"  # persists as JSON
# User Spec dir: where workplan and software-spec .md files live.
# Checked in order; first match wins.
_SPEC_DIR_CANDIDATES = ["User Spec", "user_spec", "specs", "Specs", "docs"]
SPEC_DIR = next(
    (PROJECT_ROOT / d for d in _SPEC_DIR_CANDIDATES if (PROJECT_ROOT / d).is_dir()),
    PROJECT_ROOT,  # fallback: browse project root
)
ENV_FILE             = PROJECT_ROOT / ".env"
REQUIREMENTS         = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_DEV     = PROJECT_ROOT / "requirements-dev.txt"

# Canonical list of dev tool packages required for building.
# When any of these are missing the readiness check auto-installs them.
DEV_PACKAGES = [
    # test & quality tools
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "black",
    "ruff",
    "mypy",
    "factory-boy",
    "faker",
    # runtime deps needed to import project code under test
    "fastapi",
    "uvicorn",
    "pydantic",
    "pydantic-settings",
    "sqlalchemy",
    "alembic",
    "structlog",
    "python-ulid",
    "python-jose",
    "passlib",
    "httpx",
    "tenacity",
    "redis",
    "celery",
    "boto3",
    "polars",
    "pyarrow",
    "psycopg2-binary",
    "prometheus-client",
]
# Binaries that should exist in .venv/bin after installation
DEV_BINARIES = ["pytest", "black", "ruff", "mypy"]

ANTHROPIC_API_URL     = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MODEL         = "claude-sonnet-4-5"   # override via .env ANTHROPIC_MODEL

if platform.system() == "Windows":
    VENV_PYTHON   = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP      = VENV_DIR / "Scripts" / "pip.exe"
    VENV_ACTIVATE = VENV_DIR / "Scripts" / "activate.bat"
else:
    VENV_PYTHON   = VENV_DIR / "bin" / "python"
    VENV_PIP      = VENV_DIR / "bin" / "pip"
    VENV_ACTIVATE = VENV_DIR / "bin" / "activate"

USE_COLOUR = sys.stdout.isatty() and platform.system() != "Windows"

C_RESET   = "\033[0m"  if USE_COLOUR else ""
C_BOLD    = "\033[1m"  if USE_COLOUR else ""
C_DIM     = "\033[2m"  if USE_COLOUR else ""
C_RED     = "\033[91m" if USE_COLOUR else ""
C_YELLOW  = "\033[93m" if USE_COLOUR else ""
C_GREEN   = "\033[92m" if USE_COLOUR else ""
C_CYAN    = "\033[96m" if USE_COLOUR else ""
C_MAGENTA = "\033[95m" if USE_COLOUR else ""

# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def _h1(msg: str) -> None:
    w = 72
    print(f"\n{C_BOLD}{C_CYAN}{'=' * w}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}  {msg}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * w}{C_RESET}")

def _h2(msg: str)   -> None: print(f"\n{C_BOLD}{C_MAGENTA}-- {msg} {C_RESET}")
def _ok(msg: str)   -> None: print(f"  {C_GREEN}+{C_RESET}  {msg}")
def _warn(msg: str) -> None: print(f"  {C_YELLOW}!{C_RESET}  {msg}")
def _err(msg: str)  -> None: print(f"  {C_RED}x{C_RESET}  {msg}")
def _info(msg: str) -> None: print(f"  {C_DIM}.{C_RESET}  {msg}")
def _sep()          -> None: print(f"{C_DIM}{'-' * 72}{C_RESET}")

class BuildLog:
    """
    Routes output to two channels:
      screen  — only what the user needs to act on
      logfile — everything (detail, claude output, debug)

    Use log.detail() for anything the user doesn't need to read.
    Use log.status/success/warn/error/banner for user-facing lines.
    """

    def __init__(self, workplan_stem: str) -> None:
        self._path = TRACKING_DIR / f"{workplan_stem}.build-log.md"
        TRACKING_DIR.mkdir(parents=True, exist_ok=True)

    def _write(self, text: str) -> None:
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

    def section(self, title: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._write(f"\n## {ts}  {title}\n")

    def detail(self, msg: str) -> None:
        """File only — never shown on screen."""
        self._write(f"    {msg}")

    def status(self, msg: str) -> None:
        print(f"  {msg}")
        self._write(f"  {msg}")

    def success(self, msg: str) -> None:
        print(f"  {C_GREEN}✔{C_RESET}  {msg}")
        self._write(f"  +  {msg}")

    def warn(self, msg: str) -> None:
        print(f"  {C_YELLOW}!{C_RESET}  {msg}")
        self._write(f"  !  {msg}")

    def error(self, msg: str) -> None:
        print(f"  {C_RED}✖{C_RESET}  {msg}")
        self._write(f"  x  {msg}")

    def code_block(self, content: str, max_lines: int = 40) -> None:
        """Write verbatim content to log file only."""
        self._write("```")
        lines = content.splitlines()
        for line in lines[:max_lines]:
            self._write(line)
        if len(lines) > max_lines:
            self._write(f"... ({len(lines)-max_lines} more lines truncated)")
        self._write("```")

    def banner(self, msg: str, ok: bool) -> None:
        col  = C_GREEN if ok else C_RED
        icon = "✔" if ok else "✖"
        print(f"\n  {C_BOLD}{col}{icon}  {msg}{C_RESET}\n")
        self._write(f"\n  {icon}  {msg}\n")

    @property
    def path(self) -> Path:
        return self._path



# ---------------------------------------------------------------------------
# .env loader  (pure stdlib -- works before venv exists)
# ---------------------------------------------------------------------------

def load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    """
    Parse KEY=VALUE lines from a .env file and inject into os.environ.

    Rules:
    - Lines starting with # are skipped (comments).
    - 'export KEY=VALUE' prefix is stripped.
    - Single- and double-quoted values are unquoted.
    - Existing env vars are never overwritten (os.environ.setdefault).

    Returns a dict of variables actually loaded from the file.
    """
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key   = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        if not key:
            continue
        os.environ.setdefault(key, value)
        loaded[key] = value

    return loaded


def validate_api_key() -> tuple[bool, str]:
    """
    Check that ANTHROPIC_API_KEY is present and plausible (format only --
    no network call). Returns (ok, human-readable message).
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return False, "ANTHROPIC_API_KEY is not set"
    if not key.startswith("sk-ant-"):
        return False, f"Key does not start with 'sk-ant-' (got: {key[:12]}...)"
    if len(key) < 40:
        return False, f"Key looks too short (length {len(key)})"
    return True, f"{key[:16]}...{'*' * 8}"


# ---------------------------------------------------------------------------
# Spinner (shows activity during blocking API calls)
# ---------------------------------------------------------------------------

class Spinner:
    """
    Display a terminal spinner in a background thread while work runs.

    Usage:
        with Spinner("Calling Claude"):
            result = slow_function()
    """
    def __init__(self, msg: str = "Working") -> None:
        self._msg    = msg
        self._stop   = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        frames = itertools.cycle(["|", "/", "-", "\\"])
        while not self._stop.is_set():
            print(f"\r  {C_CYAN}{next(frames)}{C_RESET}  {self._msg} ...",
                  end="", flush=True)
            time.sleep(0.12)
        print(f"\r{' ' * (len(self._msg) + 14)}\r", end="", flush=True)

    def __enter__(self) -> "Spinner":
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        self._thread.join()


# ---------------------------------------------------------------------------
# Anthropic API  (stdlib urllib only -- no SDK needed)
# ---------------------------------------------------------------------------

def call_claude(
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 4096,
) -> str:
    """
    POST to the Anthropic Messages API and return the assistant text.

    Uses only stdlib urllib -- the anthropic SDK is not required.
    Model is read from ANTHROPIC_MODEL env var, defaulting to DEFAULT_MODEL.
    Raises RuntimeError on API or network failures.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    model   = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    payload = json.dumps({
        "model":      model,
        "max_tokens": max_tokens,
        "system":     system,
        "messages":   messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return "".join(
                block.get("text", "")
                for block in body.get("content", [])
                if block.get("type") == "text"
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("error", {}).get("message", raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"Anthropic API {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Venv management
# ---------------------------------------------------------------------------

def _run(
    cmd: list[str],
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    kwargs: dict[str, Any] = {"check": check}
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return subprocess.run(cmd, **kwargs)


def _venv_exists() -> bool:
    return VENV_PYTHON.exists()


def _validate_venv() -> tuple[bool, str]:
    if not VENV_PYTHON.exists():
        return False, "Python binary not found in .venv"
    try:
        result = _run(
            [str(VENV_PYTHON), "-c",
             "import sys, pip; print(sys.version_info.major, sys.version_info.minor)"],
            capture=True,
        )
        major, minor = map(int, result.stdout.strip().split())
        if (major, minor) < (3, 10):
            return False, f"Python {major}.{minor} found; 3.10+ required"
        return True, f"Python {major}.{minor} -- OK"
    except Exception as exc:
        return False, f"Validation probe failed: {exc}"


def _find_python_312() -> Optional[str]:
    """
    Return path to the best available Python 3.10+ binary by searching:
      1. Explicitly versioned names on PATH (python3.13, python3.12, python3.11, python3.10)
      2. Homebrew prefixes: Apple Silicon /opt/homebrew, Intel /usr/local
      3. pyenv shims and versions directory (~/.pyenv)
      4. Python.org macOS framework installer
      5. Generic python3 / python on PATH
      6. sys.executable as last resort

    Note: The minimum was lowered to 3.10 to support Linux CI environments
    where only python3.10 is available. The project targets 3.12 in production.
    """
    MIN = (3, 10)

    def _version_ok(exe: str) -> bool:
        try:
            r = subprocess.run(
                [exe, "-c",
                 "import sys; print(sys.version_info.major, sys.version_info.minor)"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                return False
            return tuple(map(int, r.stdout.strip().split())) >= MIN
        except Exception:
            return False

    candidates: list[str] = []

    # 1. Versioned names on PATH — prefer highest version first
    for name in ("python3.13", "python3.12", "python3.11", "python3.10"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # 2. Homebrew
    for prefix in ("/opt/homebrew", "/usr/local"):
        for minor in (13, 12, 11, 10):
            p = f"{prefix}/bin/python3.{minor}"
            if Path(p).exists():
                candidates.append(p)
        p = f"{prefix}/bin/python3"
        if Path(p).exists():
            candidates.append(p)

    # 3. pyenv
    pyenv_root = Path(os.environ.get("PYENV_ROOT", Path.home() / ".pyenv"))
    if pyenv_root.exists():
        for minor in (13, 12, 11, 10):
            p = pyenv_root / "shims" / f"python3.{minor}"
            if p.exists():
                candidates.append(str(p))
        versions_dir = pyenv_root / "versions"
        if versions_dir.exists():
            for ver_dir in sorted(versions_dir.iterdir(), reverse=True):
                try:
                    parts = ver_dir.name.split(".")
                    if int(parts[0]) == 3 and int(parts[1]) >= 10:
                        p = ver_dir / "bin" / "python3"
                        if p.exists():
                            candidates.append(str(p))
                except (ValueError, IndexError):
                    pass

    # 4. Python.org macOS framework
    for minor in (13, 12, 11, 10):
        p = f"/Library/Frameworks/Python.framework/Versions/3.{minor}/bin/python3"
        if Path(p).exists():
            candidates.append(p)

    # 5. Generic PATH
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # 6. Fallback
    candidates.append(sys.executable)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        real = str(Path(c).resolve())
        if real not in seen:
            seen.add(real)
            unique.append(c)

    for exe in unique:
        if _version_ok(exe):
            return exe
    return None


def create_venv() -> None:
    _h2("Creating virtual environment")
    python_exe = _find_python_312()
    if python_exe is None:
        _err("Could not find Python 3.10+ on this system.")
        _err("Install options:")
        _err("  brew install python@3.12")
        _err("  pyenv install 3.12.x && pyenv global 3.12.x")
        _err("  sudo apt-get install python3.12  (Linux/Ubuntu)")
        _err("  https://www.python.org/downloads/")
        sys.exit(1)

    _info(f"Using: {python_exe}")
    try:
        r = subprocess.run([python_exe, "--version"], capture_output=True, text=True)
        _info((r.stdout or r.stderr).strip())
    except Exception:
        pass

    _run([python_exe, "-m", "venv", str(VENV_DIR)])
    _ok(f".venv created at {VENV_DIR}")
    _info("Upgrading pip ...")
    _run([str(VENV_PIP), "install", "--upgrade", "pip", "--quiet"])
    _ok("pip upgraded")


def install_requirements() -> None:
    """Install requirements files and ensure dev tools are present."""
    installed = False
    for req in (REQUIREMENTS, REQUIREMENTS_DEV):
        if req.exists():
            _info(f"Installing {req.name} ...")
            _run([str(VENV_PIP), "install", "-r", str(req), "--quiet"])
            _ok(f"{req.name} installed")
            installed = True
    if not installed:
        _warn("No requirements files found -- installing dev tools directly")
    # Always ensure dev tools are present regardless of requirements files
    _ensure_dev_tools(quiet=True)


def _ensure_dev_tools(quiet: bool = False) -> bool:
    """
    Ensure every package in DEV_PACKAGES is importable in the venv.
    Checks each package by attempting to import it -- not just by looking
    for a binary -- then installs any that are missing in a single pip call.
    Called at startup so missing packages are never the user's problem.
    """
    def _importable(pkg: str) -> bool:
        # Map install name to import name where they differ
        _import_name = {
            "python-ulid":       "ulid",
            "pytest-asyncio":    "pytest_asyncio",
            "pytest-cov":        "pytest_cov",
            "psycopg2-binary":   "psycopg2",
            "python-jose":       "jose",
            "factory-boy":       "factory",
            "prometheus-client": "prometheus_client",
            "opentelemetry-sdk": "opentelemetry",
        }
        import_name = _import_name.get(pkg, pkg.replace("-", "_"))
        r = subprocess.run(
            [str(VENV_PYTHON), "-c", f"import {import_name}"],
            capture_output=True,
        )
        return r.returncode == 0

    missing = [p for p in DEV_PACKAGES if not _importable(p)]

    if not missing:
        _ensure_package_inits()
        return True

    if not quiet:
        _info(f"Auto-installing: {', '.join(missing)}")
    result = subprocess.run(
        [str(VENV_PIP), "install"] + missing + ["--quiet"],
        capture_output=quiet,
    )
    if result.returncode == 0:
        if not quiet:
            _ok(f"Installed: {', '.join(missing)}")
        _ensure_package_inits()
        return True
    else:
        _err(f"pip install failed for: {', '.join(missing)}")
        return False


def _ensure_package_inits() -> None:
    """
    Two-phase package hygiene pass run before and after every agent step.

    Phase A — Reactive: any directory under services/, libs/, or tests/ that
    already contains .py files but is missing __init__.py gets one created.
    This handles the common case where Claude writes foo.py but forgets the
    package marker.

    Phase B — Proactive: every top-level lib that is already a package
    (has __init__.py) gets its standard subdirectory skeleton scaffolded:
      - interfaces/   — abstract ports (ABCs / Protocols)
      - mocks/        — in-memory fakes for unit tests
    This ensures the onion-architecture subdirectory structure is always
    present for any lib, regardless of which phase introduced it.  New libs
    added in future phases automatically get the full skeleton on the next
    [a] run without any manual scaffolding.
    """
    # ── Phase A: reactive __init__.py creation ────────────────────────────
    roots = ["services", "libs", "tests"]
    for root in roots:
        root_path = PROJECT_ROOT / root
        if not root_path.exists():
            continue
        for dirpath in root_path.rglob("*"):
            if not dirpath.is_dir():
                continue
            has_py = any(dirpath.glob("*.py"))
            init   = dirpath / "__init__.py"
            if has_py and not init.exists():
                init.write_text(
                    f'"""Auto-created by build.py — {dirpath.relative_to(PROJECT_ROOT)}"""\n'
                )

    # ── Phase B: proactive lib skeleton scaffolding ───────────────────────
    # For every top-level directory under libs/ that is already a Python
    # package, ensure the standard onion-architecture subdirs exist.
    _LIB_SUBDIRS = ("interfaces", "mocks")
    libs_root = PROJECT_ROOT / "libs"
    if not libs_root.exists():
        return
    for lib_dir in sorted(libs_root.iterdir()):
        if not lib_dir.is_dir() or lib_dir.name.startswith("."):
            continue
        if not (lib_dir / "__init__.py").exists():
            continue   # not yet a package — skip until Phase A promotes it
        for subname in _LIB_SUBDIRS:
            sub      = lib_dir / subname
            sub_init = sub / "__init__.py"
            if sub_init.exists():
                continue   # already present
            sub.mkdir(exist_ok=True)
            rel = sub.relative_to(PROJECT_ROOT)
            sub_init.write_text(
                f'"""\n'
                f'{subname.capitalize()} package for {lib_dir.name}.\n\n'
                f'{"Abstract ports (ABCs / Protocols) for the" if subname == "interfaces" else "In-memory fakes for unit-testing the"} '
                f'{lib_dir.name} subsystem.\n'
                f'Concrete implementations must never be imported here.\n'
                f'"""\n'
            )


def ensure_venv() -> None:
    _h2("Virtual environment check")
    if not _venv_exists():
        _warn(".venv not found -- creating one now")
        create_venv()
        install_requirements()

    ok, message = _validate_venv()
    if ok:
        _ok(f".venv validated: {message}")
        return

    _err(f".venv validation FAILED: {message}")
    answer = input(
        f"  {C_YELLOW}Delete and recreate .venv? [y/N]{C_RESET} "
    ).strip().lower()
    if answer != "y":
        _err("Cannot continue with invalid .venv. Exiting.")
        sys.exit(1)

    _info("Removing existing .venv ...")
    shutil.rmtree(VENV_DIR)
    create_venv()
    install_requirements()
    ok2, msg2 = _validate_venv()
    if ok2:
        _ok(f".venv recreated and validated: {msg2}")
        install_requirements()  # includes _ensure_dev_tools
    else:
        _err(f"Recreated .venv still fails validation: {msg2}")
        _err("Please inspect .venv manually before continuing.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Tracking file data structures
# ---------------------------------------------------------------------------

@dataclass
class ProgressEntry:
    milestone_id:   str
    label:          str
    status:         str
    blocking_issue: str = ""
    steps:          list[tuple[str, str]] = field(default_factory=list)


@dataclass
class WorkplanProgress:
    workplan_name:    str
    progress_file:    Path
    last_updated:     str
    active_milestone: str
    active_step:      str
    resume_detail:    str
    entries:          list[ProgressEntry] = field(default_factory=list)


@dataclass
class Issue:
    number:     str
    title:      str
    status:     str
    milestone:  str
    discovered: str
    resolved:   str
    symptoms:   str
    root_cause: str
    fix:        str
    lesson_ref: str


@dataclass
class Lesson:
    number:    str
    title:     str
    milestone: str
    source:    str
    lesson:    str
    apply_to:  str


@dataclass
class WorkplanTracking:
    workplan_name: str
    progress:  Optional[WorkplanProgress]  = None
    issues:    list[Issue]                 = field(default_factory=list)
    lessons:   list[Lesson]                = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tracking file parsers
# ---------------------------------------------------------------------------

_STATUS_RE = re.compile(
    r"^\[(?P<mid>M\d+[A-Z]?)\]\s+(?P<label>.+?)\s{2,}"
    r"(?P<status>DONE|IN_PROGRESS|NOT_STARTED|BLOCKED(?:\[ISS-\d+\])?|SKIPPED)",
    re.IGNORECASE,
)
_STEP_RE = re.compile(
    r"^\s+\[(?P<sid>[A-Z\d]+-S\d+)\]\s+(?P<label>.+?)\s{2,}"
    r"(?P<status>DONE|IN_PROGRESS|NOT_STARTED|BLOCKED(?:\[ISS-\d+\])?|SKIPPED)",
    re.IGNORECASE,
)
_HEADER_RE = re.compile(r"^#\s+(?P<key>[A-Za-z ]+):\s*(?P<value>.+)$")


def _parse_progress(path: Path) -> Optional[WorkplanProgress]:
    if not path.exists():
        return None
    headers: dict[str, str] = {}
    entries: list[ProgressEntry] = []
    current: Optional[ProgressEntry] = None

    for line in path.read_text(encoding="utf-8").splitlines():
        hm = _HEADER_RE.match(line)
        if hm:
            headers[hm.group("key").strip().lower()] = hm.group("value").strip()
            continue
        sm = _STATUS_RE.match(line)
        if sm:
            if current:
                entries.append(current)
            raw = sm.group("status").upper()
            blocking = ""
            if raw.startswith("BLOCKED"):
                m = re.search(r"\[(ISS-\d+)\]", raw)
                blocking = m.group(1) if m else ""
                raw = "BLOCKED"
            current = ProgressEntry(
                milestone_id=sm.group("mid"),
                label=sm.group("label").strip(),
                status=raw,
                blocking_issue=blocking,
            )
            continue
        step_m = _STEP_RE.match(line)
        if step_m and current:
            # Store (bare_step_id, status) e.g. ("S1", "NOT_STARTED")
            # so the status panel can look up by step ID directly
            raw_sid = step_m.group("sid")        # e.g. "M0-S1"
            bare    = raw_sid.split("-")[-1]     # e.g. "S1"
            current.steps.append(
                (bare, step_m.group("status").upper())
            )
    if current:
        entries.append(current)

    return WorkplanProgress(
        workplan_name=path.stem,
        progress_file=path,
        last_updated=headers.get("last updated", "unknown"),
        active_milestone=headers.get("active milestone", "M0"),
        active_step=headers.get("active step", "STEP 1"),
        resume_detail=headers.get("active step", "STEP 1"),
        entries=entries,
    )


def _block_field(block: str, name: str) -> str:
    m = re.search(
        rf"^{re.escape(name)}:\s*(.+?)(?=\n[A-Za-z ]+:|$)",
        block, re.MULTILINE | re.DOTALL,
    )
    return textwrap.dedent(m.group(1)).strip() if m else ""


def _parse_issues(path: Path) -> list[Issue]:
    if not path.exists():
        return []
    issues: list[Issue] = []
    for block in re.split(r"\n---\n", path.read_text(encoding="utf-8")):
        m = re.search(r"(ISS-\d+)", block)
        if not m:
            continue
        issues.append(Issue(
            number=m.group(1),
            title=_block_field(block, "Title"),
            status=_block_field(block, "Status"),
            milestone=_block_field(block, "Milestone"),
            discovered=_block_field(block, "Discovered"),
            resolved=_block_field(block, "Resolved"),
            symptoms=_block_field(block, "Symptoms"),
            root_cause=_block_field(block, "Root cause"),
            fix=_block_field(block, "Fix"),
            lesson_ref=_block_field(block, "Lesson"),
        ))
    return issues


def _parse_lessons(path: Path) -> list[Lesson]:
    if not path.exists():
        return []
    lessons: list[Lesson] = []
    for block in re.split(r"\n---\n", path.read_text(encoding="utf-8")):
        m = re.search(r"(LL-\d+)", block)
        if not m:
            continue
        lessons.append(Lesson(
            number=m.group(1),
            title=_block_field(block, "Title"),
            milestone=_block_field(block, "Milestone"),
            source=_block_field(block, "Source"),
            lesson=_block_field(block, "Lesson"),
            apply_to=_block_field(block, "Apply to"),
        ))
    return lessons


def discover_tracking() -> list[WorkplanTracking]:
    """Load all tracking files from docs/workplan-tracking/."""
    if not TRACKING_DIR.exists():
        return []
    stems: set[str] = set()
    for f in TRACKING_DIR.iterdir():
        for ext in (".progress", ".issues", ".lessons-learned"):
            if f.name.endswith(ext):
                stems.add(f.name[: -len(ext)])
    results: list[WorkplanTracking] = []
    for stem in sorted(stems):
        wt = WorkplanTracking(workplan_name=stem)
        wt.progress = _parse_progress(TRACKING_DIR / f"{stem}.progress")
        wt.issues   = _parse_issues(TRACKING_DIR / f"{stem}.issues")
        wt.lessons  = _parse_lessons(TRACKING_DIR / f"{stem}.lessons-learned")
        results.append(wt)
    return results


# ---------------------------------------------------------------------------
# Active workplan / spec selection  (persisted to .active_workplan as JSON)
# ---------------------------------------------------------------------------
#
# .active_workplan stores:
#   {
#     "workplan_stem": "FXLab_Phase_1_workplan_v3",   <- tracking file stem
#     "workplan_path": "User Spec/FXLab_Phase_1_workplan_v3.md",
#     "spec_path":     "User Spec/phase_1_platform_foundation_v1.md"  (may be "")
#   }
# ---------------------------------------------------------------------------

@dataclass
class ActiveSelection:
    workplan_stem: str        # stem used for tracking files
    workplan_path: Path       # absolute path to the workplan .md
    spec_path:     Optional[Path]  # absolute path to the software spec .md (optional)


def load_active_selection() -> Optional[ActiveSelection]:
    """Load the persisted workplan + spec selection from .active_workplan (JSON)."""
    if not ACTIVE_WORKPLAN_FILE.exists():
        return None
    try:
        data = json.loads(ACTIVE_WORKPLAN_FILE.read_text(encoding="utf-8"))
        wp_path = PROJECT_ROOT / data["workplan_path"]
        sp_raw  = data.get("spec_path", "")
        sp_path = PROJECT_ROOT / sp_raw if sp_raw else None
        return ActiveSelection(
            workplan_stem=data["workplan_stem"],
            workplan_path=wp_path,
            spec_path=sp_path,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_active_selection(sel: ActiveSelection) -> None:
    """Persist the active selection to .active_workplan (JSON)."""
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "workplan_stem": sel.workplan_stem,
        "workplan_path": str(sel.workplan_path.relative_to(PROJECT_ROOT)),
        "spec_path":     str(sel.spec_path.relative_to(PROJECT_ROOT)) if sel.spec_path else "",
    }
    ACTIVE_WORKPLAN_FILE.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


def resolve_active_workplan(
    all_wt: list[WorkplanTracking],
) -> Optional[WorkplanTracking]:
    """
    Return the active WorkplanTracking for menu display / brief scoping.
    Priority:
      1. Stem from saved .active_workplan JSON.
      2. Auto-select when exactly one workplan is tracked.
      3. None.
    """
    sel = load_active_selection()
    if sel:
        for wt in all_wt:
            if wt.workplan_name == sel.workplan_stem:
                return wt
        _warn(f"Saved workplan stem '{sel.workplan_stem}' has no tracking files -- ignoring.")

    if len(all_wt) == 1:
        return all_wt[0]

    return None


# ---------------------------------------------------------------------------
# .md file browser (for User Spec directory)
# ---------------------------------------------------------------------------

def _collect_md_files(directory: Path) -> list[Path]:
    """
    Recursively collect all .md files under directory, sorted with files in
    the root first, then subdirectories alphabetically.
    """
    root_files = sorted(p for p in directory.glob("*.md"))
    sub_files: list[Path] = []
    for sub in sorted(d for d in directory.iterdir() if d.is_dir() and not d.name.startswith(".")):
        sub_files.extend(sorted(sub.rglob("*.md")))
    return root_files + sub_files


def browse_md_files(
    directory: Path,
    prompt: str = "Select a file",
    allow_skip: bool = False,
) -> Optional[Path]:
    """
    Display a numbered list of .md files found under `directory` and return
    the user's choice.  Files are grouped: root-level first, then by subfolder.
    Returns None if the user cancels or skips.
    """
    if not directory.exists():
        _warn(f"Directory not found: {directory}")
        _warn("Create it and add your .md files, or update SPEC_DIR in build.py.")
        return None

    files = _collect_md_files(directory)
    if not files:
        _warn(f"No .md files found under {directory}")
        return None

    # Group by parent for display
    last_parent: Optional[Path] = None
    for idx, fp in enumerate(files, 1):
        parent = fp.parent
        if parent != last_parent:
            rel_parent = parent.relative_to(PROJECT_ROOT)
            print(f"\n  {C_DIM}{rel_parent}/{C_RESET}")
            last_parent = parent
        size_kb = fp.stat().st_size / 1024
        print(f"    {C_BOLD}[{idx:>2}]{C_RESET}  {fp.name}  {C_DIM}({size_kb:.1f} KB){C_RESET}")

    skip_hint = f" / s=skip" if allow_skip else ""
    print()
    try:
        raw = input(
            f"  {C_YELLOW}{prompt} (1-{len(files)}{skip_hint} / Enter=cancel):{C_RESET} "
        ).strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        return None

    if not raw or raw == "q":
        _info("Cancelled.")
        return None

    if allow_skip and raw == "s":
        _info("Skipped.")
        return None

    try:
        idx = int(raw) - 1
        if not (0 <= idx < len(files)):
            raise ValueError
        return files[idx]
    except ValueError:
        _warn(f"Invalid selection: '{raw}'")
        return None


def action_select_workplan(all_wt: list[WorkplanTracking]) -> Optional[WorkplanTracking]:
    """
    Two-step interactive picker:
      Step 1 -- Browse User Spec dir and pick a workplan .md file.
      Step 2 -- Browse same dir and pick the corresponding software spec .md
                (optional -- press s to skip).

    The workplan file name (without extension) becomes the tracking stem.
    Tracking files are bootstrapped automatically if they don't yet exist.
    The selection is persisted to .active_workplan (JSON).
    """
    _h2("Select workplan")
    _info(f"Browsing: {SPEC_DIR}")

    # ── Step 1: pick workplan file ─────────────────────────────────────
    print(f"\n  {C_BOLD}Step 1 of 2 -- Workplan file{C_RESET}")
    workplan_path = browse_md_files(SPEC_DIR, prompt="Select workplan")
    if workplan_path is None:
        return None

    workplan_stem = workplan_path.stem
    _ok(f"Workplan: {workplan_path.relative_to(PROJECT_ROOT)}")

    # ── Step 2: pick software spec file ───────────────────────────────
    print(f"\n  {C_BOLD}Step 2 of 2 -- Software spec file (optional){C_RESET}")
    _info("This spec is injected into Claude prompts as additional context.")
    spec_path = browse_md_files(
        SPEC_DIR,
        prompt="Select spec (s=skip)",
        allow_skip=True,
    )
    if spec_path:
        _ok(f"Spec:     {spec_path.relative_to(PROJECT_ROOT)}")
    else:
        _info("No spec selected -- Claude will use the workplan alone.")

    # ── Bootstrap tracking files if needed ────────────────────────────
    progress_file = TRACKING_DIR / f"{workplan_stem}.progress"
    if not progress_file.exists():
        _info(f"No tracking files found for '{workplan_stem}' -- bootstrapping now ...")
        _bootstrap_one(workplan_stem)

    # ── Persist selection ──────────────────────────────────────────────
    sel = ActiveSelection(
        workplan_stem=workplan_stem,
        workplan_path=workplan_path,
        spec_path=spec_path,
    )
    save_active_selection(sel)
    _ok(f"Active workplan: {C_BOLD}{workplan_stem}{C_RESET}")
    if spec_path:
        _ok(f"Active spec:     {C_BOLD}{spec_path.name}{C_RESET}")
    _info(f"Selection saved to {ACTIVE_WORKPLAN_FILE}")

    # Return the matching WorkplanTracking if it exists already
    all_wt_refreshed = discover_tracking()
    for wt in all_wt_refreshed:
        if wt.workplan_name == workplan_stem:
            return wt
    return None


def find_resume(all_wt: list[WorkplanTracking]) -> Optional[tuple[str, str, str]]:
    """
    Return (workplan_name, active_milestone, resume_detail) for the active
    workplan, or the first in-progress workplan if no explicit selection exists.
    """
    active = resolve_active_workplan(all_wt)
    if active and active.progress:
        wp = active.progress
        return active.workplan_name, wp.active_milestone, wp.resume_detail

    # Fallback: first workplan with work in progress
    for wt in all_wt:
        if wt.progress:
            for entry in wt.progress.entries:
                if entry.status in ("IN_PROGRESS", "BLOCKED"):
                    wp = wt.progress
                    return wt.workplan_name, wp.active_milestone, wp.resume_detail
    return None


def find_workplan_file(workplan_name: str) -> Optional[Path]:
    """
    Return the workplan .md Path.  Priority:
      1. The path saved in .active_workplan (most reliable).
      2. Stem-name match anywhere under SPEC_DIR.
      3. Stem-name match anywhere under PROJECT_ROOT (legacy fallback).
    """
    sel = load_active_selection()
    if sel and sel.workplan_stem == workplan_name and sel.workplan_path.exists():
        return sel.workplan_path

    for p in SPEC_DIR.rglob("*.md"):
        if p.stem == workplan_name:
            return p

    for p in PROJECT_ROOT.rglob("*.md"):
        if "workplan-tracking" in str(p):
            continue
        if p.stem == workplan_name or workplan_name in p.stem:
            return p
    return None


def find_spec_file() -> Optional[Path]:
    """Return the saved software spec Path, or None."""
    sel = load_active_selection()
    if sel and sel.spec_path and sel.spec_path.exists():
        return sel.spec_path
    return None


# ---------------------------------------------------------------------------
# Distilled context  (per-milestone summaries, generated once via [d])
# ---------------------------------------------------------------------------
# The distilled file lives at:
#   docs/workplan-tracking/{stem}.distilled.md
#
# Format produced by action_distil():
#   ## MILESTONE: M0 -- Bootstrap
#   ### Spec Context
#   ...
#   ### Key Constraints
#   ...
#   ### Interface Contracts
#   ...
#   ### Acceptance Criteria
#   ...
#   ---
#   ## MILESTONE: M1 -- Docker Runtime
#   ...
#
# Each section is ~400-600 tokens.  action_agentic_build and action_ai_brief
# load ONLY the section for the active milestone -- not the full spec.
# ---------------------------------------------------------------------------

# We own the heading format (## MILESTONE: MX -- label) so this regex
# only needs to match what WE write, not what Claude might produce.
# Separator between sections is always \n\n---\n\n (also written by us).
_DISTIL_SECTION_RE = re.compile(
    r"## MILESTONE:\s*(?P<mid>M\d+[A-Z]?)"
    r"(?:\s*--\s*(?P<label>[^\n]+))?"
    r"\n\n"
    r"(?P<body>.*?)"
    r"(?=\n\n---\n\n##|\Z)",
    re.DOTALL,
)


def distilled_file_path(workplan_stem: str) -> Path:
    return TRACKING_DIR / f"{workplan_stem}.distilled.md"


def _workplan_hash(workplan_stem: str) -> str:
    """
    Return a short SHA-256 hex digest of the workplan spec file's content.

    Used to detect staleness: if the workplan has been edited since the
    distilled file was generated, the hash stored in the distilled file's
    header will no longer match and the caller knows to warn the operator
    to re-run [d].

    Returns "" if no workplan file can be found.
    """
    import hashlib as _hashlib
    wp = find_workplan_file(workplan_stem)
    if wp is None or not wp.exists():
        return ""
    return _hashlib.sha256(wp.read_bytes()).hexdigest()[:12]


def load_milestone_context(workplan_stem: str, milestone_id: str) -> str:
    """
    Return the distilled context block for a specific milestone, or "".

    Falls back to "" gracefully when the distilled file does not yet exist
    (caller should warn the user to run [d] first).

    Staleness check:
        If the distilled file contains a ``Workplan-hash:`` header line and the
        current workplan file has a different hash, a warning is printed.  The
        cached context is still returned (it may be partially valid) but the
        operator is advised to re-run [d] to regenerate it.
    """
    dp = distilled_file_path(workplan_stem)
    if not dp.exists():
        return ""

    text = dp.read_text(encoding="utf-8")

    # ── Staleness check ──────────────────────────────────────────────────────
    # The distilled file header optionally contains:
    #   Workplan-hash: <12-char sha256>
    # If present, compare against the current workplan hash.
    stored_hash_m = re.search(r"Workplan-hash:\s*([a-f0-9]{12})", text)
    if stored_hash_m:
        stored = stored_hash_m.group(1)
        current = _workplan_hash(workplan_stem)
        if current and current != stored:
            _warn(
                f"Distilled context is STALE — workplan has changed since [d] was last run "
                f"(stored hash {stored} ≠ current {current}).  "
                "Run [d] to regenerate; using cached context for now."
            )

    for m in _DISTIL_SECTION_RE.finditer(text):
        if m.group("mid").upper() == milestone_id.upper():
            return m.group("body").strip()
    return ""


def load_spec_content_raw(max_chars: int = 60_000) -> str:
    """
    Load raw spec file content for one-time distillation use only.
    Head/tail truncation applied only when the file exceeds max_chars.
    NOT used by agentic build or brief after distillation exists.
    """
    sp = find_spec_file()
    if sp is None:
        return ""

    raw = sp.read_text(encoding="utf-8")
    if len(raw) <= max_chars:
        return raw

    keep_head = int(max_chars * 0.55)
    keep_tail = int(max_chars * 0.35)
    omitted   = len(raw) - keep_head - keep_tail
    return (
        raw[:keep_head]
        + f"\n\n[... {omitted:,} chars omitted -- middle sections ...] \n\n"
        + raw[-keep_tail:]
    )


def build_state_dump(all_wt: list[WorkplanTracking]) -> str:
    """Build a compact plain-text context dump for Claude prompts."""
    parts: list[str] = []
    for wt in all_wt:
        parts.append(f"=== WORKPLAN: {wt.workplan_name} ===")
        if wt.progress:
            wp = wt.progress
            parts.append(f"Last updated:     {wp.last_updated}")
            parts.append(f"Active milestone: {wp.active_milestone}")
            parts.append(f"Resume at:        {wp.resume_detail}")
            parts.append("\nMILESTONE STATUS:")
            for e in wp.entries:
                suffix = f"  [blocked: {e.blocking_issue}]" if e.blocking_issue else ""
                parts.append(f"  [{e.milestone_id}] {e.label}: {e.status}{suffix}")
        open_issues = [i for i in wt.issues if i.status.upper() != "RESOLVED"]
        if open_issues:
            parts.append("\nOPEN ISSUES:")
            for iss in open_issues:
                parts.append(f"  {iss.number} [{iss.status}] {iss.title}")
                parts.append(f"    Milestone: {iss.milestone}")
                if iss.symptoms:
                    parts.append(f"    Symptoms:  {iss.symptoms[:200]}")
                if iss.fix and iss.fix.lower() not in ("tbd", "-", ""):
                    parts.append(f"    Fix plan:  {iss.fix[:200]}")
        if wt.lessons:
            parts.append("\nLESSONS LEARNED:")
            for ll in wt.lessons:
                parts.append(f"  {ll.number}: {ll.title}")
                parts.append(f"    {ll.lesson[:200]}")
                parts.append(f"    Apply to: {ll.apply_to}")
        parts.append("")
    shared = _parse_lessons(SHARED_LESSONS)
    if shared:
        parts.append("=== SHARED LESSONS (all phases) ===")
        for ll in shared:
            parts.append(f"  {ll.number}: {ll.title}")
            parts.append(f"    {ll.lesson[:200]}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Status colour helper
# ---------------------------------------------------------------------------

def _col(s: str) -> str:
    up = s.upper()
    if up == "DONE":         return f"{C_GREEN}{s}{C_RESET}"
    if up == "IN_PROGRESS":  return f"{C_CYAN}{s}{C_RESET}"
    if up == "BLOCKED":      return f"{C_RED}{s}{C_RESET}"
    if up in ("WORKING", "IDENTIFIED"): return f"{C_YELLOW}{s}{C_RESET}"
    if up == "RESOLVED":     return f"{C_GREEN}{s}{C_RESET}"
    return f"{C_DIM}{s}{C_RESET}"


# ---------------------------------------------------------------------------
# Plain-text brief (fallback when API unavailable)
# ---------------------------------------------------------------------------

def print_plain_brief(all_wt: list[WorkplanTracking]) -> None:
    _h1("FXLab -- Session State (plain)")
    _info(f"Session: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if not all_wt:
        _warn("No tracking files found. Use [b] to bootstrap them.")
        return
    for wt in all_wt:
        _h2(wt.workplan_name)
        if wt.progress:
            wp = wt.progress
            _info(f"Active: {C_BOLD}{wp.active_milestone}{C_RESET} -- {wp.resume_detail}")
            _sep()
            for e in wp.entries:
                note = f"  <- blocked: {e.blocking_issue}" if e.blocking_issue else ""
                print(f"    [{e.milestone_id:3s}] {e.label:<48s} {_col(e.status)}{note}")
        open_issues = [i for i in wt.issues if i.status.upper() != "RESOLVED"]
        if open_issues:
            print()
            for iss in open_issues:
                print(f"  {C_BOLD}{iss.number}{C_RESET} [{_col(iss.status)}] {iss.title}")


# ---------------------------------------------------------------------------
# AI session brief
# ---------------------------------------------------------------------------

_BRIEF_SYSTEM = """\
You are a senior technical program manager reviewing the current state of the
FXLab platform engineering project. You will receive a structured dump of
workplan progress, open issues, and lessons learned across all project phases.

Produce a concise, actionable session brief using EXACTLY this format:

## Session Brief -- <today's date>

### Momentum
One or two sentences on where the project stands overall.

### Top Risks / Blockers
Bullet list. Only real risks visible in the data -- do not invent problems.
Prefix each with: [BLOCKED], [AT RISK], or [MINOR].

### Active Issues Requiring Attention
For each IDENTIFIED or WORKING issue: one line with issue number, title,
and the single most important next action.
If no open issues, say "None."

### Lessons to Apply This Session
If any lessons-learned Apply-to fields match the active milestone, list them
with a one-sentence reminder. If none match, say "None applicable."

### Recommended First Action
One clear, specific sentence describing what the engineer should do first.

Keep the brief under 350 words. Use plain text -- no tables, no code blocks.
Be direct. Do not repeat information that is obvious from the data.
"""


# ---------------------------------------------------------------------------
# Distil action  ([d] menu item)
# ---------------------------------------------------------------------------

_DISTIL_SYSTEM = """You are a senior technical architect preparing implementation context.

You will be given a single milestone ID, its workplan section, and a software spec.
Produce ONLY the four content sections below -- no heading, no preamble, no commentary.
The caller will add the heading. Just produce the four sections starting with ### Spec Context.

### Spec Context
- <2-4 bullets: spec facts directly needed for THIS milestone only>
- <quote exact names, field lists, types, or rules from the spec>

### Key Constraints
- <2-4 bullets: non-negotiable rules from the engineering protocol that apply here>
- <e.g. "All IDs are ULIDs", "Every mutation writes an immutable audit_event">

### Interface Contracts
- <exact class or function name and its architectural layer>
- <API endpoint path and HTTP method if this milestone defines or consumes it>

### Acceptance Criteria
- <exact acceptance criterion from the workplan for this milestone>
- <another criterion>

Rules:
- Under 200 words total. Every word must earn its place.
- Only content relevant to the specified milestone -- nothing from later milestones.
- No implementation code. Only facts from the spec and workplan.
- Do not repeat the milestone heading or ID -- just start with ### Spec Context.

CANONICAL PROJECT CONVENTIONS (repeat in every section's Key Constraints):
- FastAPI app: services/api/main.py — never app.py or any other name
- Route handlers: services/api/routes/<name>.py
- Pydantic schemas/enums: libs/contracts/
- Typed exceptions: libs/contracts/errors.py
- Test fixtures: tests/conftest.py (root), tests/unit/conftest.py, tests/integration/conftest.py
- Never create a second conftest.py — always merge into the existing one
- All IDs are ULIDs — never UUID or auto-increment
"""


def _distil_refresh_section(
    sel: "ActiveSelection",
    dp: Path,
    milestone_id: str,
    all_wt: list[WorkplanTracking],
) -> None:
    """
    Regenerate a single milestone section in the distilled file.
    Incorporates current lessons-learned as extra context -- cheap targeted refresh.
    """
    _h2(f"Refreshing distilled context for {milestone_id}")

    workplan_path = find_workplan_file(sel.workplan_stem)
    if workplan_path is None or not workplan_path.exists():
        _warn("Workplan file not found.")
        return

    # Extract just the milestone section from the workplan
    full_wp = workplan_path.read_text(encoding="utf-8")
    pat = re.compile(
        rf"###\s+Milestone\s+{re.escape(milestone_id)}[\s:].+?"
        rf"(?=\n###\s+Milestone\s+M|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = pat.search(full_wp)
    milestone_spec = m.group(0) if m else f"(milestone {milestone_id} section not found)"

    # Gather relevant lessons from the active workplan
    lessons_text = ""
    for wt in all_wt:
        if wt.workplan_name == sel.workplan_stem and wt.lessons:
            relevant = [
                ll for ll in wt.lessons
                if milestone_id.lower() in ll.apply_to.lower()
                or "all" in ll.apply_to.lower()
            ]
            if relevant:
                lessons_text = "\n".join(
                    f"- {ll.number}: {ll.title}\n  {ll.lesson}"
                    for ll in relevant
                )

    spec_excerpt = ""
    if sel.spec_path and sel.spec_path.exists():
        raw = sel.spec_path.read_text(encoding="utf-8")
        spec_excerpt = raw[:8000]  # just enough for one section

    user_content = (
        f"Regenerate ONLY the section for {milestone_id} in the distilled context file.\n\n"
        f"## Milestone Spec\n\n{milestone_spec}\n\n"
        f"{'## Spec Excerpt (first 8000 chars)' + chr(10) + spec_excerpt + chr(10) + chr(10) if spec_excerpt else ''}"
        f"{'## Lessons Learned' + chr(10) + lessons_text + chr(10) + chr(10) if lessons_text else ''}"
        f"Output ONLY the section block starting with:\n"
        f"## MILESTONE: {milestone_id} -- <label>\n"
        f"(no preamble, no other milestones, end with ---)"
    )

    system = (
        _DISTIL_SYSTEM.split("Output format")[0].strip()
        + "\n\nOutput ONLY the single milestone section requested. "
        "Start with '## MILESTONE: " + milestone_id + "' and end with '---'. "
        "No preamble, no other sections."
    )

    try:
        with Spinner(f"Refreshing {milestone_id} context"):
            result = call_claude(
                system=system,
                messages=[{"role": "user", "content": user_content}],
                max_tokens=2048,
            )
    except RuntimeError as exc:
        _err(f"Refresh failed: {exc}")
        return

    # Splice new section into existing distilled file
    existing = dp.read_text(encoding="utf-8") if dp.exists() else ""
    # Remove the old section for this milestone
    section_pat = re.compile(
        rf"## MILESTONE:\s+{re.escape(milestone_id)}\s*--.+?(?=\n## MILESTONE:|\Z)",
        re.DOTALL,
    )
    if section_pat.search(existing):
        updated = section_pat.sub(result.strip() + "\n\n", existing, count=1)
    else:
        updated = existing.rstrip() + "\n\n" + result.strip() + "\n"

    dp.write_text(updated, encoding="utf-8")
    _ok(f"Section {milestone_id} refreshed in {dp.name}")
    tokens = len(result) // 4
    _info(f"Section size: ~{tokens} tokens")


def action_distil_debug(all_wt: list[WorkplanTracking]) -> None:
    """
    Diagnose a distilled file: show what the regex actually matches and
    print the first 200 chars of the raw file so heading format is visible.
    Use this when the menu shows "0 milestones distilled".
    """
    _h2("Distil debug")
    sel = load_active_selection()
    if sel is None:
        _warn("No workplan selected.")
        return
    dp = distilled_file_path(sel.workplan_stem)
    if not dp.exists():
        _warn(f"No distilled file found: {dp}")
        return

    raw = dp.read_text(encoding="utf-8")
    _info(f"File: {dp}")
    _info(f"Size: {len(raw):,} chars  ({len(raw)//4} tokens approx)")
    print()

    # Show first 400 chars so user can see the actual heading format
    print(f"  {C_BOLD}First 400 chars:{C_RESET}")
    _sep()
    print(raw[:400])
    _sep()
    print()

    # Try the regex and report
    sections = list(_DISTIL_SECTION_RE.finditer(raw))
    if sections:
        _ok(f"Regex matched {len(sections)} section(s):")
        for m in sections:
            tokens = len(m.group("body")) // 4
            print(f"  {C_BOLD}{m.group('mid'):>3s}{C_RESET}  "
                  f"{(m.group('label') or '').strip():<45s}  "
                  f"{C_DIM}~{tokens} tokens{C_RESET}")
    else:
        _err("Regex matched 0 sections.")
        print()
        # Show all ## headings in the file so user can see the actual format
        headings = [ln.strip() for ln in raw.splitlines() if ln.strip().startswith("##")]
        if headings:
            _info(f"Headings found in file ({len(headings)} total):")
            for h in headings[:20]:
                print(f"  {C_DIM}{h}{C_RESET}")
            if len(headings) > 20:
                _info(f"... and {len(headings)-20} more")
        print()
        _warn("The distilled file uses headings that don't match the regex.")
        _warn("Option 1: Delete the file and re-run [d] (the prompt is now stricter).")
        _warn("Option 2: Manually edit headings to '## MILESTONE: MX -- label' format.")
        _info(f"File path: {dp}")


def action_distil(
    all_wt: list[WorkplanTracking],
    refresh_milestone: Optional[str] = None,
) -> None:
    """
    Distil spec + workplan into per-milestone context blocks.

    Full mode (default): send entire spec + workplan, generate all sections.
    Refresh mode (refresh_milestone="M3"): regenerate ONE section only,
      incorporating current lessons-learned for that milestone as extra input.
      Much cheaper than full re-distil -- use when a milestone's context
      has gone stale due to discoveries during implementation.
    """
    _h2("Distil spec into per-milestone context")

    sel = load_active_selection()
    if sel is None:
        _warn("No workplan selected. Use [w] to select one first.")
        return

    workplan_stem = sel.workplan_stem
    dp = distilled_file_path(workplan_stem)

    # ── Refresh mode: regenerate one section only ────────────────────────────
    if refresh_milestone is None and dp.exists():
        answer = input(
            f"  {C_YELLOW}Distilled file exists.  "
            f"[f]ull regen / [r]efresh one milestone / [c]ancel:{C_RESET} "
        ).strip().lower()
        if answer == "c":
            _info("Cancelled.")
            return
        if answer == "r":
            mid = input(
                f"  {C_YELLOW}Milestone to refresh (e.g. M3):{C_RESET} "
            ).strip().upper()
            refresh_milestone = mid if mid else None

    if refresh_milestone:
        _distil_refresh_section(sel, dp, refresh_milestone, all_wt)
        return

    # Full regeneration -- warn if file exists
    if dp.exists():
        size_kb = dp.stat().st_size / 1024
        answer = input(
            f"  {C_YELLOW}Distilled file already exists ({size_kb:.1f} KB).  "
            f"Regenerate all? [y/N]{C_RESET} "
        ).strip().lower()
        if answer != "y":
            _info("Keeping existing distilled file.")
            return

    # Load source material
    workplan_path = find_workplan_file(workplan_stem)
    if workplan_path is None or not workplan_path.exists():
        _warn(f"Workplan file not found for '{workplan_stem}'.")
        _warn("Use [w] to re-select the workplan file.")
        return

    workplan_text = workplan_path.read_text(encoding="utf-8")
    spec_text     = load_spec_content_raw()

    if not spec_text:
        answer = input(
            f"  {C_YELLOW}No spec file selected.  "
            f"Distil from workplan only? [y/N]{C_RESET} "
        ).strip().lower()
        if answer != "y":
            _info("Aborted. Use [w] to select a spec file first.")
            return

    # Estimate and show token counts (rough: 1 token ≈ 4 chars)
    wp_tokens   = len(workplan_text) // 4
    spec_tokens = len(spec_text) // 4
    total_in    = wp_tokens + spec_tokens
    _info(f"Workplan:  ~{wp_tokens:,} tokens")
    _info(f"Spec:      ~{spec_tokens:,} tokens")
    _info(f"Total in:  ~{total_in:,} tokens  (one-time cost)")
    _info(f"Output:    per-milestone context blocks (~400-600 tokens each, reused every build)")

    answer = input(
        f"  {C_YELLOW}Proceed with distillation? [y/N]{C_RESET} "
    ).strip().lower()
    if answer != "y":
        _info("Aborted.")
        return

    # One call per milestone -- we write the heading, Claude writes the content.
    # This eliminates all heading-format parsing failures.
    all_sections: list[str] = []
    call_errors  = 0
    total        = len(MILESTONE_LIST)

    for idx, (mid, label) in enumerate(MILESTONE_LIST, 1):
        # Extract just this milestone's section from the workplan (saves tokens)
        pat = re.compile(
            rf"###\s+Milestone\s+{re.escape(mid)}[\s:].+?"
            rf"(?=\n###\s+Milestone\s+M|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        m = pat.search(workplan_text)
        milestone_spec = m.group(0) if m else f"(section for {mid} not found in workplan)"

        user_msg = (
            f"Milestone: {mid} -- {label}\n\n"
            f"## Workplan section for {mid}\n\n{milestone_spec}\n\n"
            f"## Spec excerpt\n\n"
            f"{spec_text[:4000] if spec_text else '(no spec provided)'}"
        )

        try:
            with Spinner(f"[{idx}/{total}] Distilling {mid} -- {label}"):
                content = call_claude(
                    system=_DISTIL_SYSTEM,
                    messages=[{"role": "user", "content": user_msg}],
                    max_tokens=1024,
                )
        except RuntimeError as exc:
            _err(f"{mid} failed: {exc}")
            call_errors += 1
            all_sections.append(
                f"## MILESTONE: {mid} -- {label}\n\n"
                f"### Spec Context\n- (distillation failed: {exc})\n"
            )
            continue

        # We own the heading -- Claude only produces the four ### subsections
        section = f"## MILESTONE: {mid} -- {label}\n\n{content.strip()}"
        all_sections.append(section)
        _ok(f"{mid} done (~{len(content)//4} tokens)")

    if call_errors == total:
        _err("All milestone calls failed. No distilled file written.")
        return
    if call_errors:
        _warn(f"{call_errors}/{total} milestone(s) failed -- file will have error placeholders.")

    result = "\n\n---\n\n".join(all_sections) + "\n\n<!-- distilled -->\n"
    sections_found = list(_DISTIL_SECTION_RE.finditer(result))
    _info(f"Assembled {len(sections_found)}/13 sections")

    # Pre-flight: count sections before writing so we can warn early
    sections_preview = list(_DISTIL_SECTION_RE.finditer(result))
    if not sections_preview:
        _warn("ZERO sections matched the regex. Showing first 600 chars of Claude output:")
        print()
        print(result[:600])
        print()
        _warn("This usually means Claude used a different heading format.")
        _warn("The file will be saved so you can inspect it manually.")
        _warn(f"Path: {TRACKING_DIR / (workplan_stem + '.distilled.md')}")
        # Still write the file for inspection, then return
        TRACKING_DIR.mkdir(parents=True, exist_ok=True)
        raw_path = TRACKING_DIR / f"{workplan_stem}.distilled.raw.md"
        raw_path.write_text(result, encoding="utf-8")
        _warn(f"Raw output saved to: {raw_path.name}")
        _warn("Edit heading lines to match '## MILESTONE: MX -- label' then re-run [d].")
        return

    # Write distilled file
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    # Embed a hash of the workplan source so load_milestone_context() can detect
    # if the workplan has been edited since this file was generated.
    import hashlib as _hashlib
    wp_hash = (
        _hashlib.sha256(sel.spec_path.read_bytes()).hexdigest()[:12]
        if sel.spec_path and sel.spec_path.exists()
        else "unknown"
    )
    header = (
        f"<!-- FXLab distilled context\n"
        f"     Workplan: {workplan_stem}\n"
        f"     Spec:     {sel.spec_path.name if sel.spec_path else 'none'}\n"
        f"     Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"     Workplan-hash: {wp_hash}\n"
        f"     This file is machine-generated but human-editable.\n"
        f"     Re-run [d] to regenerate, or edit sections directly.\n"
        f"-->\n\n"
    )
    dp.write_text(header + result, encoding="utf-8")

    # Report what was generated
    sections = list(_DISTIL_SECTION_RE.finditer(result))
    out_tokens = len(result) // 4
    _ok(f"Distilled file written: {dp.name}")
    _ok(f"Milestones distilled:   {len(sections)}")
    _ok(f"Output size:            ~{out_tokens:,} tokens total")
    _ok(f"Per-milestone average:  ~{out_tokens // max(len(sections), 1):,} tokens")
    _info(f"Token saving per build: ~{spec_tokens:,} tokens (spec no longer sent raw)")

    print()
    for m in sections:
        ctx_tokens = len(m.group("body")) // 4
        print(f"  {C_BOLD}{m.group('mid'):>3s}{C_RESET}  "
              f"{m.group('label'):<45s}  {C_DIM}~{ctx_tokens} tokens{C_RESET}")

    print()
    _info(f"Path: {dp}")
    _info("Agentic build [a] and Claude brief [c] will now use these sections automatically.")


def action_ai_brief(all_wt: list[WorkplanTracking]) -> None:
    _h2("AI session brief")

    # Scope the brief to the active workplan (+ all shared lessons for cross-phase context)
    active_wt = resolve_active_workplan(all_wt)
    brief_wt = [active_wt] if active_wt else all_wt
    state = build_state_dump(brief_wt)
    if not state.strip():
        _warn("No tracking data to brief on. Run [b] to bootstrap tracking files first.")
        return

    # Prefer distilled per-milestone context over raw spec.
    active_wt   = resolve_active_workplan(all_wt)
    active_stem = active_wt.workplan_name if active_wt else ""
    active_mid  = active_wt.progress.active_milestone if (active_wt and active_wt.progress) else ""

    distilled_ctx = load_milestone_context(active_stem, active_mid) if active_stem and active_mid else ""
    if distilled_ctx:
        _info(f"Using distilled context for {active_mid} (~{len(distilled_ctx)//4} tokens)")
        spec_section = f"\n\n## Milestone Context (distilled)\n\n{distilled_ctx}"
    else:
        dp = distilled_file_path(active_stem) if active_stem else None
        if dp and not dp.exists():
            _warn("No distilled context found -- run [d] to generate per-milestone summaries.")
            _warn("Proceeding without spec context this session.")
        spec_section = ""

    user_msg = (
        f"Today is {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.\n\n"
        f"Project state:\n\n{state}"
        f"{spec_section}"
    )

    try:
        with Spinner("Claude is reviewing project state"):
            response = call_claude(
                system=_BRIEF_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                max_tokens=1024,
            )
        print()
        print(response)
        print()
    except RuntimeError as exc:
        _err(f"AI brief failed: {exc}")
        _warn("Falling back to plain state display.")
        print_plain_brief(all_wt)


# ---------------------------------------------------------------------------
# Agentic milestone execution
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-step system prompts  (improvement #2)
# Each CLAUDE.md step gets a purpose-built prompt that enforces exactly
# what that step should produce and nothing else.
# ---------------------------------------------------------------------------

_STEP_PROMPTS: dict[str, str] = {

"S1": """You are a senior software architect performing a spec review.
You will receive a workplan milestone spec, distilled context, and project state.

OUTPUT ONLY a structured understanding document -- no code, no file blocks.

Format:
## Understanding: <Milestone ID> -- <label>

### What this milestone must deliver
<Bullet list of concrete deliverables>

### Architectural layers touched
<Which onion layers are affected and why>

### Ambiguities or risks
<Any spec gaps, forward dependencies, or decisions that need confirming>

### Ready to proceed?
YES or BLOCKED (with reason)

Keep it under 300 words. Be direct. This output will be saved as the session
understanding record before any implementation begins.
""",

"S2": """You are a senior software architect defining interface contracts.
You will receive a workplan milestone spec and distilled context.

OUTPUT ONLY abstract interfaces, Pydantic v2 schemas, and enums.
DO NOT write any implementation code -- no method bodies, no SQL, no HTTP logic.
If you write anything that is not an abstract class, Protocol, dataclass, or
Pydantic model, that is a violation.

Rules:
- Abstract methods must have only '...' as body (never 'pass' or 'raise').
- Every repository interface must be in a libs/*/interfaces/ directory.
- Every service interface must be in a libs/*/interfaces/ directory.
- Pydantic models go in libs/contracts/.
- Include full type annotations on every field and method signature.
- Include a docstring on every class and abstract method.

Output files using:
<<<FILE: relative/path>>>
<content>
<<<END_FILE>>>

After files, add:
## Interface Summary
- List every class name and its layer (Contract / ServiceInterface / RepositoryInterface)
""",

"S3": """You are a senior software engineer writing a failing test suite (RED phase).
You will receive interface contracts defined in S2 and milestone acceptance criteria.

OUTPUT ONLY test files -- no implementation code whatsoever.
Every test MUST FAIL when run against empty/stub implementations.
If a test would pass without any implementation, it is not a real test.

Rules:
- One test file per service or repository being tested.
- Test files go in tests/unit/ or tests/integration/ as appropriate.
- Use pytest. Use mock/patch for all external dependencies in unit tests.
- Naming: test_<unit>_<scenario>_<expected_outcome>
- Cover: happy path, each error path, dependency failure modes.
- Tests must import from the interface layer, not from any implementation.
- Include a conftest.py with shared fixtures if needed.

Output files using <<<FILE>>> blocks. Nothing else — no commentary, no coverage plans, no explanations after the files.""",

"S4": """You are a senior software engineer writing minimal implementations (GREEN phase).
You will receive failing tests from S3 and interface contracts from S2.

YOUR ONLY GOAL: make the failing tests pass with the minimum code required.
Do not gold-plate. Do not implement features not covered by a test.

Rules:
- Implement exactly the interfaces defined in S2. Do not change the interfaces.
- No TODOs, stubs, or bare 'pass' in any code path that a test exercises.
- Use Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, structlog, ULIDs.
- All repository implementations go in libs/db/ or libs/storage/.
- All service implementations go in the relevant libs/ subdirectory.
- Route handlers go in services/api/routes/ and must be thin (no logic).
- Every external I/O (DB, Redis, MinIO) must be injectable via the interface.
- Add structured log statements at: function entry, state transitions, errors.

Output files using <<<FILE>>> blocks.

After the files, add one short section:
## Next Commands
```bash
<exact pytest command to verify the tests you just wrote pass>
```
Nothing else.""",

"S5": """You are a senior software engineer performing a quality gate review.
Analyse the code written so far against the quality rules below and
output a structured report -- no new implementation files.

Quality rules (from CLAUDE.md):
- No 'except Exception: pass' or bare except.
- No magic numbers/strings without named constants.
- No functions longer than ~50 lines.
- No circular imports between layers.
- No business logic in controllers.
- No concrete repository imports in services.
- Coverage >= 80% overall, >= 85% new code, >= 90% services.

Output format:
## Quality Report: <Milestone>

### Violations Found
<List each violation with file:line and severity: BLOCKER / WARNING>

### Suggested Fixes
<For each BLOCKER, show the corrected code snippet>

### Coverage Gaps
<List any untested paths>

### Verdict
PASS or FAIL (with count of blockers)

If FAIL, output corrected files using <<<FILE>>> blocks after the report.
""",

"S6": """You are a senior software engineer performing a refactor (GREEN is passing).
Tests are passing. Your job is to improve code quality WITHOUT changing behaviour.

Allowed changes:
- Rename for clarity (variables, functions, classes).
- Extract long functions into smaller private helpers.
- Replace magic values with named constants.
- Improve docstrings and inline comments.
- Remove dead code or duplicate logic.

Forbidden changes:
- Do not change any function signature that is part of a public interface.
- Do not change test files (behaviour must remain identical).
- Do not add new features or logic branches.

Output only the files that actually changed using <<<FILE>>> blocks.
If no refactoring is needed, say so explicitly and output no files.
""",

"S7": """You are a senior software engineer writing integration tests.
Unit tests pass. Now write tests that exercise real I/O against
the Docker Compose stack (PostgreSQL, Redis, MinIO).

Rules:
- Integration tests go in tests/integration/.
- Mark each test with @pytest.mark.integration.
- Each test must set up its own state and tear down after.
- Do not mock any infrastructure -- use real connections.
- Test the full path from the API controller down to the DB.
- Include at least: happy path, missing resource (404), auth rejection (403).

Output files using <<<FILE>>> blocks.

After files, add:
## Next Commands
- <docker compose up command>
- <pytest integration test command>
""",

"S8": """You are a senior software engineer performing a final checklist review.
All tests pass, quality gate is clean. Produce a review checklist sign-off.

Output format:
## Review Checklist: <Milestone>

For each item below, write PASS, FAIL, or N/A with a one-line note:

- [ ] All tests pass (unit + integration + contract)
- [ ] Coverage >= threshold
- [ ] No linting or type errors
- [ ] Docstrings complete on all public APIs
- [ ] No TODO without ticket ID
- [ ] No secrets in code or tests
- [ ] Structured logging at all required events
- [ ] Error handling follows retry/no-retry policy
- [ ] Mock/fake implementations match interfaces
- [ ] Commit message follows conventional commits format

### Milestone Completion Status
DONE or NEEDS_WORK (list items that need fixing)

Output no code files unless a blocker requires an immediate fix.
""",
}

# Matches "S1", "S2" ... OR "STEP 1", "STEP 2" (what the progress file writes)
_STEP_ID_RE = re.compile(r"(?:STEP\s+|S)(\d+)", re.IGNORECASE)


def _step_id_from_detail(resume_detail: str) -> str:
    """Extract step ID (S1-S8) from a progress file resume_detail string.

    Handles both formats written by the progress file:
      "STEP 1 -- UNDERSTAND (begin M0 Bootstrap)"  -> S1
      "S4 GREEN"                                   -> S4
    """
    m = _STEP_ID_RE.search(resume_detail)
    if not m:
        return "S4"  # safe default
    n = int(m.group(1))
    if 1 <= n <= 8:
        return f"S{n}"
    return "S4"


def _system_for_step(step_id: str) -> str:
    """Return the appropriate system prompt for the given step ID."""
    return _STEP_PROMPTS.get(step_id.upper(), _STEP_PROMPTS["S4"])


_AGENT_SYSTEM = _STEP_PROMPTS["S4"]  # legacy alias for direct calls



def _extract_files(response: str) -> list[tuple[str, str]]:
    """Parse <<<FILE: path>>> ... <<<END_FILE>>> blocks from a Claude response.

    Tolerates both <<<END_FILE>>> and bare <<<FILE>>> as the closing tag,
    since Claude occasionally uses the wrong closer.
    """
    pattern = re.compile(
        r"<<<FILE:\s*(?P<path>[^\n>]+)>>>\n(?P<content>.*?)(?:<<<END_FILE>>>|<<<FILE>>>)",
        re.DOTALL,
    )
    return [(m.group("path").strip(), m.group("content")) for m in pattern.finditer(response)]


def _extract_next_commands(response: str) -> list[str]:
    """Extract commands from a '## Next Commands' section."""
    m = re.search(r"##\s*Next Commands\s*\n(.*?)(?=\n##|\Z)", response, re.DOTALL)
    if not m:
        return []
    cmds = []
    for line in m.group(1).splitlines():
        s = line.strip().lstrip("-*+").strip()
        if s and not s.startswith("#"):
            cmds.append(s)
    return cmds


def _confirm_write(rel_path: str, content: str) -> bool:
    """
    Kept for compatibility — the agentic build loop no longer calls this.
    Direct writes are used instead.
    """
    return True


# ---------------------------------------------------------------------------
# Prerequisite gate  (improvement #3)
# ---------------------------------------------------------------------------

# Hardcoded dependency chain matching the workplan milestone graph.
# Key = milestone that has prerequisites; value = list of required-DONE milestones.
_MILESTONE_DEPS: dict[str, list[str]] = {
    "M1":  ["M0"],
    "M2":  ["M1"],
    "M3":  ["M2"],
    "M4":  ["M3"],
    "M5":  ["M4"],
    "M6":  ["M5"],
    "M7":  ["M6"],
    "M8":  ["M7"],
    "M9":  ["M2", "M7"],
    "M10": ["M4", "M7"],
    "M11": ["M4", "M8", "M10"],
    "M12": ["M0","M1","M2","M3","M4","M5","M6","M7","M8","M9","M10","M11"],
}


def check_prerequisites(
    active_wt: WorkplanTracking, milestone_id: str
) -> tuple[bool, list[str]]:
    """
    Check that all prerequisite milestones are DONE in the progress file.
    Returns (ok, list_of_blocking_milestone_ids).
    """
    if active_wt.progress is None:
        return True, []  # can't check, don't block

    required = _MILESTONE_DEPS.get(milestone_id.upper(), [])
    if not required:
        return True, []

    done_ids = {
        e.milestone_id.upper()
        for e in active_wt.progress.entries
        if e.status == "DONE"
    }
    blocking = [r for r in required if r.upper() not in done_ids]
    return len(blocking) == 0, blocking


# ---------------------------------------------------------------------------
# Contract fingerprinting  (improvement #8)
# ---------------------------------------------------------------------------
# After S2 (INTERFACE FIRST) completes, hash the interface files and store
# fingerprints in the progress file under a special comment block.
# Before building downstream milestones, verify hashes have not drifted.
# ---------------------------------------------------------------------------

_FINGERPRINT_MARKER = "# CONTRACT_FINGERPRINTS:"


def _hash_file(path: Path) -> str:
    """Return sha256 hex digest of a file's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _find_interface_files() -> list[Path]:
    """Collect all Python files in libs/*/interfaces/ directories."""
    result: list[Path] = []
    for idir in (PROJECT_ROOT / "libs").glob("*/interfaces"):
        if idir.is_dir():
            result.extend(sorted(idir.rglob("*.py")))
    return result


def store_contract_fingerprints(progress_path: Path, milestone_id: str) -> dict[str, str]:
    """
    Hash all interface files and append a fingerprint block to the progress file.
    Returns the fingerprint dict {relative_path: hash}.
    """
    ifiles = _find_interface_files()
    if not ifiles:
        return {}

    fps: dict[str, str] = {}
    for fp in ifiles:
        rel = str(fp.relative_to(PROJECT_ROOT))
        fps[rel] = _hash_file(fp)

    # Append to progress file
    text = progress_path.read_text(encoding="utf-8")
    # Remove any existing fingerprint block
    text = re.sub(
        re.escape(_FINGERPRINT_MARKER) + r".*?(?=\n#|\Z)",
        "",
        text,
        flags=re.DOTALL,
    ).rstrip() + "\n"
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = (
        "\n"
        + _FINGERPRINT_MARKER
        + f" milestone={milestone_id} ts={now_ts}\n"
    )
    for rel, h in fps.items():
        block += f"#   {h}  {rel}\n"
    progress_path.write_text(text + block, encoding="utf-8")
    return fps


def check_contract_fingerprints(progress_path: Path) -> tuple[bool, list[str]]:
    """
    Re-hash current interface files and compare against stored fingerprints.
    Returns (ok, list_of_drifted_files).
    """
    if not progress_path.exists():
        return True, []

    text = progress_path.read_text(encoding="utf-8")
    pattern = re.escape(_FINGERPRINT_MARKER) + r".*?\n((?:#   .+\n)*)"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return True, []  # no fingerprints stored yet

    stored: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("#").strip()
        if "  " in line:
            h, _, rel = line.partition("  ")
            stored[rel.strip()] = h.strip()

    drifted: list[str] = []
    for rel, stored_hash in stored.items():
        fp = PROJECT_ROOT / rel
        if not fp.exists():
            drifted.append(f"{rel} (DELETED)")
        elif _hash_file(fp) != stored_hash:
            drifted.append(f"{rel} (MODIFIED)")
    return len(drifted) == 0, drifted


# ---------------------------------------------------------------------------
# Contract completeness AST check  (improvement #7)
# ---------------------------------------------------------------------------

def _method_names_from_contracts_section(distilled_text: str) -> list[str]:
    """
    Extract method/function names mentioned in an '### Interface Contracts'
    section of a distilled context block.  Looks for patterns like
    'def foo(', 'foo(', or '- foo' followed by '('.
    """
    section_m = re.search(
        r"###\s+Interface Contracts\s*\n(.*?)(?=\n###|\Z)",
        distilled_text, re.DOTALL | re.IGNORECASE,
    )
    if not section_m:
        return []
    section = section_m.group(1)
    # Match bare method names: word chars followed by optional whitespace then (
    names = re.findall(r"([a-z_][a-z0-9_]{2,})\s*\(", section, re.IGNORECASE)
    # Exclude Python builtins and common noise words
    skip = {
        "def", "class", "if", "for", "while", "return", "raise", "print",
        "isinstance", "hasattr", "getattr", "setattr", "len", "str", "int",
        "dict", "list", "tuple", "set", "type", "super", "object",
    }
    return [n for n in names if n.lower() not in skip]


def _method_names_in_files(written_paths: list[str]) -> set[str]:
    """Extract all function/method names defined in a list of Python files."""
    names: set[str] = set()
    for rel in written_paths:
        fp = PROJECT_ROOT / rel
        if not fp.exists() or fp.suffix != ".py":
            continue
        try:
            tree = ast.parse(fp.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
    return names


def run_contract_completeness_check(
    written_paths: list[str],
    distilled_ctx: str,
) -> tuple[bool, list[str]]:
    """
    After GREEN step, verify that every method name listed in the distilled
    Interface Contracts section exists somewhere in the written files.
    Returns (ok, list_of_missing_names).
    """
    expected = _method_names_from_contracts_section(distilled_ctx)
    if not expected:
        return True, []

    defined = _method_names_in_files(written_paths)
    missing = [n for n in expected if n not in defined]
    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# Test runner with failure capture (for iteration loop)
# ---------------------------------------------------------------------------

def _extract_missing_modules(output: str) -> list[str]:
    """
    Parse pytest output for ModuleNotFoundError / ImportError and return
    the list of missing top-level package names that can be pip-installed.
    """
    # Match any "No module named 'x'" regardless of prefix
    hits = re.findall(
        r"No module named ['\"](\w[\w\-]*)",
        output,
    )
    # Map common import names to installable package names
    _install_map = {
        "ulid":              "python-ulid",
        "pydantic":          "pydantic",
        "fastapi":           "fastapi",
        "sqlalchemy":        "sqlalchemy",
        "structlog":         "structlog",
        "celery":            "celery",
        "redis":             "redis",
        "boto3":             "boto3",
        "polars":            "polars",
        "pyarrow":           "pyarrow",
        "jose":              "python-jose",
        "passlib":           "passlib",
        "tenacity":          "tenacity",
        "httpx":             "httpx",
        "alembic":           "alembic",
        "psycopg2":          "psycopg2-binary",
        "opentelemetry":     "opentelemetry-sdk",
        "prometheus_client": "prometheus-client",
        "APScheduler":       "apscheduler",
        "apscheduler":       "apscheduler",
        "ulid_py":           "python-ulid",
        "python_ulid":       "python-ulid",
    }
    packages = []
    for mod in hits:
        pkg = _install_map.get(mod, mod)
        if pkg not in packages:
            packages.append(pkg)
    return packages


def run_tests_capture(test_dir: str = "tests/", auto_fix_imports: bool = True) -> tuple[bool, str]:
    """
    Run pytest and capture output.  Returns (passed, failure_output).

    If auto_fix_imports=True (default), detects ModuleNotFoundError lines
    in the output, pip-installs the missing packages, and retries once.
    This handles the common case where generated code or fixtures import
    a package that hasn't been installed yet.
    """
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "pytest", test_dir,
         "--tb=short", "-q", "--no-header"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    output = (result.stdout + result.stderr).strip()

    if result.returncode != 0 and auto_fix_imports:
        missing = _extract_missing_modules(output)
        if missing:
            install_result = subprocess.run(
                [str(VENV_PIP), "install"] + missing + ["--quiet"],
                capture_output=True,
            )
            if install_result.returncode == 0:
                _append_to_requirements_dev(missing)
                result = subprocess.run(
                    [str(VENV_PYTHON), "-m", "pytest", test_dir,
                     "--tb=short", "-q", "--no-header"],
                    capture_output=True, text=True, cwd=str(PROJECT_ROOT),
                )
                output = (result.stdout + result.stderr).strip()

    passed = result.returncode == 0
    return passed, ("" if passed else output)


def _append_to_requirements_dev(packages: list[str]) -> None:
    """Add newly discovered packages to requirements-dev.txt."""
    req_file = REQUIREMENTS_DEV
    existing = set()
    if req_file.exists():
        for line in req_file.read_text(encoding="utf-8").splitlines():
            existing.add(line.strip().split("==")[0].split(">=")[0].lower())

    new_lines = [
        p for p in packages
        if p.lower() not in existing and p.lower().replace("-","_") not in existing
    ]
    if new_lines:
        with open(req_file, "a", encoding="utf-8") as fh:
            for p in new_lines:
                fh.write(f"{p}\n")
        _info(f"Added to {req_file.name}: {', '.join(new_lines)}")


# ---------------------------------------------------------------------------
# Progress file auto-advance  (improvement #4)
# ---------------------------------------------------------------------------

def _step_sequence() -> list[str]:
    return [sid for sid, _ in STEP_LABELS]


def advance_progress_step(
    progress_path: Path, milestone_id: str, completed_step_id: str
) -> Optional[str]:
    """
    Mark completed_step_id as DONE for milestone_id and advance Active step.
    Returns the next step ID, or None if the milestone is now fully complete.
    Updates the progress file in-place.
    """
    if not progress_path.exists():
        return None

    text = progress_path.read_text(encoding="utf-8")
    seq  = _step_sequence()

    # Capture group wraps the entire "  [MX-SY] label  " prefix so re.sub
    # preserves it. Without this the bracket expression is consumed and dropped,
    # making the line unparseable on the next read.
    text = re.sub(
        r"(\s+\[" + re.escape(f"{milestone_id}-{completed_step_id}") + r"\][^\n]+?)"
        r"(NOT_STARTED|IN_PROGRESS)",
        r"\1DONE",
        text,
    )

    try:
        current_idx = seq.index(completed_step_id.upper())
        next_step   = seq[current_idx + 1] if current_idx + 1 < len(seq) else None
    except ValueError:
        next_step = None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = re.sub(r"^# Last updated:.*$", f"# Last updated: {now}", text, flags=re.MULTILINE)

    if next_step:
        next_label = next((lbl for sid, lbl in STEP_LABELS if sid == next_step), next_step)
        new_active = f"STEP {seq.index(next_step)+1} -- {next_label} ({milestone_id})"
        text = re.sub(
            r"^# Active step:.*$", f"# Active step: {new_active}", text, flags=re.MULTILINE
        )
        text = re.sub(
            r"(\s+\[" + re.escape(f"{milestone_id}-{next_step}") + r"\][^\n]+?)NOT_STARTED",
            r"\1IN_PROGRESS",
            text,
        )
    else:
        text = re.sub(
            r"(\[" + re.escape(milestone_id) + r"\][^\n]+?)(IN_PROGRESS|NOT_STARTED)",
            r"\1DONE",
            text,
        )
        text = re.sub(
            r"^# Active step:.*$",
            f"# Active step: {milestone_id} COMPLETE -- advance Active milestone",
            text, flags=re.MULTILINE,
        )

    progress_path.write_text(text, encoding="utf-8")
    return next_step


# ---------------------------------------------------------------------------
# Auto-commit helper  (improvement #6)
# ---------------------------------------------------------------------------

def _git_available() -> bool:
    return shutil.which("git") is not None


def _git_status_clean() -> bool:
    """True if there are staged or unstaged changes (i.e. something to commit)."""
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    return bool(r.stdout.strip())


def action_auto_commit(milestone_id: str, step_id: str, step_label: str) -> None:
    """
    Stage all changes and commit with a conventional commit message.
    Prompts for confirmation before committing.
    """
    if not _git_available():
        _warn("git not found -- skipping auto-commit.")
        return
    if not _git_status_clean():
        _info("No changes to commit.")
        return

    msg = (
        f"feat({milestone_id.lower()}-{step_id.lower()}): "
        f"{step_label.lower().replace(' -- ', ' ')}"
    )
    print(f"\n  {C_BOLD}Proposed commit message:{C_RESET}")
    print(f"  {C_CYAN}{msg}{C_RESET}")
    answer = input(
        f"  {C_YELLOW}Commit all changes? [y/N/e=edit]{C_RESET} "
    ).strip().lower()
    if answer == "e":
        try:
            msg = input(f"  {C_YELLOW}Enter commit message:{C_RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            _info("Commit cancelled.")
            return
    if answer not in ("y", "e") and not (answer == "e" and msg):
        _info("Commit skipped.")
        return

    subprocess.run(["git", "add", "-A"], cwd=str(PROJECT_ROOT), check=False)
    r = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if r.returncode == 0:
        _ok(f"Committed: {msg}")
        _info(r.stdout.strip())
    else:
        _err("Commit failed:")
        print(r.stderr.strip())


# ---------------------------------------------------------------------------
# Session handoff  (improvement #5)
# ---------------------------------------------------------------------------

_HANDOFF_SYSTEM = """You are a senior engineering manager writing a session handoff document.
You will receive:
  - A git diff summary (files changed this session)
  - Current project progress state
  - Any new issues opened or resolved this session

Produce a HANDOFF.md that the next session will read as its first context.

Format:
## Session Handoff -- <date>

### What was accomplished this session
<Bullet list of concrete deliverables, referencing milestone/step IDs>

### Decisions made
<Any architectural or implementation decisions made during this session
that are not obvious from the code. Include the reasoning.>

### Current state
<Where exactly in the build we are: milestone, step, what passes, what doesn't>

### Immediate next action
<One specific sentence: the first thing to do in the next session>

### Watch out for
<Any gotchas, partial work, or known issues the next session must be aware of>

Keep it under 400 words. Be direct. This replaces a verbal handoff.
"""


def action_handoff(all_wt: list[WorkplanTracking], api_ok: bool) -> None:
    """
    Generate a HANDOFF.md session summary using Claude.
    Reads git diff --stat for changed files, current progress state,
    and recent issues to produce a structured handoff document.
    """
    _h2("Generating session handoff")

    # Get git diff summary
    git_diff = ""
    if _git_available():
        r = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT),
        )
        git_diff = r.stdout.strip()
        if not git_diff:
            # Try against last commit if nothing staged
            r2 = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True, text=True, cwd=str(PROJECT_ROOT),
            )
            git_diff = r2.stdout.strip() or "(no changes detected -- already committed)"
    else:
        git_diff = "(git not available)"

    state_dump = build_state_dump(all_wt)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_content = (
        f"Today is {today}.\n\n"
        f"## Git changes this session\n\n{git_diff}\n\n"
        f"## Project state\n\n{state_dump}"
    )

    handoff_path = TRACKING_DIR / "HANDOFF.md"

    if not api_ok:
        # Write a plain handoff without AI synthesis
        TRACKING_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = (
            f"# Session Handoff -- {today}\n\n"
            f"## Git changes\n\n```\n{git_diff}\n```\n\n"
            f"## Project state\n\n```\n{state_dump}\n```\n"
        )
        handoff_path.write_text(content, encoding="utf-8")
        _ok(f"Plain handoff written (no API key): {handoff_path.name}")
        return

    try:
        with Spinner("Claude is writing session handoff"):
            response = call_claude(
                system=_HANDOFF_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
                max_tokens=1024,
            )
    except RuntimeError as exc:
        _err(f"Handoff generation failed: {exc}")
        return

    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(response, encoding="utf-8")
    _ok(f"Handoff written: {handoff_path}")
    print()
    print(response)


def _collect_milestone_test_files(milestone_id: str) -> list[str]:
    """
    Return relative paths of test files that are likely associated with
    ``milestone_id``.

    Strategy:
        1. Test files whose name contains the lowercase milestone slug
           (e.g. ``test_m1_*.py``, ``test_milestone_1_*.py``).
        2. If none are found that way, fall back to ALL test files under
           ``tests/`` — wide net is safer for the coherence gate because a
           false-positive warning is lower cost than a missed gap.

    Args:
        milestone_id: Milestone identifier string such as ``"M1"`` or
                      ``"milestone-1-project-setup"``.

    Returns:
        Sorted list of relative file paths (may be empty if tests/ missing).

    Example:
        _collect_milestone_test_files("M1")
        # → ["tests/unit/test_m1_health.py", "tests/unit/test_m1_models.py"]
    """
    test_root = PROJECT_ROOT / "tests"
    if not test_root.exists():
        return []

    all_tests = sorted(str(p.relative_to(PROJECT_ROOT)) for p in test_root.rglob("test_*.py"))

    # Build candidate slug patterns from the milestone ID
    slug = milestone_id.lower().replace("-", "_").replace(" ", "_")
    # Also try just the numeric part (e.g. "m1" → "1")
    numeric = re.sub(r"[^0-9]", "", slug)
    patterns = [slug]
    if numeric:
        patterns.append(f"m{numeric}_")
        patterns.append(f"m{numeric}.")
        patterns.append(f"_{numeric}_")

    matched = [
        t for t in all_tests
        if any(pat in Path(t).name.lower() for pat in patterns)
    ]
    return matched if matched else all_tests


def _collect_failing_test_files(test_output: str) -> list[str]:
    """
    Parse pytest output and return a deduplicated list of test file paths
    that had at least one failure or error.  Handles:
      FAILED tests/foo.py::Class::method
      ERROR  tests/foo.py - ImportError
      ERROR collecting tests/foo.py
    """
    pattern = re.compile(
        r"(?:FAILED|ERROR)\s+(?:collecting\s+)?(tests/[^\s:]+\.py)",
        re.MULTILINE,
    )
    return sorted(set(pattern.findall(test_output)))


def _run_specific_tests(test_path: str) -> tuple[bool, str]:
    """Run pytest against a single file. Auto-installs missing imports."""
    passed, output = run_tests_capture(test_dir=test_path, auto_fix_imports=True)
    return passed, output


def _rollback_writes_since(wname: str, since_ts: str) -> int:
    """
    Restore every file that the write journal logged at or after ``since_ts``.

    Responsibilities:
    - Read the JSONL write journal for ``wname``.
    - Reverse all entries whose ``ts`` field >= ``since_ts`` (most-recent first
      so intermediate states don't bleed through).
    - If a prior version exists in the entry, write it back; otherwise delete
      the file (it was newly created by the agent and did not exist before).

    Does NOT:
    - Truncate the journal (entries remain for audit purposes).
    - Raise on missing journal — returns 0 silently.

    Args:
        wname:    Workplan name (used to locate the journal file).
        since_ts: ISO-8601 timestamp string.  All journal entries at or after
                  this timestamp are rolled back.

    Returns:
        Number of files restored (0 if journal missing or no matching entries).

    Example:
        ts = datetime.now(timezone.utc).isoformat()
        # ... writes happen ...
        n = _rollback_writes_since(wname, ts)
        # all writes since ts have been undone
    """
    import json as _json
    journal = TRACKING_DIR / f"{wname}.write-journal.jsonl"
    if not journal.exists():
        return 0
    all_records = [
        _json.loads(ln)
        for ln in journal.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    to_restore = [r for r in all_records if r.get("ts", "") >= since_ts]
    restored = 0
    for r in reversed(to_restore):
        dest = PROJECT_ROOT / r["path"]
        if r.get("prev"):
            dest.write_text(r["prev"], encoding="utf-8")
        elif dest.exists():
            dest.unlink(missing_ok=True)
        restored += 1
    return restored


def _run_blast_radius_check(
    at_risk: "list[str]",
    wname: str,
    since_ts: str,
) -> "tuple[bool, list[str], int]":
    """
    Run ``at_risk`` tests immediately after a file write to detect blast-radius
    regressions before they compound.

    If any of the at-risk tests now fail, roll back ALL writes logged since
    ``since_ts`` — restoring the codebase to the pre-write state for those
    files — and report which tests regressed.

    This is the mechanistic complement to the blast-radius prompt section:
    we told the LLM which tests it must not break (prompt-time constraint);
    this function VERIFIES the constraint was honoured (write-time enforcement)
    and auto-repairs the damage if it wasn't.

    Responsibilities:
    - Run all ``at_risk`` test files in a single pytest invocation (fast --tb=line).
    - If all pass: return (True, [], 0) — no regression, no rollback.
    - If any fail: roll back via ``_rollback_writes_since``, return failed list
      and rollback count so the caller can log and skip this file.

    Does NOT:
    - Retry or re-attempt the fix — caller is responsible for that.
    - Modify ``_passing_tests`` or ``_reverse_map`` — they are round-level state.

    Args:
        at_risk:   Passing tests that share source dependencies with the file
                   just fixed.  From ``_blast_radius_tests()``.
        wname:     Workplan name (for rollback journal lookup).
        since_ts:  Timestamp recorded just before the write — all journal
                   entries at or after this timestamp are eligible for rollback.

    Returns:
        (all_passed, newly_failing_test_files, n_files_rolled_back)

    Example:
        ts = datetime.now(timezone.utc).isoformat()
        new_paths, _ = _targeted_implement(...)
        ok, regressed, rolled = _run_blast_radius_check(at_risk, wname, ts)
        if not ok:
            _err(f"blast-radius regression: {regressed}; rolled back {rolled} file(s)")
    """
    if not at_risk:
        return True, [], 0

    # Single pytest invocation across all at-risk files — faster than N calls
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "pytest"] + at_risk
        + ["--tb=line", "-q", "--no-header"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    output = (result.stdout + result.stderr).strip()

    if result.returncode == 0:
        return True, [], 0     # constraint honoured — no blast-radius regressions

    # Constraint violated — identify which at-risk tests now fail
    newly_failing = _collect_failing_test_files(output)

    # Roll back ALL writes from this attempt so the regression doesn't
    # compound.  The next file in the inner loop will see a clean baseline.
    n_rolled = _rollback_writes_since(wname, since_ts)

    return False, newly_failing, n_rolled


def _load_test_file(rel_path: str) -> str:
    """Read a test file relative to the project root."""
    p = PROJECT_ROOT / rel_path
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _merge_conftest(existing: str, new: str) -> str:
    """Append fixture functions from `new` that don't exist in `existing`."""
    existing_fns = set(re.findall(r"^def (\w+)", existing, re.MULTILINE))
    new_imports = [
        l for l in new.splitlines()
        if l.startswith(("import ", "from ")) and l not in existing
    ]
    blocks: list[str] = []
    current: list[str] = []
    capture = False
    for line in new.splitlines():
        fn = re.match(r"^def (\w+)", line)
        if re.match(r"^@pytest\.fixture", line) or fn:
            if current and capture:
                blocks.append("\n".join(current))
            current = [line]
            capture = fn is not None and fn.group(1) not in existing_fns
        elif current:
            current.append(line)
    if current and capture:
        blocks.append("\n".join(current))
    if not new_imports and not blocks:
        return ""
    parts = [existing.rstrip()]
    if new_imports:
        parts.append("\n# -- merged imports --")
        parts.extend(new_imports)
    if blocks:
        parts.append("")
        parts.extend(blocks)
    return "\n".join(parts) + "\n"


def _accumulator_merge(existing: str, proposed: str, source_hint: str = "") -> str:
    """
    Merge a proposed Python source into an existing accumulator file.

    Merge policy (protects cross-milestone work while enabling fixes):
    - **Update** existing symbols — if both files have symbol X, the proposed
      version replaces the existing one.  This allows the agent to FIX a broken
      implementation, not just add new ones.
    - **Add** new symbols — symbols that exist only in proposed are appended.
    - **Never delete** — symbols that exist only in existing are preserved.
      This is the cross-milestone protection: a symbol added by M0 is never
      removed when M22's agent touches the same file.

    The old "add-only" policy caused a deadlock: when a symbol existed but was
    broken, the merge refused to update it, so the test could never be fixed
    no matter how many LLM calls were made.

    Uses Python AST for reliable symbol detection.  Falls back to returning the
    existing content unchanged if either file fails to parse — it is always safer
    to keep a known-good file than to corrupt it.

    Args:
        existing:     Content currently on disk.
        proposed:     Content the agent wants to write.
        source_hint:  Optional label for the merge comment (e.g. the file path).

    Returns:
        Merged source string.  Returns ``existing`` as-is if nothing changed.

    Example:
        # Existing has RunStatus (wrong impl); proposed fixes it + adds StrategyType
        merged = _accumulator_merge(existing, proposed, "libs/contracts/enums.py")
        # → RunStatus replaced with proposed version, StrategyType appended
    """
    import ast as _ast

    try:
        existing_tree = _ast.parse(existing)
        proposed_tree = _ast.parse(proposed)
    except SyntaxError:
        # Unparseable → preserve existing, don't risk a corrupt overwrite
        return existing

    # ── Build a lookup: symbol_name → (start_lineno_0idx, end_lineno_exclusive) ──
    # for BOTH the existing file and the proposed file.  We need line spans so we
    # can splice in updated symbol bodies from the proposed source.

    def _symbol_spans(tree: "_ast.Module") -> "dict[str, tuple[int,int]]":
        """Return {name: (start_0idx, end_exclusive)} for all top-level symbols."""
        spans: dict[str, tuple[int, int]] = {}
        for node in tree.body:
            name: str | None = None
            if isinstance(node, (_ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, _ast.Assign):
                for target in node.targets:
                    if isinstance(target, _ast.Name):
                        name = target.id
                        break
            if name:
                end = getattr(node, "end_lineno", None)
                if end is not None:
                    spans[name] = (node.lineno - 1, end)
        return spans

    existing_spans = _symbol_spans(existing_tree)
    proposed_spans = _symbol_spans(proposed_tree)

    existing_lines  = existing.splitlines()
    proposed_lines  = proposed.splitlines()

    # ── Merge strategy ────────────────────────────────────────────────────────
    # Policy: ADD new symbols + UPDATE existing symbols.  NEVER delete a symbol
    # that is in existing but absent from proposed — that protects symbols added
    # by earlier milestones that the current agent doesn't know about.
    #
    # "Update" means: if a symbol exists in both files, replace the existing
    # version with the proposed version in the output.  This is what allows the
    # agent to FIX a broken implementation, not just add new ones.
    #
    # We reconstruct the file by:
    #   1. Walk existing top-level statements in order.
    #   2. For each named symbol: if proposed has a newer version, use proposed.
    #      Otherwise keep existing.
    #   3. For non-named top-level statements (imports, __all__, constants not
    #      matching a name): keep existing version.  If proposed has extra
    #      imports/constants, append them at the end.
    #   4. Append any NEW symbols from proposed that don't exist in existing.

    # Reconstruct existing body with selective updates
    output_lines: list[str] = []
    cursor = 0          # tracks how far through existing_lines we've consumed
    updated: set[str] = set()

    for node in existing_tree.body:
        start_0 = node.lineno - 1
        end_exc  = getattr(node, "end_lineno", node.lineno)

        # Emit any gap between cursor and this node (blank lines, decorators
        # that appear before the node but after the previous one)
        output_lines.extend(existing_lines[cursor:start_0])
        cursor = end_exc  # advance past this node

        # Determine if this node has a named symbol
        sym_name: str | None = None
        if isinstance(node, (_ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
            sym_name = node.name
        elif isinstance(node, _ast.Assign):
            for target in node.targets:
                if isinstance(target, _ast.Name):
                    sym_name = target.id
                    break

        if sym_name and sym_name in proposed_spans:
            # Proposed has an updated version — use it
            ps, pe = proposed_spans[sym_name]
            output_lines.extend(proposed_lines[ps:pe])
            updated.add(sym_name)
        else:
            # No update — keep existing
            output_lines.extend(existing_lines[start_0:end_exc])

    # Emit any trailing content in existing after the last symbol
    output_lines.extend(existing_lines[cursor:])

    # ── Append new symbols from proposed that don't exist in existing ─────────
    new_blocks: list[str] = []
    for sym_name, (ps, pe) in proposed_spans.items():
        if sym_name not in existing_spans:
            new_blocks.append("\n".join(proposed_lines[ps:pe]))

    if not new_blocks and not updated:
        return existing  # nothing changed — leave file untouched

    result = "\n".join(output_lines).rstrip()
    if new_blocks:
        hint = f"\n\n# -- new symbols merged: {source_hint} --\n" if source_hint else "\n\n"
        result += hint + "\n\n".join(new_blocks)
    result += "\n"

    # Sanity check: result must parse cleanly
    try:
        _ast.parse(result)
    except SyntaxError:
        # If the merge produced invalid Python (e.g. decorator edge-case),
        # fall back to the safe add-only approach to avoid corrupting the file.
        append_only: list[str] = []
        for sym_name, (ps, pe) in proposed_spans.items():
            if sym_name not in existing_spans:
                append_only.append("\n".join(proposed_lines[ps:pe]))
        if not append_only:
            return existing
        result = existing.rstrip() + "\n\n" + "\n\n".join(append_only) + "\n"

    return result


def _parse_failure_cases(failure_output: str, test_file: str) -> list[dict]:
    """
    Parse pytest --tb=short output into structured failure cases.
    Returns a list of dicts with keys: test_name, error_type, error_message, location.
    """
    cases = []
    # Split on FAILED / ERROR lines
    blocks = re.split(r"\n(?=FAILED|ERROR)", failure_output)
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue
        header = lines[0]
        # Extract test name
        name_m = re.match(r"(?:FAILED|ERROR)\s+([^\s]+)", header)
        if not name_m:
            continue
        test_name = name_m.group(1)
        # Find the error line (starts with E  )
        error_lines = [l.lstrip() for l in lines if l.strip().startswith("E ")]
        error_text  = " ".join(l[2:].strip() for l in error_lines[:3]) if error_lines else header
        # Find the location line (file:line)
        loc_m = re.search(r"(\S+\.py):(\d+):", block)
        location = f"{loc_m.group(1)}:{loc_m.group(2)}" if loc_m else ""
        cases.append({
            "test":     test_name,
            "error":    error_text[:300],
            "location": location,
        })
    return cases


def _read_existing_implementations(test_content: str) -> dict[str, str]:
    """
    From the imports in the test file, find which implementation files
    already exist and return their content (for Claude to see what it wrote).
    Limits each file to 100 lines to stay within token budget.
    """
    found = {}
    import_re = re.compile(r"^(?:from|import)\s+(libs\.[\w.]+|services\.[\w.]+)", re.MULTILINE)
    for m in import_re.finditer(test_content):
        module_path = m.group(1).replace(".", "/")
        # Try both module.py and module/__init__.py
        for candidate in [f"{module_path}.py", f"{module_path}/__init__.py"]:
            p = PROJECT_ROOT / candidate
            if p.exists():
                lines = p.read_text(encoding="utf-8").splitlines()
                preview = "\n".join(lines[:100])
                if len(lines) > 100:
                    preview += f"\n# ... ({len(lines)-100} more lines)"
                found[candidate] = preview
    return found




# ---------------------------------------------------------------------------
# Known-fix registry
# Deterministic patches for common failure patterns.
# Applied automatically when the failure message matches a pattern.
# ---------------------------------------------------------------------------

_KNOWN_FIXES: list[tuple[str, str, str]] = [
    # (failure_pattern, file_to_write, content)
    # Each entry: if failure_output contains pattern, write content to file.
]


def _apply_known_fixes(failure_output: str, wname: str) -> list[str]:
    """
    Check failure output against the known-fix registry and apply any matches.
    Returns list of files written.
    """
    written = []
    for pattern, rel_path, content in _KNOWN_FIXES:
        if pattern in failure_output:
            dest = PROJECT_ROOT / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            _journal_write(rel_path, content, wname)
            dest.write_text(content, encoding="utf-8")
            _ok(f"Known fix applied: {rel_path}")
            written.append(rel_path)
    return written


def _register_known_fix(pattern: str, rel_path: str, content: str) -> None:
    """Add a fix to the registry. Called when a fix is applied manually."""
    _KNOWN_FIXES.append((pattern, rel_path, content))


def _classify_failure(failure_output: str) -> str:
    """
    Classify a pytest failure into one of five error buckets.

    Each bucket requires a different remediation strategy; mis-classifying a
    failure leads to the wrong prompt being sent to the LLM, which is the
    most common cause of a fix attempt making things worse.

    Returns one of:
      "structural"   — ModuleNotFoundError, missing __init__.py, missing
                       file/directory.  Fix deterministically first via
                       _ensure_package_inits(); only call LLM if still failing.

      "interface"    — AttributeError on a class (missing method/property),
                       TypeError on a call (wrong number/type of args),
                       or abstract-method-not-implemented errors.
                       Prompt: "check the interface definition and implement
                       the missing method with the correct signature."

      "assertion"    — AssertionError with actual/expected values visible.
                       Prompt: "the implementation exists but returns the wrong
                       value — focus on the assertion failure, not the imports."

      "fixture"      — pytest fixture not found (conftest.py gap).
                       Prompt: "add the missing fixture to conftest.py."

      "schema"       — Pydantic ValidationError or similar schema mismatch.
                       Prompt: "correct the data structure / field types to
                       match the Pydantic model definition."

      "logic"        — Everything else; general implementation problem.

    Rationale:
        Sending the same boilerplate prompt for an AssertionError as for a
        ModuleNotFoundError is wasteful.  Type-specific prompts reduce the
        number of rounds needed because Claude already knows what kind of
        problem it is solving.
    """
    # Structural: missing packages / files
    if re.search(r"ModuleNotFoundError|No module named '", failure_output):
        return "structural"
    if re.search(
        r"must exist|must be a directory"
        r"|assert.*\.exists\(\)"
        r"|assert.*\.is_dir\(\)"
        r"|__init__\.py must exist",
        failure_output,
    ):
        return "structural"

    # Interface: missing attribute / method / wrong signature
    if re.search(
        r"AttributeError|has no attribute"
        r"|TypeError.*argument"
        r"|TypeError.*positional"
        r"|Can't instantiate abstract"
        r"|abstractmethod",
        failure_output,
    ):
        return "interface"

    # Fixture: pytest can't find a fixture
    if re.search(
        r"fixture '.*' not found"
        r"|ERRORS.*conftest"
        r"|fixture.*not found",
        failure_output,
    ):
        return "fixture"

    # Schema: Pydantic / dataclass / marshmallow validation failures
    if re.search(
        r"ValidationError|pydantic"
        r"|Field required|value is not a valid"
        r"|schema validation",
        failure_output,
        re.IGNORECASE,
    ):
        return "schema"

    # Assertion: implementation exists but returns wrong value
    if re.search(r"AssertionError|assert .* ==|assert .* is", failure_output):
        return "assertion"

    return "logic"


# Map each failure class to a short, type-specific instruction appended to the
# standard _targeted_implement instructions section.  Claude reads this last
# and it acts as a "hint" about what kind of fix is expected.
_FAILURE_CLASS_HINTS: dict[str, str] = {
    "structural": (
        "This is a STRUCTURAL failure (missing module or file).  "
        "Create the missing package __init__.py files and module skeletons first.  "
        "Do not implement business logic yet — just make the import work."
    ),
    "interface": (
        "This is an INTERFACE failure (wrong method signature, missing attribute, "
        "or unimplemented abstract method).  "
        "Check the interface definition (ABC / Protocol) and implement EXACTLY the "
        "methods it declares with the correct signatures.  "
        "Do not change the interface — only fix the concrete implementation."
    ),
    "assertion": (
        "This is an ASSERTION failure — the implementation exists and imports "
        "correctly, but it returns the WRONG VALUE.  "
        "Focus on the AssertionError line: identify actual vs expected, then "
        "fix the logic that produces the wrong value.  "
        "Do NOT rewrite imports or restructure the file."
    ),
    "fixture": (
        "This is a FIXTURE failure — a pytest fixture is missing from conftest.py.  "
        "Add the missing fixture to the appropriate conftest.py.  "
        "Do not change the test file itself."
    ),
    "schema": (
        "This is a SCHEMA / VALIDATION failure.  "
        "The data being passed does not match the Pydantic model or schema definition.  "
        "Fix the data structure, field types, or validators to match the contract.  "
        "Do not change the schema itself unless the spec requires it."
    ),
    "logic": (
        "This is a LOGIC failure — general implementation problem.  "
        "Read the test carefully to understand the exact expected behaviour, "
        "then write the minimum implementation to satisfy it."
    ),
}


def _parse_acceptance_criteria(workplan_path: Path, milestone_id: str) -> list[str]:
    """
    Extract acceptance criteria checkboxes from the workplan for a milestone.
    These are the authoritative definition of done — not Claude's interpretation.
    Returns list of criterion strings.
    """
    if not workplan_path or not workplan_path.exists():
        return []
    src = workplan_path.read_text(encoding="utf-8")
    mid_m = re.search(r"(\d+[A-Z]?)", milestone_id)
    if not mid_m:
        return []
    n = mid_m.group(1)
    section_re = re.compile(
        rf"###\s+Milestone\s+{re.escape(n)}[:\s].+?(?=\n###\s+Milestone\s+\d|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    m = section_re.search(src)
    if not m:
        return []
    criteria = []
    for line in m.group(0).splitlines():
        cb = re.match(r"\s*-\s*\[[ xX]\]\s*(.+)", line)
        if cb:
            criteria.append(cb.group(1).strip())
    return criteria


def _check_ac_quality(criteria: list[str]) -> list[str]:
    """
    Analyse acceptance criteria for signs of untestability or ambiguity.

    Untestable ACs produce S3 tests that can never pass, wasting every
    subsequent S4 run.  This gate catches the most common patterns before
    any test is written, giving the operator a chance to fix the spec first.

    Checks performed:
    - Vague outcome language: "should work", "is usable", "feels fast", etc.
    - Environment-tooling requirements: npm, docker, redis, Kafka, etc.
    - Unmeasurable comparatives: "is faster than", "scales to", "handles many"
    - Forward references: mentions of systems not yet built in this phase

    Args:
        criteria: List of acceptance criterion strings from the workplan.

    Returns:
        List of warning strings (one per problematic criterion).  Empty list
        means all criteria appear testable.

    Example:
        warnings = _check_ac_quality(criteria)
        if warnings:
            for w in warnings: print(w)
    """
    import shutil as _shutil
    warnings: list[str] = []

    _VAGUE_PATTERNS = [
        (r"\bshould work\b|\bis usable\b|\bworks correctly\b|\bfunctions properly\b",
         "vague outcome — specify a measurable assertion (return value, HTTP status, etc.)"),
        (r"\bfaster than\b|\bscales to\b|\bhandles many\b|\bhigh throughput\b|\blow latency\b",
         "unmeasurable performance claim — add specific numbers (e.g. '<100 ms', '>1000 rps')"),
        (r"\buser can\b|\boperator can\b|\badmin can\b",
         "UI/UX AC — only testable with a browser or E2E framework; consider splitting"),
    ]
    _ENV_PATTERNS = [
        (r"\bnpm\b|\bnode_modules\b|\bvite\b|\bwebpack\b",
         "requires npm/node — testable only if node_modules is installed",
         "npm"),
        (r"\bdocker\b|\bcontainer\b|\bdocker-compose\b",
         "requires Docker — testable only in a Docker-capable environment",
         "docker"),
        (r"\bredis\b",
         "requires Redis — testable only with a running Redis server",
         "redis-cli"),
        (r"\bkafka\b",
         "requires Kafka — testable only with a running Kafka broker",
         ""),
        (r"\bpostgres\b|\bpsycopg\b|\basyncpg\b",
         "requires PostgreSQL — testable only with a live database connection",
         "psql"),
    ]

    for ac in criteria:
        for pattern, msg in _VAGUE_PATTERNS:
            if re.search(pattern, ac, re.IGNORECASE):
                warnings.append(f"AC «{ac[:80]}»: {msg}")
                break  # one warning per AC

        for pattern, msg, binary in _ENV_PATTERNS:
            if re.search(pattern, ac, re.IGNORECASE):
                if not binary or not _shutil.which(binary):
                    warnings.append(f"AC «{ac[:80]}»: {msg}")
                break

    return warnings


def _check_ac_test_alignment(
    criteria: list[str],
    test_files: "list[str]",
) -> "list[str]":
    """
    Verify that each acceptance criterion is represented by at least one
    test assertion in the written test files.

    Purpose:
        S3 writes tests labelled ``test_ac1_*``, ``test_ac2_*``, etc., to
        align with acceptance criteria.  If an AC has no corresponding test
        the LLM will spend S4 trying to pass a non-existent gate.  This gate
        surfaces the gap BEFORE S4 starts so the operator can fix the tests
        or the spec rather than burning rounds.

    Strategy (deliberately lightweight to avoid false positives):
        For each AC, extract the 2–3 most distinctive non-stopword tokens.
        Search all test file source for any of those tokens appearing in a
        ``def test_`` block or an ``assert`` / ``expect`` statement.
        If none match, flag the AC as potentially unrepresented.

    Limitations:
        This is a heuristic, not a proof.  Tests may cover an AC through
        fixture setup rather than explicit assertions; such tests will be
        false-positives here and the operator can safely ignore the warning.

    Args:
        criteria:   Acceptance criterion strings from ``_extract_acceptance_criteria()``.
        test_files: Relative paths of test files written by S3 for this milestone.

    Returns:
        List of warning strings for ACs that appear to have no matching test.
        Empty list means all ACs appear to be covered.

    Example:
        warnings = _check_ac_test_alignment(criteria, ["tests/unit/test_m1.py"])
        # ["AC 3 ('returns 404 when id not found') has no matching test assertion"]
    """
    if not criteria or not test_files:
        return []

    # Aggregate all test source into one blob for fast scanning
    test_source = ""
    for tf in test_files:
        p = PROJECT_ROOT / tf
        if p.exists():
            try:
                test_source += p.read_text(encoding="utf-8") + "\n"
            except OSError:
                pass
    if not test_source:
        return []

    # Common English stopwords that carry no AC-specific signal
    _STOP = frozenset({
        "a", "an", "the", "is", "it", "in", "on", "at", "to", "of", "be",
        "are", "was", "for", "and", "or", "not", "that", "this", "with",
        "when", "if", "as", "by", "from", "has", "have", "should", "must",
        "can", "will", "returns", "return", "given", "then", "after",
    })

    def _ac_tokens(ac: str) -> list[str]:
        """Extract distinctive lowercase tokens from an AC string."""
        words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]+", ac.lower())
        # Prioritise: longer tokens, non-stopwords, snake_case identifiers
        return [w for w in words if w not in _STOP and len(w) >= 4][:5]

    warnings: list[str] = []
    for idx, ac in enumerate(criteria, 1):
        tokens = _ac_tokens(ac)
        if not tokens:
            continue   # AC too short / all stopwords — skip rather than false-positive
        # Consider the AC covered if ANY distinctive token appears near
        # a test function def or assert statement
        covered = any(
            tok in test_source
            for tok in tokens
        )
        if not covered:
            short_ac = ac if len(ac) <= 60 else ac[:57] + "..."
            warnings.append(
                f"AC {idx} ('{short_ac}') has no matching test — "
                f"searched for: {tokens}"
            )

    return warnings


def _check_milestone_complexity(
    criteria: list[str],
    workplan_section: str,
    milestone_id: str,
) -> "list[str]":
    """
    Analyse a milestone's spec for structural complexity that predicts S4
    oscillation before any tests or code are written.

    Rationale:
        The single biggest root-cause of the regression spiral is scope: a
        milestone that touches too many architectural layers in one step creates
        a blast-radius surface the LLM cannot navigate without circular dependencies.
        Catching this at S3 (before tests are written) costs nothing; catching it
        at S4 round 3 costs many tokens and operator attention.

    Checks:
        1. Too many ACs (> MAX_AC): high AC count correlates with multi-layer scope.
        2. Too many distinct architectural layers mentioned (> MAX_LAYERS):
           controller + service + repository + domain all in one milestone = trouble.
        3. Cross-cutting concerns in one step: if the spec mentions both
           "create" and "delete" (CRUD breadth) or multiple external services.
        4. Vague scope indicators: "all", "entire", "complete", "full" as
           adjectives modifying a plural noun — signs the milestone was written
           without decomposition.

    Args:
        criteria:         Acceptance criteria list.
        workplan_section: Raw text of this milestone's workplan section.
        milestone_id:     For labelling warnings.

    Returns:
        List of complexity warning strings.  Empty = within budget.

    Example:
        warnings = _check_milestone_complexity(criteria, section, "M1")
        # ["M1 has 12 ACs (threshold 8) — consider splitting into two milestones"]
    """
    warnings: list[str] = []
    text = workplan_section.lower()

    # ── Check 1: AC count ─────────────────────────────────────────────────────
    MAX_AC = 8
    if len(criteria) > MAX_AC:
        warnings.append(
            f"{milestone_id} has {len(criteria)} acceptance criteria (threshold {MAX_AC}) "
            "— consider splitting into two milestones; high AC count correlates with "
            "blast-radius oscillation in S4"
        )

    # ── Check 2: Architectural layer breadth ──────────────────────────────────
    LAYER_TERMS = {
        "controller": ["controller", "route", "endpoint", "handler", "api"],
        "service":    ["service", "use case", "usecase", "business logic", "orchestrat"],
        "repository": ["repository", "repo", "database", "db ", "persist", "store", "dao"],
        "domain":     ["domain", "model", "schema", "contract", "pydantic", "entity", "enum"],
        "infra":      ["infrastructure", "config", "logging", "telemetry", "docker", "redis"],
    }
    MAX_LAYERS = 3
    layers_touched = [
        layer for layer, terms in LAYER_TERMS.items()
        if any(term in text for term in terms)
    ]
    if len(layers_touched) > MAX_LAYERS:
        warnings.append(
            f"{milestone_id} touches {len(layers_touched)} architectural layers "
            f"({', '.join(layers_touched)}) — threshold is {MAX_LAYERS}; "
            "each additional layer multiplies blast-radius surface area"
        )

    # ── Check 3: CRUD breadth in one step ─────────────────────────────────────
    CRUD_VERBS = ["create", "read", "update", "delete", "list", "search", "filter"]
    crud_hits = [v for v in CRUD_VERBS if re.search(rf"\b{v}\b", text)]
    if len(crud_hits) >= 4:
        warnings.append(
            f"{milestone_id} covers {len(crud_hits)} CRUD operations "
            f"({', '.join(crud_hits)}) in one step — "
            "CRUD breadth usually means multiple independent service methods; "
            "consider one milestone per resource operation"
        )

    # ── Check 4: Vague scope language ─────────────────────────────────────────
    SCOPE_CREEP = re.compile(
        r"\b(all|entire|complete|full|comprehensive|everything)\s+(the\s+)?\w+s\b",
        re.IGNORECASE,
    )
    creep_matches = SCOPE_CREEP.findall(workplan_section)
    if creep_matches:
        warnings.append(
            f"{milestone_id} contains vague scope language suggesting insufficient "
            f"decomposition: {creep_matches[:3]} — "
            "replace with explicit, enumerated deliverables"
        )

    return warnings


def _criteria_to_test_plan(criteria: list[str], milestone_id: str) -> str:
    """
    Convert acceptance criteria into a structured prompt section for S3.
    Grounds Claude's test writing in the workplan, not domain guesswork.
    """
    if not criteria:
        return ""
    lines = [
        f"## Acceptance Criteria for {milestone_id} — write one test per criterion",
        "",
        "These are the ONLY things that need to be true for this milestone to be done.",
        "Write tests labelled test_ac1_..., test_ac2_... etc.",
        "Do NOT test anything not on this list.",
        "",
    ]
    for i, c in enumerate(criteria, 1):
        lines.append(f"{i}. {c}")
    return "\n".join(lines)


def _project_snapshot(relevant_namespaces: "set[str] | None" = None) -> str:
    """
    Return a compact tree of .py files in the project grouped by directory.

    relevant_namespaces — when provided (targeted per-file S4/S7 calls), only
    files under those path prefixes are included.  libs/contracts is always
    added because it is the shared contract layer depended on by everything.

    Pass None to get the full tree (whole-milestone S2, S3, S8 calls where
    Claude needs a complete picture of what already exists).

    Scoping this to the relevant namespace reduces prompt size by ~70-80% for
    a typical per-file call (from ~1,380 tokens to ~200-350 tokens) while
    keeping the exact files Claude needs to reason about.
    """
    # libs/contracts is always included — shared enums, base models, errors
    _ALWAYS_INCLUDE = {"libs/contracts"}

    roots = ["services", "libs", "tests"]
    lines = ["## Existing project files (do NOT create duplicates)\n"]
    for root in roots:
        root_path = PROJECT_ROOT / root
        if not root_path.exists():
            continue
        files = sorted(root_path.rglob("*.py"))
        if not files:
            continue

        if relevant_namespaces is not None:
            # Keep only files that fall under a relevant namespace or always-include path
            effective = relevant_namespaces | _ALWAYS_INCLUDE
            files = [
                fp for fp in files
                if any(
                    str(fp.relative_to(PROJECT_ROOT)).startswith(ns)
                    for ns in effective
                )
            ]
        if not files:
            continue

        lines.append(f"### {root}/")
        for fp in files:
            rel  = str(fp.relative_to(PROJECT_ROOT))
            size = fp.stat().st_size
            lines.append(f"  {rel}  ({size} bytes)")
        lines.append("")
    return "\n".join(lines)


def _namespaces_from_imports(test_content: str, depth: int = 2) -> set[str]:
    """
    Parse a test file's import statements and return top-level namespace paths,
    optionally following the import graph one additional hop.

    Motivation:
        A test may fail because of a transitive dependency — the test imports
        ``services.api.routes.health`` which itself imports ``libs.contracts.enums``,
        but ``enums`` is missing a required symbol.  Following one extra import
        hop surfaces the actual broken file in the context Claude receives,
        allowing it to fix the right file rather than the intermediate one.

    Args:
        test_content: Full text of the test file.
        depth:        1 = direct imports only.  2 (default) = follow imported
                      files' imports one additional level.

    Returns:
        Set of namespace path strings (e.g. ``"libs/strategy_compiler"``).

    Example:
        "from libs.strategy_compiler.interfaces import ..."
        → {"libs/strategy_compiler"}   (depth=1)
        → {"libs/strategy_compiler", "libs/contracts"}   (depth=2, if interfaces imports contracts)
    """
    import_re = re.compile(
        r"^(?:from|import)\s+((?:libs|services)\.[a-zA-Z_][a-zA-Z0-9_]*)",
        re.MULTILINE,
    )

    def _extract(content: str) -> set[str]:
        ns: set[str] = set()
        for m in import_re.finditer(content):
            parts = m.group(1).split(".")
            ns.add("/".join(parts[:2]))
        return ns

    # Level 1: direct imports from the test file
    level1 = _extract(test_content)
    if depth < 2:
        return level1

    # Level 2: follow each direct import into its source file and extract its imports
    level2: set[str] = set()
    for ns in level1:
        # Try both module.py and module/__init__.py
        for candidate in [
            PROJECT_ROOT / (ns + ".py"),
            PROJECT_ROOT / ns / "__init__.py",
        ]:
            if candidate.exists():
                try:
                    child_content = candidate.read_text(encoding="utf-8")
                    level2.update(_extract(child_content))
                except OSError:
                    pass
                break  # found one form; no need to try the other

    return level1 | level2


def _module_to_source_file(module_str: str) -> "str | None":
    """
    Resolve a dotted module path to the relative file path of the first
    matching source file that exists on disk.

    Tries from most-specific to least-specific, covering both the
    ``pkg/module.py`` and ``pkg/module/__init__.py`` forms.

    Args:
        module_str: Dotted module string, e.g. ``"libs.contracts.errors"``.

    Returns:
        Relative path string such as ``"libs/contracts/errors.py"``,
        or ``None`` if no matching file exists.

    Example:
        _module_to_source_file("libs.contracts.errors")
        # → "libs/contracts/errors.py"  (if that file exists)

        _module_to_source_file("libs.contracts")
        # → "libs/contracts/__init__.py"  (if that form exists)
    """
    parts = module_str.rstrip(".").split(".")
    for depth in range(len(parts), 0, -1):
        base = "/".join(parts[:depth])
        for suffix in (".py", "/__init__.py"):
            candidate = base + suffix
            if (PROJECT_ROOT / candidate).exists():
                return candidate
    return None


def _build_reverse_import_map() -> "dict[str, set[str]]":
    """
    Scan every ``test_*.py`` file under ``tests/`` and build:

        source_file_rel_path  →  set of test_file_rel_paths that import it

    Purpose:
        This map powers ``_blast_radius_tests()``.  Before the S4 repair
        loop asks the LLM to fix a failing test it tells the LLM which
        *other* passing tests share source-file dependencies — so the LLM
        knows what it must NOT break.

    Design choices:
        - Only DIRECT imports are mapped (depth=1).  Transitive deps are
          excluded deliberately: the blast-radius set must stay small enough
          to be useful context, not overwhelming noise.
        - Only ``libs.*`` and ``services.*`` modules are tracked; third-party
          and stdlib imports are irrelevant to the agent's blast radius.
        - Built fresh once per outer S4 iteration so newly written files are
          visible (a prior round may have created a source file this test now
          imports).

    Returns:
        Dict mapping each source file to the set of test files that import it.
        Empty dict if ``tests/`` does not exist.

    Example:
        {
          "libs/contracts/errors.py": {
              "tests/unit/test_errors.py",
              "tests/unit/test_service.py",
          },
          ...
        }
    """
    reverse: dict[str, set[str]] = {}
    import_re = re.compile(
        r"^(?:from|import)\s+((?:libs|services)\.[a-zA-Z_.]+)",
        re.MULTILINE,
    )
    test_root = PROJECT_ROOT / "tests"
    if not test_root.exists():
        return reverse

    for test_path in test_root.rglob("test_*.py"):
        test_rel = str(test_path.relative_to(PROJECT_ROOT))
        try:
            content = test_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in import_re.finditer(content):
            src = _module_to_source_file(m.group(1))
            if src:
                reverse.setdefault(src, set()).add(test_rel)

    return reverse


def _blast_radius_tests(
    test_file: str,
    passing_tests: "set[str]",
    reverse_map: "dict[str, set[str]]",
) -> "list[str]":
    """
    Return passing tests that share at least one direct source-file
    dependency with ``test_file``.

    These tests are the "blast radius" of any write the agent makes to
    fix ``test_file``.  Passing them to ``_targeted_implement`` tells the
    LLM what it must not inadvertently break.

    Args:
        test_file:     Relative path of the failing test being repaired.
        passing_tests: Set of test files currently passing (env-skips excluded).
        reverse_map:   Reverse import map from ``_build_reverse_import_map()``.

    Returns:
        Sorted list of at-risk passing test relative paths, capped at 12
        to avoid overwhelming the LLM prompt.  May be empty.

    Raises:
        Nothing — OSError on unreadable test_file silently returns [].

    Example:
        # test_foo.py imports libs/contracts/errors.py
        # test_bar.py also imports libs/contracts/errors.py and is passing
        _blast_radius_tests("tests/unit/test_foo.py", passing, reverse_map)
        # → ["tests/unit/test_bar.py"]
    """
    import_re = re.compile(
        r"^(?:from|import)\s+((?:libs|services)\.[a-zA-Z_.]+)",
        re.MULTILINE,
    )
    try:
        content = (PROJECT_ROOT / test_file).read_text(encoding="utf-8")
    except OSError:
        return []

    at_risk: set[str] = set()
    for m in import_re.finditer(content):
        src = _module_to_source_file(m.group(1))
        if src and src in reverse_map:
            at_risk.update(reverse_map[src] & passing_tests)

    at_risk.discard(test_file)          # never flag the test being fixed
    return sorted(at_risk)[:12]         # cap: enough signal, not overwhelming


def _compute_repair_surface(
    test_content: str,
    failure_output: str,
) -> "list[str]":
    """
    Derive the minimum set of source files the agent should need to write
    in order to fix a specific failing test.

    The repair surface is the union of three independent signals:

    1. **Missing imports** — modules that the test file imports but whose
       corresponding source file does not yet exist on disk.  The agent
       *must* create these.

    2. **Traceback files** — project source files named in the pytest
       traceback.  These are the files where the failure actually occurred
       and are the most likely candidates for correction.

    3. **ModuleNotFoundError targets** — explicit ``No module named 'X'``
       errors in the failure output, converted to likely file paths.

    Purpose:
        Presented to the LLM as an explicit allowlist, the repair surface
        makes the minimal change visible *before* the agent decides what to
        write.  Files outside the surface can still be written — this is a
        WARNING constraint, not a hard block — but the agent is asked to
        justify any out-of-surface write with a ``# REPAIR-SURFACE: ...``
        comment.  This makes blast-radius violations deliberate and traceable
        rather than accidental.

    Does NOT:
        - Follow transitive imports (depth=1 only — deeper traversal risks
          surfacing the entire codebase).
        - Include test files (the test itself is never part of the repair
          surface — only source files are).
        - Include stdlib or venv files named in the traceback.

    Args:
        test_content:   Full text of the failing test file.
        failure_output: Combined pytest stdout+stderr for this test.

    Returns:
        Sorted list of relative source file paths (may include paths that
        don't yet exist — those are files the agent needs to create).
        Capped at 15 to keep the prompt section bounded.

    Example:
        _compute_repair_surface(
            test_content,
            "ModuleNotFoundError: No module named 'libs.contracts.errors'"
        )
        # → ["libs/contracts/errors.py"]   (doesn't exist yet → must create)
    """
    surface: set[str] = set()
    import_re = re.compile(
        r"^(?:from|import)\s+((?:libs|services)\.[a-zA-Z_.]+)",
        re.MULTILINE,
    )

    # ── Signal 1: direct imports that don't exist on disk ────────────────────
    for m in import_re.finditer(test_content):
        src = _module_to_source_file(m.group(1))
        if src is None:
            # Doesn't exist → derive the most likely target path
            parts = m.group(1).rstrip(".").split(".")
            # Prefer package/__init__.py for multi-part modules, else module.py
            if len(parts) >= 3:
                surface.add("/".join(parts) + ".py")
                surface.add("/".join(parts[:-1]) + "/__init__.py")
            else:
                surface.add("/".join(parts) + ".py")

    # ── Signal 2: project source files named in the failure traceback ────────
    traceback_file_re = re.compile(r'File "([^"]+\.py)"', re.MULTILINE)
    for m in traceback_file_re.finditer(failure_output):
        raw = m.group(1)
        try:
            rel = str(Path(raw).relative_to(PROJECT_ROOT))
        except ValueError:
            # Absolute path outside project root — skip
            continue
        # Exclude test files, venv, and __pycache__
        if (
            rel.startswith(("libs/", "services/"))
            and "__pycache__" not in rel
            and ".venv" not in rel
        ):
            surface.add(rel)

    # ── Signal 3: explicit ModuleNotFoundError messages ──────────────────────
    module_err_re = re.compile(
        r"No module named '((?:libs|services)[^']+)'",
        re.MULTILINE,
    )
    for m in module_err_re.finditer(failure_output):
        module_str = m.group(1).strip("'")
        src = _module_to_source_file(module_str)
        if src:
            surface.add(src)
        else:
            parts = module_str.split(".")
            surface.add("/".join(parts) + ".py")

    # ── Signal 4: AttributeError / ImportError on specific names ─────────────
    # "cannot import name 'Foo' from 'libs.contracts.errors'" → that file
    import_name_re = re.compile(
        r"cannot import name '[^']+' from '((?:libs|services)[^']+)'",
        re.MULTILINE,
    )
    for m in import_name_re.finditer(failure_output):
        src = _module_to_source_file(m.group(1))
        if src:
            surface.add(src)

    return sorted(surface)[:15]         # cap: bounded, still comprehensive


def _failing_modules_from_cases(
    failure_cases: list[dict],
    test_content: str,
) -> set[str]:
    """
    Extract the specific module paths that appear in the failure output so
    that _read_existing_implementations_scoped can load only the relevant files.

    For example, if a failure mentions 'libs/strategy_compiler/interfaces/__init__.py'
    or 'libs.strategy_compiler', that module is returned.  Falls back to all
    top-level imports in the test if no specific failing module can be identified.
    """
    modules: set[str] = set()

    # Look for module paths in the error messages themselves
    module_re = re.compile(r"((?:libs|services)/[a-zA-Z_][a-zA-Z0-9_/]*\.py)")
    dotted_re = re.compile(r"((?:libs|services)\.[a-zA-Z_][a-zA-Z0-9_.]*)")
    for case in failure_cases:
        for hit in module_re.findall(case.get("error", "") + case.get("location", "")):
            modules.add(hit)
        for hit in dotted_re.findall(case.get("error", "")):
            # "libs.strategy_compiler.interfaces" → "libs/strategy_compiler"
            parts = hit.split(".")
            modules.add("/".join(parts[:2]))

    # Fallback: use all top-level imports in the test file
    if not modules:
        import_re = re.compile(
            r"^(?:from|import)\s+((?:libs|services)\.[a-zA-Z_][a-zA-Z0-9_.]*)",
            re.MULTILINE,
        )
        for m in import_re.finditer(test_content):
            parts = m.group(1).split(".")
            modules.add("/".join(parts[:2]))
    return modules


def _read_existing_implementations_scoped(
    relevant_module_paths: "set[str]",
) -> dict[str, str]:
    """
    Read existing implementation files scoped to the given module paths.

    Only reads files that fall under one of the provided top-level module
    paths (e.g. 'libs/strategy_compiler', 'services/api').  This avoids
    loading large files from unrelated parts of the codebase that would
    consume context-window budget without helping Claude fix the specific
    failing test.

    Limits each file to 100 lines to stay within token budget.
    """
    found: dict[str, str] = {}
    for mod_path in relevant_module_paths:
        target = PROJECT_ROOT / mod_path
        # Direct file path (e.g. libs/strategy_compiler.py)
        as_file = target.with_suffix(".py")
        # Package path (e.g. libs/strategy_compiler/__init__.py)
        as_pkg = target / "__init__.py"

        for candidate in [as_file, as_pkg]:
            if candidate.exists():
                lines = candidate.read_text(encoding="utf-8").splitlines()
                preview = "\n".join(lines[:100])
                if len(lines) > 100:
                    preview += f"\n# ... ({len(lines) - 100} more lines)"
                rel = str(candidate.relative_to(PROJECT_ROOT))
                found[rel] = preview

        # Also include immediate children of the package directory
        if target.is_dir():
            for child in sorted(target.glob("*.py")):
                if child.name == "__init__.py":
                    continue   # already included above
                rel = str(child.relative_to(PROJECT_ROOT))
                if rel not in found:
                    lines = child.read_text(encoding="utf-8").splitlines()
                    preview = "\n".join(lines[:100])
                    if len(lines) > 100:
                        preview += f"\n# ... ({len(lines) - 100} more lines)"
                    found[rel] = preview
    return found


def _extract_shared_missing_modules(
    failing_files: list[str],
    full_output: str,
) -> set[str]:
    """
    Identify test files that share a common missing-module root cause.

    When multiple tests fail because of the same ``ModuleNotFoundError`` or
    ``ImportError``, fixing that missing module once is more efficient than
    making N separate LLM calls that each independently try to create the
    same file.

    This function returns the set of failing test file paths whose failure
    output contains the same missing module name as at least one other failing
    test.  An empty set (or a set of size ≤ 1) means no shared root cause was
    detected and per-file calls are appropriate.

    Args:
        failing_files: List of test file relative paths that are currently failing.
        full_output:   Full pytest output from the most recent full-suite run.

    Returns:
        Set of test file paths that share a common missing module.

    Example:
        shared = _extract_shared_missing_modules(failing, output)
        if len(shared) > 1:
            # Make one batch call to fix the common root cause
    """
    # Extract "No module named 'X'" strings from the full output
    missing_re = re.compile(r"No module named '([^']+)'")
    all_missing = missing_re.findall(full_output)
    if not all_missing:
        return set()

    # Count which missing module names appear most often
    from collections import Counter
    counts = Counter(all_missing)
    # A "shared" root cause is one that affects more than one test (appears ≥2 times)
    shared_modules = {mod for mod, cnt in counts.items() if cnt >= 2}
    if not shared_modules:
        return set()

    # Return only the failing test files that actually reference the shared module
    affected: set[str] = set()
    for tf in failing_files:
        content = _load_test_file(tf)
        if any(mod.split(".")[0] in content or mod in content for mod in shared_modules):
            affected.add(tf)
    return affected


def _build_log_excerpt_for_file(
    build_log_path: Path,
    test_file: str,
    max_chars: int = 1500,
) -> str:
    """
    Scan the build log markdown file and return the most recent excerpt
    that is relevant to the given test file.

    Purpose:
        When a targeted_implement call fails and we enter a retry loop, the
        retry call needs to know what was already attempted and what error
        remained.  The build log contains the raw pytest output from prior
        attempts logged by the outer build loop.  Extracting just the
        sections that mention the failing test file gives the retry call
        a ~1 500-char high-signal context block instead of dumping the
        entire (potentially multi-MB) log into the prompt.

    Responsibilities:
        - Read the build log if it exists (return "" if missing).
        - Split on markdown headings / horizontal rules that the logger
          writes between attempt blocks.
        - Find the last section that contains any mention of test_file
          (basename match is enough — full path may vary).
        - Return up to max_chars of that section, trimming from the front
          so the most recent failure lines are always included.

    Does NOT:
        - Parse or interpret pytest output.
        - Raise exceptions on missing file (silent empty return).

    Args:
        build_log_path: Absolute Path to the .build-log.md file.
        test_file:      Relative path of the failing test file
                        (e.g. "tests/unit/test_foo.py").
        max_chars:      Maximum characters to return (default 1500).

    Returns:
        A string excerpt (possibly empty) from the build log.

    Example:
        excerpt = _build_log_excerpt_for_file(
            build_log_path=Path("docs/workplan-tracking/foo.build-log.md"),
            test_file="tests/unit/test_bar.py",
            max_chars=1500,
        )
        # excerpt contains the last pytest run mentioning test_bar.py
    """
    if not build_log_path or not build_log_path.exists():
        return ""

    raw = build_log_path.read_text(encoding="utf-8")
    if not raw.strip():
        return ""

    # The build logger separates attempt blocks with "---" horizontal rules
    # or "##" / "###" headings.  Split on these boundaries so we can find
    # the most recent block that mentions the failing test file.
    section_re = re.compile(r"(?:^|\n)(?:---+|#{1,3} )", re.MULTILINE)
    sections = section_re.split(raw)

    # Work backwards: find the last section containing the test file name
    basename = Path(test_file).name  # e.g. "test_foo.py"
    relevant_section = ""
    for section in reversed(sections):
        if basename in section or test_file in section:
            relevant_section = section
            break

    if not relevant_section:
        # Fallback: last max_chars of the entire log (better than nothing)
        return raw[-max_chars:] if len(raw) > max_chars else raw

    # Trim from the front to stay within max_chars, keeping the tail
    # (most recent failure lines are at the end of the section)
    if len(relevant_section) > max_chars:
        relevant_section = "...\n" + relevant_section[-max_chars:]

    return relevant_section.strip()


# ---------------------------------------------------------------------------
# Environment capability detection
# Some tests require tooling (npm/node, Docker, Redis …) that may not be
# present in the current execution environment.  Calling the LLM to "fix"
# these tests is futile — the fix is installing the tool, not editing Python.
# _detect_missing_env_caps() scans a test file and returns a human-readable
# list of missing capabilities.  An empty list means the test is runnable.
# ---------------------------------------------------------------------------

# Capability entries: (scan_pattern, tool_binary, human_label)
# scan_pattern  — regex searched in the test source
def _detect_missing_env_caps(test_content: str) -> list[str]:
    """
    Scan a test file's source for environment requirements that the current
    execution environment cannot satisfy.

    Returns a list of human-readable capability descriptions that are missing.
    An empty list means the test can be attempted.

    Capabilities checked:
    - npm run build / yarn build → requires npm binary AND node_modules installed
    - docker → probed via shutil.which('docker')
    - redis → probed via shutil.which('redis-cli')

    Note: npm binary presence alone is not sufficient — node_modules must be
    installed (i.e. ``npm install`` has been run) for ``npm run build`` to work.

    Args:
        test_content: Full text of the test file.

    Returns:
        List of missing capability descriptions; empty if all satisfied.

    Example:
        caps = _detect_missing_env_caps(test_src)
        if caps:
            print("Cannot run — missing:", caps)
    """
    import shutil as _shutil
    missing: list[str] = []

    # npm run build / yarn build — requires BOTH the binary AND node_modules.
    # The npm binary may be installed system-wide but npm install hasn't been run,
    # making `npm run build` fail regardless of binary presence.
    # Pattern covers both shell-style "npm run build" and list-style ["npm", "run", ...]
    if re.search(r"\bnpm\b|\byarn\b|\bvite\b|\bwebpack\b|\bnext\b",
                 test_content, re.IGNORECASE):
        npm_ok = bool(_shutil.which("npm") or _shutil.which("yarn"))
        node_modules_ok = (PROJECT_ROOT / "node_modules").is_dir()
        if not npm_ok:
            missing.append("npm/node (frontend toolchain binary not installed)")
        elif not node_modules_ok:
            missing.append(
                "npm build environment (node_modules not installed — "
                "run 'npm install' in the project root first)"
            )

    # Docker
    if re.search(r"\bdocker\b(?!\s*import)", test_content, re.IGNORECASE):
        if not _shutil.which("docker"):
            missing.append("docker (container runtime not available)")

    # Redis
    if re.search(r"\bredis\b", test_content, re.IGNORECASE):
        if not _shutil.which("redis-cli"):
            missing.append("redis (Redis server / CLI not available)")

    return missing


def _targeted_implement(
    test_file: str,
    test_content: str,
    failure_output: str,
    milestone_id: str,
    distilled_ctx: str,
    wname: str,
    system_prompt: str,
    existing_paths: "set[str] | None" = None,
    prior_attempt_context: str = "",
    at_risk_tests: "list[str] | None" = None,
    repair_surface: "list[str] | None" = None,
) -> tuple[list[str], str]:
    """
    Build a lean, targeted RAG prompt and call Claude to fix a specific
    failing test file.

    Prompt sections (in order, smallest useful footprint):
      0. Scoped file inventory  — only files in the test's namespaces
      1. Intent                 — milestone + imports that must exist
      2. Contract               — test file content (capped 3000 chars)
      3. Prior attempt context  — what was tried last time (retry only)
      4. Existing implementations — current content of relevant impl files
      5. Failures to fix        — structured cases + raw pytest output
      6. Spec context           — distilled milestone context (capped 1500 chars)
      7. Blast-radius guard     — passing tests sharing dependencies (must not break)
      7b. Repair surface        — minimum files agent should write (allowlist)
      8. Instructions

    Parameters
    ----------
    prior_attempt_context:
        On retry calls, pass the build-log excerpt for this test file from the
        previous attempt.  This tells Claude exactly what it already tried and
        what still failed, making corrections far more targeted than a cold call.
        Leave empty on the first attempt.

    at_risk_tests:
        Passing tests that share at least one direct source-file dependency with
        ``test_file``.  Computed by ``_blast_radius_tests()``.  When provided,
        they are injected into the prompt as an explicit "must not break"
        constraint immediately before the Instructions section — the primary
        meta-architectural defence against the oscillation pattern where fixing
        one test inadvertently breaks another that imports the same module.
        Pass None (default) to omit the section (e.g. for batch root-cause calls).

    repair_surface:
        Minimum set of source files the agent should need to write, derived from
        the test's import graph and the failure traceback by
        ``_compute_repair_surface()``.  Injected as a named allowlist in the
        prompt so the LLM knows upfront what the minimal change looks like.
        Files outside the list can still be written but must be justified with
        a ``# REPAIR-SURFACE: ...`` comment.  This makes blast-radius
        violations deliberate and traceable rather than accidental.
        Pass None (default) to omit — safe for batch root-cause calls where
        the surface is deliberately broad.

    Note: `spec_section` (the raw workplan text) was removed from this function.
    The distilled context already contains a compressed version of the milestone
    spec.  Passing both was redundant and wasted ~500 tokens per call.
    """
    # Apply any known deterministic fixes before calling Claude
    known_written = _apply_known_fixes(failure_output, wname)
    if known_written:
        still_failing, failure_output = _run_specific_tests(test_file)
        if not still_failing:
            return known_written, ""  # fixed without an LLM call

    # Parse failures into structured cases (error type + location)
    failure_cases = _parse_failure_cases(failure_output, test_file)

    # Extract imports from the test — defines the exact contract
    imports = [
        line for line in test_content.splitlines()
        if line.startswith(("import ", "from ")) and ("libs." in line or "services." in line)
    ]

    # Derive relevant namespaces from those imports for the scoped snapshot
    relevant_namespaces = _namespaces_from_imports(test_content)

    # Read existing implementations scoped to failing modules only
    # (files that are in the namespace of the test's actual failures)
    failing_modules = _failing_modules_from_cases(failure_cases, test_content)
    existing_impl = _read_existing_implementations_scoped(failing_modules)

    # ── Build structured prompt ───────────────────────────────────────────────

    # Section 0: Scoped file inventory — only namespaces this test touches
    snapshot = _project_snapshot(relevant_namespaces)
    file_inventory = (
        f"{snapshot}\n"
        f"{_CANONICAL_PATHS}\n"
        f"**RULES:** Write to existing files to correct them. "
        f"Never invent a duplicate of a canonical file.\n\n"
    )

    # Section 1: Intent — what module this call is responsible for
    intent = (
        f"## What we are building\n\n"
        f"Milestone: {milestone_id}\n"
        f"Test file: {test_file}\n\n"
        f"The test file requires these modules to exist:\n"
        + "\n".join(f"  {imp}" for imp in imports)
        + "\n"
    )

    # Section 2: The contract — the test itself (source of truth)
    contract = (
        f"\n## The Contract (test file)\n\n"
        f"```python\n{test_content[:3000]}\n"
        + ("# ... (truncated)\n" if len(test_content) > 3000 else "")
        + "```\n"
    )

    # Section 3: Prior attempt context (retry only)
    # When provided, this is the highest-signal RAG input available: it
    # describes exactly what was tried and what still failed, letting Claude
    # make a surgical correction rather than re-deriving from scratch.
    prior_section = (
        f"\n## What was tried previously (do not repeat these mistakes)\n\n"
        f"{prior_attempt_context[:2000]}\n"
        if prior_attempt_context else ""
    )

    # Section 4: What was already written (correct, don't rewrite from scratch)
    if existing_impl:
        impl_section = "\n## What was already written (correct or extend these)\n\n"
        for path, content in existing_impl.items():
            impl_section += f"### {path}\n```python\n{content}\n```\n\n"
    else:
        impl_section = ""

    # Section 5: Structured failure report
    if failure_cases:
        failure_section = "\n## Failures to fix\n\n"
        for case in failure_cases[:10]:
            failure_section += (
                f"**{case['test']}**\n"
                f"  Error: {case['error']}\n"
                + (f"  At: {case['location']}\n" if case['location'] else "")
                + "\n"
            )
        failure_section += (
            f"<details>\n<summary>Full pytest output</summary>\n\n"
            f"```\n{failure_output[:2000]}\n```\n</details>\n"
        )
    else:
        failure_section = (
            f"\n## Error (collection failure)\n\n"
            f"```\n{failure_output[:2000]}\n```\n"
        )

    # Section 6: Distilled spec context (condensed milestone intent, capped)
    spec_context = (
        f"\n## Spec context for {milestone_id}\n\n{distilled_ctx[:1500]}\n"
        if distilled_ctx else ""
    )

    # Section 7: Blast-radius guard — passing tests that share source dependencies.
    #
    # Root cause of the S4 oscillation pattern: the agent fixes test A by modifying
    # a shared module, which inadvertently breaks test B.  Test B then becomes the
    # next failing file, and its fix breaks test A again — a cycle with no convergence.
    #
    # The meta-fix is to make the shared-dependency relationship EXPLICIT in the
    # prompt so the LLM knows the full constraint surface before choosing an approach.
    # If it cannot fix the failing test without touching a shared module, it should
    # prefer a narrower change (new method, subclass, new private file) rather than
    # modifying the shared contract.
    blast_section = ""
    if at_risk_tests:
        names = [Path(t).name for t in at_risk_tests]
        blast_section = (
            f"\n## Tests you MUST NOT break (shared dependency blast radius)\n\n"
            f"The following {len(at_risk_tests)} passing test(s) import at least one "
            f"of the same source files you are about to modify.  If your fix changes "
            f"a shared module's interface or behaviour, these tests WILL fail — "
            f"creating the oscillation the build loop is trying to avoid.\n\n"
            + "".join(f"  - `{n}`\n" for n in names)
            + "\n**Strategy when shared modules are involved:**\n"
            "- Prefer adding a new method / subclass / private helper over changing "
            "an existing public interface.\n"
            "- If you must change a shared module, verify that your change is "
            "backward-compatible with the imports above.\n"
            "- If backward compatibility is impossible, surface this in a code "
            "comment (`# BLAST-RADIUS: ...`) so the operator can review.\n"
        )

    # Section 7b: Repair surface — the minimum files the agent should need to touch.
    #
    # This is the allowlist complement to the blast-radius deny-list.  The blast-radius
    # section tells the LLM what it must NOT break; the repair surface tells it what
    # it SHOULD write.  Together they bracket the acceptable change surface:
    #   • Below the floor (repair surface) → probably missing something
    #   • Above the ceiling (blast radius)  → probably going to regress something
    #
    # Files outside the surface can still be written — this is advisory, not enforced
    # at the prompt level (enforcement happens via _run_blast_radius_check at write
    # time).  Requiring a # REPAIR-SURFACE: comment makes deviations traceable.
    repair_surface_section = ""
    if repair_surface:
        repair_surface_section = (
            f"\n## Minimum repair surface (files derived from imports + traceback)\n\n"
            f"Based on this test's import graph and the failure traceback, the agent "
            f"should only need to write or modify these {len(repair_surface)} file(s):\n\n"
            + "".join(f"  - `{f}`\n" for f in repair_surface)
            + "\n**If you write a file NOT in this list**, add a one-line comment "
            "explaining why: `# REPAIR-SURFACE: also modifying X because <reason>`. "
            "Unexplained out-of-surface writes are the primary source of "
            "blast-radius regressions.\n"
        )

    # Section 8: Instructions — include a type-specific hint based on failure class.
    # Classifying the failure before the LLM call tells Claude what KIND of problem
    # it is solving, so it can apply the right remediation strategy immediately
    # rather than having to re-derive it from the error text.
    failure_class  = _classify_failure(failure_output)
    class_hint     = _FAILURE_CLASS_HINTS.get(failure_class, "")
    instructions = (
        f"\n## Instructions\n\n"
        f"**Failure class: `{failure_class}`** — {class_hint}\n\n"
        f"Fix the failures above.\n"
        f"- If implementation files already exist (Section 4), correct them — do not rewrite from scratch.\n"
        f"- If they don't exist, create them.\n"
        f"- Write ONLY files needed for {Path(test_file).name}. Nothing else.\n"
        f"- Use <<<FILE: path>>> ... <<<END_FILE>>> for every file.\n"
        f"- Minimal code only — make the failing tests pass, nothing more.\n"
    )

    user_content = (
        file_inventory + intent + contract + prior_section
        + impl_section + failure_section + spec_context
        + repair_surface_section + blast_section + instructions
    )

    # Trim prompt if over ~50k tokens — preserve failures + blast section, trim impl
    if len(user_content) // 4 > 50_000 and existing_impl:
        slim_impl = "\n## What was already written (trimmed)\n\n"
        for p, c in existing_impl.items():
            lines = c.splitlines()
            slim_impl += f"### {p}\n```python\n{chr(10).join(lines[:50])}\n# ...\n```\n\n"
        user_content = (
            file_inventory + intent + contract + prior_section
            + slim_impl + failure_section + spec_context
            + repair_surface_section + blast_section + instructions
        )

    try:
        with Spinner(f"Fixing {Path(test_file).name}"):
            response = call_claude(
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                max_tokens=8192,
            )
    except RuntimeError as exc:
        _err(f"API call failed for {test_file}: {exc}")
        return [], ""

    # Write files — validate paths, merge conftest, enforce protected-file guard
    file_blocks = _extract_files(response)
    written = []
    seen = existing_paths or set()
    if file_blocks:
        for rel_path, content in file_blocks:
            rel_path, content, warn = _validate_and_redirect(rel_path, content)
            if warn:
                _warn(f"  {warn}")
            if rel_path is None:        # protected — skip entirely
                continue
            dest = PROJECT_ROOT / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            _journal_write(rel_path, content, wname)
            dest.write_text(content, encoding="utf-8")
            written.append(rel_path)
    else:
        _warn(f"  No files written for {test_file} — Claude may have hit output limit")

    return written, response


# Canonical project paths — injected into every implementation prompt
_CANONICAL_PATHS = """
Canonical entry points (NEVER rename or duplicate):
  services/api/main.py                  FastAPI app object
  services/api/routes/<name>.py         one route file per resource
  services/<svc>/main.py                entry point for every non-API service
  libs/contracts/enums.py               all project enums live here
  libs/contracts/base.py                APIResponse, FXLabBaseModel
  libs/contracts/errors.py              all typed exceptions
  tests/conftest.py                     root shared fixtures
  tests/unit/conftest.py                unit fixtures (merge — never overwrite)
  tests/integration/conftest.py         integration fixtures (merge — never overwrite)

Standard library skeleton — create ALL of these when you add a new lib:
  libs/<name>/__init__.py               package root (required for importability)
  libs/<name>/interfaces/__init__.py    abstract ports (ABC / Protocol only)
  libs/<name>/mocks/__init__.py         in-memory fakes used only in unit tests

NEVER write to these paths (they are managed by build.py, not by agent steps):
  docs/workplan-tracking/.active_workplan
  docs/workplan-tracking/*.progress
  docs/workplan-tracking/*.distilled.md
  CLAUDE.md
  pyproject.toml / requirements*.txt
  docker-compose.yml
  infra/**
"""

# Canonical file rules: if Claude writes to an alias path, redirect it.
_CANONICAL_REDIRECTS: dict[str, str] = {
    "services/api/app.py":          "services/api/main.py",
    "services/api/application.py":  "services/api/main.py",
    "services/app.py":              "services/api/main.py",
    "app.py":                       "services/api/main.py",
    "main.py":                      "services/api/main.py",
    "libs/contracts/models.py":     "libs/contracts/base.py",
    "libs/contracts/schemas.py":    "libs/contracts/base.py",
    "libs/contracts/exceptions.py": "libs/contracts/errors.py",
    "libs/contracts/enumerations.py": "libs/contracts/enums.py",
}

# Directories where conftest.py must be merged, never overwritten
_CONFTEST_MERGE_DIRS = {"tests", "tests/unit", "tests/integration", "tests/acceptance"}

# ---------------------------------------------------------------------------
# Protected paths — the agent is NEVER permitted to write to these.
# These are infrastructure / tracking state managed by build.py itself, not
# by the Claude implementation agent.  Any attempt to write them is silently
# blocked and a warning is logged.  Add new entries here whenever a file is
# added to the repo that must remain under human / build.py control.
# ---------------------------------------------------------------------------
_PROTECTED_PATHS: frozenset[str] = frozenset({
    "docs/workplan-tracking/.active_workplan",   # runtime selection state
    "CLAUDE.md",                                  # prime directive
    "docker-compose.yml",                         # infrastructure definition
    "pyproject.toml",                             # dependency manifest
    "requirements.txt",                           # pinned prod deps
    "requirements-dev.txt",                       # pinned dev deps
    ".env",                                       # secrets — never agent-written
    ".gitignore",
})

# Accumulator files — shared across milestones.  Multiple agents contribute
# symbols to these files over the life of the project.  They may NEVER be
# wholesale-overwritten; agent writes are merged at the AST symbol level so
# that each milestone's additions are preserved.
#
# When an agent writes one of these paths, _validate_and_redirect applies
# _accumulator_merge() instead of replacing the existing content.
_ACCUMULATOR_FILES: frozenset[str] = frozenset({
    "libs/contracts/enums.py",      # all project enums accumulate here
    "libs/contracts/base.py",       # base models accumulate here
    "libs/contracts/errors.py",     # typed exceptions accumulate here
    "services/api/main.py",         # route registrations accumulate here
})

# Any file whose relative path starts with one of these prefixes is also
# protected regardless of the exact filename.
_PROTECTED_PREFIXES: tuple[str, ...] = (
    "docs/workplan-tracking/",   # all tracking files: .progress, .distilled.md, etc.
    "infra/",                    # docker/compose/migration config is human-owned
    ".github/",                  # CI workflows are human-owned
)


def _is_agent_writable(rel_path: str) -> tuple[bool, str]:
    """
    Return (True, "") if the agent is allowed to write rel_path.
    Return (False, reason) if the path is protected.

    Normalises the path to forward slashes before checking so that Windows
    paths and paths with leading './' are handled correctly.
    """
    norm = rel_path.replace("\\", "/").lstrip("./")
    if norm in _PROTECTED_PATHS:
        return False, (
            f"BLOCKED — '{norm}' is a protected infrastructure file managed by "
            "build.py.  Do not write this file from an agent step.  "
            "Use [w] to update the workplan selection."
        )
    for prefix in _PROTECTED_PREFIXES:
        if norm.startswith(prefix):
            return False, (
                f"BLOCKED — '{norm}' is inside protected directory '{prefix}'.  "
                "Tracking and infrastructure files are managed by build.py, not by agent steps."
            )
    return True, ""


def _validate_and_redirect(rel_path: str, content: str) -> tuple[str | None, str, str | None]:
    """
    Check a file path against canonical rules before writing.
    Returns (final_path, final_content, warning_message | None).

    A None final_path means the write must be skipped entirely (protected file).

    Rules:
    0. If the path is in _PROTECTED_PATHS or under a _PROTECTED_PREFIXES
       directory, block the write and return (None, "", warning).
    1. If the path is a known alias, redirect to the canonical path and
       merge content if the canonical file already exists.
    2. If the path is conftest.py in a known test dir, always merge.
    """
    warning = None

    # Rule 0: protected-file guard — must run before anything else
    writable, block_reason = _is_agent_writable(rel_path)
    if not writable:
        return None, "", block_reason

    # Rule 1: canonical redirects
    canonical = _CANONICAL_REDIRECTS.get(rel_path)
    if canonical:
        warning = f"Redirected {rel_path} → {canonical} (canonical path rule)"
        dest = PROJECT_ROOT / canonical
        if dest.exists():
            # Merge: append new content that isn't already present
            existing = dest.read_text(encoding="utf-8")
            # Simple merge: add lines from new content not in existing
            new_lines = [l for l in content.splitlines()
                         if l.strip() and l not in existing]
            if new_lines:
                content = existing.rstrip() + "\n\n# -- merged from " + rel_path + " --\n"
                content += "\n".join(new_lines) + "\n"
            else:
                content = existing  # nothing new to add
        # Archive the source file if it still exists on disk so it can never
        # persist and confuse the codebase (e.g. app.py must not exist alongside main.py).
        # Files are moved to _archived/ — never deleted — so history is preserved.
        src_on_disk = PROJECT_ROOT / rel_path
        if src_on_disk.exists() and src_on_disk != (PROJECT_ROOT / canonical):
            archive_dir = PROJECT_ROOT / "_archived"
            archive_dir.mkdir(exist_ok=True)
            # Mangle the filename so it is clearly not a live source file
            archive_name = rel_path.replace("/", "_") + ".bak"
            archive_dest = archive_dir / archive_name
            src_on_disk.rename(archive_dest)
            warning += f"; archived {rel_path} → _archived/{archive_name}"
        rel_path = canonical

    # Rule 2: conftest.py in known dirs always merges
    path_obj = Path(rel_path)
    if path_obj.name == "conftest.py":
        dir_str = str(path_obj.parent)
        if dir_str in _CONFTEST_MERGE_DIRS or dir_str == ".":
            dest = PROJECT_ROOT / rel_path
            if dest.exists():
                merged = _merge_conftest(dest.read_text(encoding="utf-8"), content)
                if merged:
                    content = merged
                    warning = (warning or "") + f" conftest merged"
                else:
                    content = dest.read_text(encoding="utf-8")  # nothing to add

    # Rule 3: accumulator files — AST-level symbol merge, never wholesale overwrite.
    # These files are contributed to by multiple milestone agents over the project
    # lifetime.  A wholesale replacement would silently destroy symbols added by
    # earlier milestones.  Instead, only NEW or UPDATED symbols (classes, functions,
    # top-level assignments) are merged in.  Existing symbols never deleted.
    norm_path = rel_path.replace("\\", "/").lstrip("./")
    if norm_path in _ACCUMULATOR_FILES:
        dest = PROJECT_ROOT / norm_path
        if dest.exists():
            existing = dest.read_text(encoding="utf-8")
            merged = _accumulator_merge(existing, content, source_hint=norm_path)
            if merged != existing:
                content = merged
                # Fix 5: info-level (dim dot) — not a warning, just a merge note
                _info(f"accumulator merge: symbols updated/added in {norm_path}")
            else:
                # Fix 4: no new symbols — skip the write entirely so the journal
                # isn't polluted with no-op entries (one of the root causes of the
                # 115-file write count seen in the S4 build log analysis).
                # Fix 5: info-level (dim dot) — definitely not a warning
                _info(f"accumulator: no new symbols in {norm_path} — write skipped")
                return None, "", warning
        # Normalise rel_path to canonical form so it always lands in the right place
        rel_path = norm_path

    return rel_path, content, warning





def _journal_write(rel_path: str, content: str, wname: str) -> None:
    """Log every file write so [rw] can revert the last run."""
    import json, hashlib
    journal = TRACKING_DIR / f"{wname}.write-journal.jsonl"
    dest    = PROJECT_ROOT / rel_path
    prev    = dest.read_text(encoding="utf-8") if dest.exists() else ""
    record  = {
        "ts":   datetime.now(timezone.utc).isoformat(),
        "path": rel_path,
        "prev": prev,
    }
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _write_golden_baseline(wname: str, milestone_id: str, full_output: str) -> None:
    """
    Persist the set of currently-passing test files as a "golden baseline"
    for the completed milestone.

    The golden baseline is written as a JSON file alongside the other tracking
    files.  Future S4 sessions for ANY milestone in this workplan load it via
    ``_load_golden_baseline()`` and treat every test in the set as inviolable —
    a test that was passing when milestone N completed must remain passing during
    milestone N+1, N+2, etc.

    This gives the regression guard cross-session durability: even if the operator
    presses [a] on a fresh process, the guard knows which tests were already green.

    File location: ``docs/workplan-tracking/{wname}.golden.json``
    Format::

        {
            "M0":  ["tests/acceptance/test_m0_bootstrap.py", ...],
            "M22": ["tests/...", ...],
        }

    Args:
        wname:       Workplan stem (used to construct the file path).
        milestone_id: The milestone that just completed (e.g. "M0").
        full_output:  Latest full pytest output — passing tests are derived from
                      the absence of FAILED/ERROR lines, not their presence.
    """
    import json as _json
    golden_path = TRACKING_DIR / f"{wname}.golden.json"
    existing: dict[str, list[str]] = {}
    if golden_path.exists():
        try:
            existing = _json.loads(golden_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    # Derive currently-passing test files: all tests minus the failing ones
    all_test_files = sorted(
        str(p.relative_to(PROJECT_ROOT))
        for p in PROJECT_ROOT.rglob("tests/**/*.py")
        if p.name.startswith("test_")
    )
    failing_now = set(_collect_failing_test_files(full_output))
    passing_now = [tf for tf in all_test_files if tf not in failing_now]

    existing[milestone_id] = passing_now
    golden_path.write_text(_json.dumps(existing, indent=2), encoding="utf-8")
    _ok(
        f"Golden baseline updated: {milestone_id} → "
        f"{len(passing_now)} passing test(s) recorded"
    )


def _load_golden_baseline(wname: str) -> set[str]:
    """
    Load the cross-session golden baseline for a workplan.

    Returns the union of all test files that were passing when ANY milestone
    in this workplan last completed cleanly.  The S4 regression guard uses
    this set in addition to the current-session snapshot so that regressions
    are detected even on a fresh process.

    Returns an empty set if no golden baseline has been written yet (first
    time running, or the file was deleted).

    Args:
        wname: Workplan stem.

    Returns:
        Set of test file paths that are part of the cross-session golden baseline.
    """
    import json as _json
    golden_path = TRACKING_DIR / f"{wname}.golden.json"
    if not golden_path.exists():
        return set()
    try:
        data: dict[str, list[str]] = _json.loads(golden_path.read_text(encoding="utf-8"))
        # Union of all milestones' passing test sets
        return set(tf for tests in data.values() for tf in tests)
    except Exception:
        return set()


def _append_lesson(
    wname: str,
    milestone_id: str,
    test_file: str,
    failure_class: str,
    outcome: str,
    detail: str = "",
) -> None:
    """
    Append one lesson record to ``{wname}.lessons.json``.

    A lesson is a compact structured record of what was attempted for a given
    (milestone, test_file) pair and what the outcome was.  Future S4 sessions
    load these lessons and inject them into the distilled context so the LLM
    does not repeat approaches that have already been proven ineffective.

    Responsibilities:
    - Load existing lessons file (or start empty).
    - Append a new record under ``milestone_id → [records]``.
    - Write back atomically (full rewrite — file is small).

    Does NOT:
    - Truncate old records — lessons accumulate indefinitely.
    - Raise on I/O error — lessons are advisory, never blocking.

    Args:
        wname:         Workplan stem.
        milestone_id:  Active milestone ID.
        test_file:     Relative path of the test file the lesson concerns.
        failure_class: From ``_classify_failure()`` (structural/interface/etc).
        outcome:       One of: "abandoned", "oscillation", "blast-radius-blocked",
                       "stalled", "resolved".
        detail:        Optional free-text note about what was tried / why it failed.

    Example:
        _append_lesson(wname, "M1", "tests/unit/test_m1_health.py",
                       "interface", "abandoned",
                       "3 attempts could not satisfy HealthResponse schema")
    """
    import json as _json
    lessons_path = TRACKING_DIR / f"{wname}.lessons.json"
    try:
        data: dict[str, list[dict]] = (
            _json.loads(lessons_path.read_text(encoding="utf-8"))
            if lessons_path.exists() else {}
        )
    except Exception:
        data = {}

    record = {
        "ts":            datetime.now(timezone.utc).isoformat(),
        "test_file":     test_file,
        "failure_class": failure_class,
        "outcome":       outcome,
        "detail":        detail,
    }
    data.setdefault(milestone_id, []).append(record)
    try:
        lessons_path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass   # lessons are advisory — never block on I/O failure


def _load_lessons_context(wname: str, milestone_id: str) -> str:
    """
    Load lesson records for ``milestone_id`` and format them as a compact
    context block for injection into S4's distilled context.

    Returns an empty string if no lessons exist or the file cannot be read.

    The returned string is short enough to prepend to the distilled context
    without eating into the implementation context budget.

    Args:
        wname:        Workplan stem.
        milestone_id: Active milestone ID.

    Returns:
        Formatted lessons string, or ``""`` if none.

    Example:
        ctx = _load_lessons_context(wname, "M1")
        # "## Lessons from previous S4 sessions for M1\n\n- test_m1_health.py ..."
    """
    import json as _json
    lessons_path = TRACKING_DIR / f"{wname}.lessons.json"
    if not lessons_path.exists():
        return ""
    try:
        data: dict[str, list[dict]] = _json.loads(lessons_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    records = data.get(milestone_id, [])
    if not records:
        return ""

    lines = [f"## Lessons from previous S4 sessions for {milestone_id}\n"]
    lines.append(
        "These approaches were attempted and FAILED — do not repeat them:\n"
    )
    # Show the most recent 8 records to keep context bounded
    for r in records[-8:]:
        short_file = Path(r.get("test_file", "?")).name
        fc   = r.get("failure_class", "?")
        out  = r.get("outcome", "?")
        note = r.get("detail", "")
        line = f"- `{short_file}` [{fc}] → {out}"
        if note:
            line += f": {note[:120]}"
        lines.append(line)

    return "\n".join(lines) + "\n"


def action_rollback_last_run(all_wt: "list[WorkplanTracking]") -> None:
    """Revert all files written in the most recent [a] run."""
    _h2("Rollback last run")
    active_wt = resolve_active_workplan(all_wt)
    if not active_wt:
        _warn("No active workplan."); return
    import json
    journal = TRACKING_DIR / f"{active_wt.workplan_name}.write-journal.jsonl"
    if not journal.exists():
        _warn("No write journal — nothing to roll back."); return
    records = [json.loads(l) for l in journal.read_text().splitlines() if l.strip()]
    if not records:
        _warn("Journal is empty."); return
    from datetime import timedelta
    cutoff   = (datetime.fromisoformat(records[-1]["ts"]) - timedelta(minutes=5)).isoformat()
    last_run = [r for r in records if r["ts"] >= cutoff]
    print(f"  Reverting {len(last_run)} file(s):")
    for r in reversed(last_run):
        dest = PROJECT_ROOT / r["path"]
        if r["prev"]:
            dest.write_text(r["prev"], encoding="utf-8")
            _ok(f"  Restored: {r['path']}")
        elif dest.exists():
            dest.unlink()
            _ok(f"  Deleted:  {r['path']}  (was new)")
    remaining = [r for r in records if r["ts"] < cutoff]
    journal.write_text("\n".join(json.dumps(r) for r in remaining) + "\n")
    _ok("Rollback complete.")


def _check_project_structure() -> list[str]:
    """Return list of structural problems (missing __init__.py etc)."""
    problems = []
    for root in ["services", "libs"]:
        rp = PROJECT_ROOT / root
        if not rp.exists(): continue
        for d in rp.rglob("*"):
            if d.is_dir() and any(d.glob("*.py")) and not (d / "__init__.py").exists():
                problems.append(str(d.relative_to(PROJECT_ROOT)))
    return problems


def action_agentic_build(all_wt: list[WorkplanTracking]) -> None:
    """Drive the next milestone step with Claude as implementation agent."""
    MAX_ITERATIONS = 3

    # ── Resolve active workplan and progress ─────────────────────────────────
    active_wt = resolve_active_workplan(all_wt)
    if active_wt is None:
        _warn("No active workplan selected. Use [w] to select one first.")
        return
    if active_wt.progress is None:
        _warn(f"Workplan '{active_wt.workplan_name}' has no .progress file.")
        _warn("Run [b] to bootstrap tracking files.")
        return

    wp               = active_wt.progress
    wname            = active_wt.workplan_name
    active_milestone = wp.active_milestone
    active_step      = wp.resume_detail
    step_id          = _step_id_from_detail(active_step)
    step_label       = next((lbl for sid, lbl in STEP_LABELS if sid == step_id), step_id)
    system_prompt    = _system_for_step(step_id)

    # ── Step purpose descriptions ─────────────────────────────────────────────
    STEP_PURPOSE = {
        "S1": "Review spec, confirm scope, identify ambiguities. No files written.",
        "S2": "Define abstract interfaces, Pydantic schemas, enums only. No implementation.",
        "S3": "Write failing tests for the interfaces defined in S2. No implementation.",
        "S4": "Write minimal implementation to make S3 tests pass.",
        "S5": "Run quality gate and produce a violation report. Fix blockers.",
        "S6": "Refactor for clarity without changing behaviour. Tests must stay green.",
        "S7": "Write integration tests against the real Docker Compose stack.",
        "S8": "Final checklist sign-off. Confirm milestone is shippable.",
    }
    purpose = STEP_PURPOSE.get(step_id, "")

    # ── STATUS PANEL ──────────────────────────────────────────────────────────
    w = 68
    print()
    print(f"  {C_BOLD}{C_CYAN}{'─' * w}{C_RESET}")
    print(f"  {C_BOLD}  BUILD STEP{C_RESET}")
    print(f"  {C_BOLD}{C_CYAN}{'─' * w}{C_RESET}")
    print(f"  Workplan : {wname}")
    print(f"  Milestone: {C_BOLD}{active_milestone}{C_RESET}  —  "
          f"{next((lbl for mid, lbl in MILESTONE_LIST if mid == active_milestone), '')}")
    print(f"  Step     : {C_BOLD}{C_CYAN}{step_id}{C_RESET}  {step_label}")
    print(f"  Purpose  : {C_DIM}{purpose}{C_RESET}")
    print()

    # Show all 8 steps for this milestone with status
    # Build step status map: {S1: status, S2: status, ...}
    # entry.steps now stores (bare_sid, status) e.g. ("S1", "DONE")
    step_statuses = {s: "NOT_STARTED" for s, _ in STEP_LABELS}
    for entry in wp.entries:
        if entry.milestone_id.upper() == active_milestone.upper():
            for bare_sid, step_status in entry.steps:
                key = bare_sid.upper()
                if key in step_statuses:
                    step_statuses[key] = step_status

    print(f"  {'Step':<6}  {'Label':<40}  Status")
    print(f"  {'─'*6}  {'─'*40}  {'─'*12}")
    for sid, slabel in STEP_LABELS:
        status = step_statuses.get(sid, "NOT_STARTED")
        if sid == step_id:
            row_col = C_CYAN + C_BOLD
            marker = " ◄ current"
        elif status == "DONE":
            row_col = C_DIM
            marker = ""
        else:
            row_col = ""
            marker = ""
        status_col = (C_GREEN if status == "DONE"
                      else C_CYAN if status == "IN_PROGRESS"
                      else C_RED if status == "BLOCKED"
                      else C_DIM)
        print(f"  {row_col}{sid:<6}  {slabel:<40}{C_RESET}  "
              f"{status_col}{status}{C_RESET}{marker}")

    print(f"  {C_BOLD}{C_CYAN}{'─' * w}{C_RESET}")

    # Always show acceptance criteria so engineer knows what done means
    wp_path_panel = find_workplan_file(wname)
    criteria_panel = _parse_acceptance_criteria(
        wp_path_panel, active_milestone
    ) if wp_path_panel else []
    if criteria_panel:
        print()
        print(f"  {C_BOLD}Done when:{C_RESET}")
        for i, c in enumerate(criteria_panel, 1):
            print(f"    {C_DIM}{i}.{C_RESET} {c}")
    print()

    # ── Sync check: header vs actual step statuses ────────────────────────────
    # If Active step says S2 but S1 is NOT_STARTED, the file is out of sync
    # (usually from a manual header edit without updating the step lines).
    all_sids   = [sid for sid, _ in STEP_LABELS]
    active_idx = all_sids.index(step_id) if step_id in all_sids else 0
    skipped    = [
        sid for sid in all_sids[:active_idx]
        if step_statuses.get(sid, "NOT_STARTED") == "NOT_STARTED"
    ]
    if skipped:
        _warn(f"Progress file sync issue: {step_id} is set as active but "
              f"{', '.join(skipped)} {'is' if len(skipped)==1 else 'are'} still NOT_STARTED.")
        print()
        print(f"  Options:")
        print(f"    {C_BOLD}[b]{C_RESET}ack  — go back and run the skipped step(s) first (recommended)")
        print(f"    {C_BOLD}[s]{C_RESET}kip  — mark skipped steps DONE and continue with {step_id}")
        print(f"    {C_BOLD}[c]{C_RESET}ancel")
        print()
        choice = input(f"  {C_YELLOW}Choice [b/s/c]:{C_RESET} ").strip().lower()
        if choice == "c":
            _info("Cancelled.")
            return
        elif choice == "s":
            # Repair: mark each skipped step DONE using the same advance function
            # that handles all the regex bookkeeping correctly.
            for sid in skipped:
                advance_progress_step(wp.progress_file, active_milestone, sid)
                _ok(f"Repaired: {sid} marked DONE")
            # Re-read the updated progress so the status panel is current
            wp = _parse_progress(wp.progress_file)
            if wp is None:
                _err("Could not re-read progress file after repair.")
                return
            _info(f"Progress file repaired — continuing with {step_id}")
        else:
            # Go back to first skipped step
            first_skipped = skipped[0]
            # Rewind active step header
            pf_text = wp.progress_file.read_text(encoding="utf-8")
            first_label = next((lbl for sid, lbl in STEP_LABELS if sid == first_skipped), first_skipped)
            new_active = f"STEP {all_sids.index(first_skipped)+1} -- {first_label} ({active_milestone})"
            pf_text = re.sub(
                r"^# Active step:.*$", f"# Active step: {new_active}", pf_text, flags=re.MULTILINE
            )
            wp.progress_file.write_text(pf_text, encoding="utf-8")
            _ok(f"Active step rewound to {first_skipped} — run [a] to execute it")
            return

    # ── Prerequisite gate ─────────────────────────────────────────────────────
    prereqs_ok, blocking = check_prerequisites(active_wt, active_milestone)
    if not prereqs_ok:
        _err(f"Prerequisites not met for {active_milestone}:")
        for b in blocking:
            _err(f"  {b} must be DONE before this milestone can start")
        answer = input(
            f"  {C_YELLOW}Override and proceed anyway? [y/N]{C_RESET} "
        ).strip().lower()
        if answer != "y":
            return

    # ── Contract drift check ──────────────────────────────────────────────────
    if wp.progress_file.exists():
        fp_ok, drifted = check_contract_fingerprints(wp.progress_file)
        if not fp_ok:
            _warn("Interface contracts changed since S2 — downstream context may be stale:")
            for d in drifted:
                _warn(f"  {d}")
            _warn("Consider [d] → refresh to update distilled context for this milestone.")

    # ── Load context ──────────────────────────────────────────────────────────
    workplan_path    = find_workplan_file(wname)
    workplan_section = ""
    if workplan_path and workplan_path.exists():
        full_text = workplan_path.read_text(encoding="utf-8")
        pat = re.compile(
            rf"###\s+Milestone\s+{re.escape(active_milestone)}[\s:].+?"
            rf"(?=\n###\s+Milestone\s+M|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        m = pat.search(full_text)
        workplan_section = m.group(0) if m else full_text[:8000]

    distilled_ctx = load_milestone_context(wname, active_milestone)
    if distilled_ctx:
        spec_section = f"## Distilled Context for {active_milestone}\n\n{distilled_ctx}\n\n"
    else:
        spec_section = ""
        if not distilled_file_path(wname).exists():
            _warn("No distilled context — run [d] first.")

    state_dump = build_state_dump(all_wt)

    # Load build log history as RAG context for S4 (knows what S3 failures to fix)
    build_log_ctx = ""
    if step_id in ("S4", "S7"):
        build_log = TRACKING_DIR / f"{wname}.build-log.md"
        if build_log.exists():
            raw = build_log.read_text(encoding="utf-8")
            excerpt = raw[-5000:] if len(raw) > 5000 else raw
            build_log_ctx = (
                f"## Build Log History\n\n"
                f"Previous test failures for {active_milestone} (most recent last):\n\n"
                f"{excerpt}\n\n"
            )
            _info(f"Build log context: {len(excerpt)} chars from {build_log.name}")

    def _build_user_content(extra: str = "") -> str:
        return (
            f"## Active Task\n\nWorkplan: {wname}\n"
            f"Milestone: {active_milestone}\nStep: {step_id} — {step_label}\n\n"
            f"{spec_section}"
            f"## Workplan Spec for {active_milestone}\n\n"
            f"{workplan_section or '(no workplan section found)'}\n\n"
            f"## Current Project State\n\n{state_dump}\n\n"
            f"{build_log_ctx}"
            f"{extra}"
            f"## Instructions\n\nExecute step {step_id} ({step_label}) "
            f"for milestone {active_milestone}.\n"
            f"Follow the output rules in your system prompt exactly.\n"
        )

    # ── Confirm before sending ────────────────────────────────────────────────
    ctx_tokens = (len(distilled_ctx) // 4) if distilled_ctx else 0
    wp_tokens  = len(workplan_section) // 4
    _info(f"Context: ~{ctx_tokens} distilled + ~{wp_tokens} workplan tokens")
    answer = input(
        f"  {C_YELLOW}Run {step_id} for {active_milestone}? [Y/n]{C_RESET} "
    ).strip().lower()
    if answer == "n":
        _info("Cancelled.")
        return

    # ── Pre-flight: check pytest is available for test steps ────────────────
    if step_id in ("S3", "S4", "S7"):
        pytest_check = subprocess.run(
            [str(VENV_PYTHON), "-m", "pytest", "--version"],
            capture_output=True, text=True,
        )
        if pytest_check.returncode != 0:
            _err("pytest is not installed in the venv.")
            _err("Run this before continuing:")
            _err(f"  {VENV_PIP} install pytest pytest-asyncio pytest-cov")
            _err("Then run [a] again.")
            return

    # ── Iteration strategy depends on step ───────────────────────────────────
    written_paths:    list[str] = []
    response:         str       = ""
    _s4_tests_passed: Optional[bool] = None  # set by S4 loop, read by advance block

    if step_id == "S3":
        # ── S3 RED: ground tests in workplan acceptance criteria ──────────────
        label_short = step_label.split(" -- ")[0] if " -- " in step_label else step_label

        # Extract acceptance criteria from workplan — the authoritative definition of done
        wp_path = find_workplan_file(wname)
        criteria = _parse_acceptance_criteria(wp_path, active_milestone) if wp_path else []
        if criteria:
            _ok(f"Found {len(criteria)} acceptance criteria for {active_milestone}:")
            for i, c in enumerate(criteria, 1):
                print(f"    {C_DIM}{i}.{C_RESET} {c}")
            ac_section = _criteria_to_test_plan(criteria, active_milestone)

            # ── Spec quality gate ──────────────────────────────────────────────
            # Check ACs for signs of untestability before writing any tests.
            # Writing tests for unverifiable ACs wastes LLM calls and produces
            # tests that can never pass, polluting every subsequent S4 run.
            ac_warnings = _check_ac_quality(criteria)
            if ac_warnings:
                print()
                _warn(
                    f"SPEC QUALITY GATE: {len(ac_warnings)} acceptance "
                    "criterion/criteria may be untestable or ambiguous:"
                )
                for w in ac_warnings:
                    _warn(f"  ⚠  {w}")
                print()
                print(
                    f"  {C_DIM}These ACs may produce tests that can never pass, "
                    "wasting LLM calls in S4.  Recommended: edit the workplan "
                    "to make them measurable before continuing.{C_RESET}"
                )
                choice = input(
                    f"\n  {C_YELLOW}Continue with S3 anyway? [y/N]:{C_RESET} "
                ).strip().lower()
                if choice != "y":
                    _info("S3 cancelled — edit the workplan and try again.")
                    return
                print()

            # ── Complexity budget gate ─────────────────────────────────────────
            # Check whether this milestone's scope is too broad for a single
            # S3→S4 cycle.  Milestones that cross too many layers or carry too
            # many ACs reliably produce S4 blast-radius oscillation regardless
            # of how good the tests are.  This is a WARNING gate (not a hard
            # stop) because the operator may intentionally have a broad milestone.
            complexity_warnings = _check_milestone_complexity(
                criteria, workplan_section or "", active_milestone
            )
            if complexity_warnings:
                print()
                _warn(
                    f"COMPLEXITY BUDGET: {len(complexity_warnings)} scope warning(s) "
                    "for this milestone:"
                )
                for w in complexity_warnings:
                    _warn(f"  ⚠  {w}")
                print(
                    f"  {C_DIM}Overly broad milestones are the primary cause of "
                    "S4 oscillation — the blast radius of any change is too large "
                    "for the agent to navigate without circular regressions.\n"
                    "  Consider splitting this milestone before writing tests. "
                    "Press Enter to continue anyway or Ctrl-C to exit.{C_RESET}"
                )
                input()  # pause for operator acknowledgement only — not a hard stop
        else:
            _warn("No acceptance criteria found in workplan — tests will be less targeted")
            ac_section = ""

        def _build_s3_content() -> str:
            return (
                f"## Task: Write RED tests for {active_milestone}\n\n"
                f"{spec_section}"
                f"## Workplan spec\n\n{workplan_section or '(not found)'}\n\n"
                f"{ac_section}\n\n"
                f"## Project state\n\n{state_dump}\n\n"
                f"## Instructions\n\n"
                f"Write failing tests that verify EACH acceptance criterion above.\n"
                f"Label each test test_ac1_..., test_ac2_... etc.\n"
                f"Tests must fail for the RIGHT reason (not ImportError — the interfaces must exist).\n"
                f"Do NOT test things not in the acceptance criteria list.\n"
                f"Use <<<FILE: path>>> ... <<<END_FILE>>> format.\n"
            )

        try:
            with Spinner(f"{step_id} {label_short}  [{active_milestone}]"):
                response = call_claude(
                    system=system_prompt,
                    messages=[{"role": "user", "content": _build_s3_content()}],
                    max_tokens=8192,
                )
        except RuntimeError as exc:
            _err(f"API call failed: {exc}")
            return

        narrative = re.sub(r"<<<FILE:.*?<<<END_FILE>>>", "", response, flags=re.DOTALL).strip()
        if narrative:
            print()
            print(narrative)

        file_blocks = _extract_files(response)
        if file_blocks:
            print()
            print(f"  {C_BOLD}Writing {len(file_blocks)} file(s){C_RESET}")
            for rel_path, content in file_blocks:
                rel_path, content, warn = _validate_and_redirect(rel_path, content)
                if warn:
                    _warn(f"  {warn}")
                if rel_path is None:    # protected — skip entirely
                    continue
                dest = PROJECT_ROOT / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                _ok(f"{rel_path}  ({len(content.splitlines())} lines)")
                written_paths.append(rel_path)

        print()
        tests_pass, failure_output = run_tests_capture()
        if not tests_pass:
            _ok("Tests fail as expected (RED phase complete)")
            build_log = TRACKING_DIR / f"{wname}.build-log.md"
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            TRACKING_DIR.mkdir(parents=True, exist_ok=True)
            with open(build_log, "a", encoding="utf-8") as bl:
                bl.write(f"\n## {timestamp}  {active_milestone} S3 RED baseline\n\n")
                bl.write(f"Acceptance criteria ({len(criteria)}):\n")
                for c in criteria:
                    bl.write(f"  - {c}\n")
                bl.write(f"\nRED failures S4 must fix:\n\n```\n{failure_output[:4000]}\n```\n")
            _info(f"RED baseline logged to {build_log.name}")
        else:
            _warn("All tests passed — S3 RED tests should fail. Check test assertions.")

    elif step_id in ("S4", "S7"):
        # ── S4/S7 GREEN: multi-round, per-file targeted loop ─────────────────
        #
        # Strategy (avoids the "implement everything in 8192 tokens" problem):
        #
        #   Outer loop — up to MAX_ITERATIONS rounds per [a] press:
        #     Run full suite → collect failing files → for each file:
        #       1. Call Claude with (test file + current failures) [attempt 1]
        #       2. Re-run test immediately
        #       3. If still failing, call Claude again with the *new* error output
        #          — this is the highest-signal RAG input because it describes
        #          what the implementation actually got wrong, not the original
        #          missing-file error [attempt 2 / per-file retry]
        #     After the inner file loop, re-run full suite.
        #     Break early if everything passes; otherwise start the next round.
        #
        #   MAX_ITERATIONS (outer): how many full passes per [a] press.
        #   MAX_FILE_ROUNDS (inner): max distinct failing files per pass.
        #   PER_FILE_RETRIES: extra Claude calls per file if first attempt fails.

        MAX_FILE_ROUNDS  = 10   # max distinct test files per outer round
        PER_FILE_RETRIES = 1    # per-file retry attempts after first failure

        build_log = TRACKING_DIR / f"{wname}.build-log.md"
        TRACKING_DIR.mkdir(parents=True, exist_ok=True)

        print()
        # Structural pre-flight: ensure all __init__.py + lib skeletons exist
        _ensure_package_inits()

        log = BuildLog(wname)
        all_written_this_session: set[str] = set()

        # ── Regression baseline snapshot ───────────────────────────────────────
        # Cross-session golden baseline (persisted on disk):
        #   Loaded from {wname}.golden.json.  Contains test files that were
        #   passing when a previous milestone completed cleanly.  Used here to
        #   warn the operator if those tests are ALREADY failing at S4 startup —
        #   meaning something broke between sessions, before today's [a] press.
        #   Future rounds are then protected by the in-session baseline below.
        _golden_baseline: set[str] = _load_golden_baseline(wname)

        # ── Lessons-learned context injection ─────────────────────────────────
        # Load any lesson records written by previous S4 sessions for this
        # milestone.  Prepend them to the distilled context so every LLM call
        # in this session knows which approaches already failed and must not
        # be repeated.  This gives the system cross-session memory without
        # requiring any changes to the prompt structure — the lessons block
        # simply precedes the distilled milestone content.
        _lessons_ctx = _load_lessons_context(wname, active_milestone)
        if _lessons_ctx:
            _warn(
                f"Lessons from previous sessions loaded for {active_milestone} "
                f"— {_lessons_ctx.count(chr(10) + '-')} prior failure(s) recorded"
            )
            distilled_ctx = _lessons_ctx + "\n" + (distilled_ctx or "")

        # In-session baseline: run the full suite now and record what's failing.
        # Tests that are PASSING right now are protected for the duration of S4.
        # Any round that causes a previously-passing test to fail triggers rollback.
        _info("Snapshotting regression baseline ...")
        _baseline_pass, _baseline_output = run_tests_capture()
        _baseline_failing: set[str] = set(_collect_failing_test_files(_baseline_output))

        # Cross-session regression alert: golden tests that are already failing now
        _cross_session_regressions = _golden_baseline & _baseline_failing
        if _cross_session_regressions:
            _warn(
                f"CROSS-SESSION REGRESSIONS: {len(_cross_session_regressions)} test(s) "
                "that passed at a previous milestone are already failing at S4 start "
                "(broken between sessions, before this run):"
            )
            for tf in sorted(_cross_session_regressions):
                _warn(f"  ⚠  {Path(tf).name}")
        # Also track env-skippable tests so they don't look like regressions
        _env_skip_files: set[str] = set()
        if _baseline_failing:
            _info(
                f"Baseline: {len(_baseline_failing)} pre-existing failure(s) "
                f"(S4 will only fix these)"
            )
        else:
            _info("Baseline: all tests passing")

        # ── Spec-test coherence gate ───────────────────────────────────────────
        # Verify that each AC written in the workplan has at least one
        # corresponding test assertion in the S3-produced test files.
        #
        # Why here (S4 start) rather than S3 end:
        #   At S3 end the test files may not exist on disk yet (they're being
        #   written by the LLM in that same call).  At S4 start they always
        #   exist — we can read them and verify coverage before burning rounds.
        #
        # This is a warning gate, not a hard stop: if an AC looks uncovered the
        # operator is informed with the specific tokens that were searched for,
        # so they can verify whether it's a real gap or a false positive.

        # Fetch acceptance criteria for this milestone (needed for both the
        # coherence gate below and the workplan complexity budget check).
        # Note: `criteria` is only assigned inside the S3 branch above, so we
        # must re-fetch it here independently for S4.
        _s4_wp_path = find_workplan_file(wname)
        criteria = (
            _parse_acceptance_criteria(_s4_wp_path, active_milestone)
            if _s4_wp_path else []
        )

        if criteria:
            _s4_test_files = _collect_milestone_test_files(active_milestone)
            _ac_alignment_warnings = _check_ac_test_alignment(criteria, _s4_test_files)
            if _ac_alignment_warnings:
                _warn(
                    f"SPEC-TEST COHERENCE: {len(_ac_alignment_warnings)} AC(s) "
                    "appear to have no matching test assertion:"
                )
                for w in _ac_alignment_warnings:
                    _warn(f"  ⚠  {w}")
                _warn(
                    "S4 may spend rounds trying to pass tests that don't exist. "
                    "Verify these ACs are covered before investing more LLM calls."
                )
            else:
                _info(
                    f"Spec-test coherence OK: all {len(criteria)} AC(s) appear "
                    "represented in test files"
                )

        # ── Promoted-to-passing set ────────────────────────────────────────────
        # Tracks tests that were in _baseline_failing but have since passed
        # during THIS S4 session.  Once a test is promoted, it is treated the
        # same as a baseline-passing test — any round that causes it to fail
        # again triggers the regression rollback.
        #
        # This plugs a subtle gap: the regression guard compares against
        # _baseline_failing, so a test that was failing at session start but
        # passes in round 1 would NOT be protected from being broken again in
        # round 2.  By moving it into the protected set on pass, we close that.
        _promoted_to_passing: set[str] = set()

        # ── Per-file abandon threshold ─────────────────────────────────────────
        # Tracks how many total LLM attempts have been made for each test file
        # across ALL outer iterations.  A test file that has consumed
        # MAX_FILE_ATTEMPTS attempts without passing is almost certainly
        # blocked by an untestable spec, a missing env capability that slipped
        # past the env-cap gate, or a shared-module conflict that blast-radius
        # alone cannot resolve.  Continuing to call the LLM wastes tokens
        # without converging.
        #
        # Files that hit the threshold are:
        #   - Skipped for further LLM calls in this session.
        #   - Reported in the handoff summary as "manual review required".
        #   - NOT counted as regressions (they were already failing at baseline).
        MAX_FILE_ATTEMPTS   = 4   # total LLM calls across all rounds before abandoning
        _file_attempt_counts: dict[str, int] = {}
        _abandoned_files:     set[str]       = set()

        # ── Oscillation tracking ───────────────────────────────────────────────
        # Stores a frozenset fingerprint of failing test files after each round.
        # If the same fingerprint appears twice, the loop is thrashing — Claude is
        # cycling between failure states without making progress.  Continuing would
        # only burn more tokens without converging; we stop and tell the operator.
        _seen_failure_fingerprints: list[frozenset[str]] = []
        _oscillation_detected: bool = False   # propagated to handoff recommendation

        # ── Convergence metric ─────────────────────────────────────────────────
        # Tracks the count of actionable failing files at the end of each outer
        # iteration (after regression rollback, after env-skip exclusion, after
        # abandoned-file exclusion).  Used to detect STALL: two consecutive
        # rounds where the count did not decrease.
        #
        # Stall ≠ oscillation.  Oscillation means the SAME files keep failing
        # in a cycle; stall means progress has plateaued (could be N different
        # files each round, all resistant to fixing).  Both warrant early exit,
        # but for different reasons and with different operator guidance.
        _round_failing_counts: list[int] = []
        _stall_detected: bool = False

        # ── Outer iteration loop ───────────────────────────────────────────────
        for iteration in range(1, MAX_ITERATIONS + 1):

            iter_label = f"round {iteration}/{MAX_ITERATIONS}"
            # Timestamp used to identify journal entries from this round only,
            # so we can roll back just this round if regressions are detected.
            round_start_ts = datetime.now(timezone.utc).isoformat()

            _info(f"Running full test suite ({iter_label}) ...")
            all_pass, full_output = run_tests_capture()

            if all_pass:
                break   # done — exit outer loop

            failing_files = _collect_failing_test_files(full_output)
            total_files   = len(failing_files)

            # ── Oscillation check ──────────────────────────────────────────────
            # Fingerprint = frozenset of currently-failing files (excl. env-skips)
            current_fingerprint = frozenset(
                f for f in failing_files if f not in _env_skip_files
            )
            if current_fingerprint in _seen_failure_fingerprints:
                _oscillation_detected = True
                _err(
                    f"OSCILLATION DETECTED after {iter_label}: "
                    "the same set of tests is failing as a previous round — "
                    "continuing would repeat the same mistakes."
                )
                _warn(
                    "The agent is cycling between failure states. "
                    "Manual intervention required: inspect the rolled-back "
                    "files, adjust the spec, or add a known-fix entry."
                )
                log.detail(
                    f"OSCILLATION: fingerprint {sorted(current_fingerprint)} "
                    f"seen at round {_seen_failure_fingerprints.index(current_fingerprint) + 1} "
                    f"and again at round {iteration}"
                )
                break
            _seen_failure_fingerprints.append(current_fingerprint)

            if not failing_files:
                break   # collection error — can't proceed; caller handles

            _info(f"Found {total_files} failing test file(s)")
            log.section(f"S4 {active_milestone} — {iter_label}, {total_files} file(s)")

            # ── Root-cause deduplication ───────────────────────────────────────
            # Before calling the LLM once per file, check whether multiple failing
            # tests share the same root cause (a missing module / symbol that
            # appears in every failure output).  Fixing the shared root cause
            # first — in a single LLM call — can resolve several tests at once,
            # avoiding N redundant calls that each attempt to create the same file.
            shared_missing = _extract_shared_missing_modules(
                failing_files[:MAX_FILE_ROUNDS], full_output
            )
            if len(shared_missing) > 1:
                # More than one test cites the same missing root; fix it centrally.
                _info(
                    f"  Root-cause dedup: {len(shared_missing)} tests share "
                    f"missing module(s): {', '.join(sorted(shared_missing))} — "
                    "single batch fix call before per-file loop"
                )
                log.section(f"Root-cause batch fix: {sorted(shared_missing)}")
                batch_written, _ = _targeted_implement(
                    test_file      = failing_files[0],  # representative test
                    test_content   = _load_test_file(failing_files[0]),
                    failure_output = (
                        f"# Multiple tests ({len(shared_missing)}) share this root cause:\n"
                        + full_output[:2000]
                    ),
                    milestone_id   = active_milestone,
                    distilled_ctx  = distilled_ctx or "",
                    wname          = wname,
                    system_prompt  = system_prompt,
                    existing_paths = all_written_this_session,
                )
                written_paths.extend(batch_written)
                all_written_this_session.update(batch_written)
                for p in batch_written:
                    log.detail(f"batch-wrote: {p}")
                # Re-run to see how many tests the batch fix resolved
                _, full_output = run_tests_capture()
                failing_files = _collect_failing_test_files(full_output)
                _info(
                    f"  After batch fix: {len(failing_files)} file(s) still failing"
                )

            # ── Blast-radius map ───────────────────────────────────────────────
            # Build a reverse import map ONCE per outer round (not per file) so
            # the cost is amortised across all files in this iteration.
            # The map tells us: for each source file, which passing tests import it.
            # We use this to compute each failing test's "blast radius" — the set
            # of currently-passing tests that share a source-file dependency and
            # could break if the agent modifies that shared source file.
            #
            # Rationale for per-round rebuild (vs once per session):
            #   Prior rounds may have WRITTEN new source files.  A newly created
            #   file can now be imported by tests that previously failed to import
            #   it.  Rebuilding ensures the map reflects the current disk state.
            _reverse_map = _build_reverse_import_map()
            _all_test_files: set[str] = (
                {
                    str(p.relative_to(PROJECT_ROOT))
                    for p in (PROJECT_ROOT / "tests").rglob("test_*.py")
                }
                if (PROJECT_ROOT / "tests").exists()
                else set()
            )
            _passing_tests = (
                _all_test_files
                - set(failing_files)
                - _env_skip_files
            )
            _info(
                f"Blast-radius map: {len(_reverse_map)} source file(s) tracked, "
                f"{len(_passing_tests)} passing test(s) in protection set"
            )

            # ── Inner file loop ────────────────────────────────────────────────
            for file_idx, test_file in enumerate(failing_files[:MAX_FILE_ROUNDS], 1):
                short = Path(test_file).name
                print(
                    f"  [{file_idx}/{min(total_files, MAX_FILE_ROUNDS)}] "
                    f"{short:<52}",
                    end="", flush=True,
                )
                log.section(f"File: {test_file}")

                file_pass, file_output = _run_specific_tests(test_file)
                log.code_block(file_output)
                if file_pass:
                    print(f"{C_GREEN}pass{C_RESET}")
                    continue

                test_content = _load_test_file(test_file)
                if not test_content:
                    print(f"{C_RED}unreadable{C_RESET}")
                    continue

                # ── Environment capability gate ────────────────────────────────
                # Some tests require tooling (npm, docker, redis …) that is not
                # present in this execution environment.  Calling the LLM to fix
                # them is futile — the only fix is installing the tool, not
                # editing Python.  Skip them here and count separately so they
                # don't pollute the regression/failure report.
                missing_caps = _detect_missing_env_caps(test_content)
                if missing_caps:
                    _env_skip_files.add(test_file)
                    print(f"{C_YELLOW}env-skip{C_RESET}")
                    for cap in missing_caps:
                        _warn(f"    ENV_SKIP  {cap}")
                    log.detail(f"ENV_SKIP — missing: {', '.join(missing_caps)}")
                    continue  # no LLM call — cannot be resolved in this environment

                # ── Triage: fix structural failures without calling LLM ────────
                # ModuleNotFoundError and path-existence assertions are purely
                # mechanical — a missing __init__.py or directory will never be
                # solved by LLM reasoning.  Fix deterministically first.
                failure_class = _classify_failure(file_output)
                if failure_class == "structural":
                    _info(f"  {short}: structural failure — running scaffold fix ...")
                    _ensure_package_inits()
                    file_pass_s, file_output_s = _run_specific_tests(test_file)
                    if file_pass_s:
                        print(f"{C_GREEN}✔{C_RESET}  (structural fix, no LLM call)")
                        log.detail("structural fix resolved without LLM")
                        continue
                    # Scaffold didn't fully resolve — escalate to LLM with
                    # the post-scaffold output (more informative than original)
                    file_output = file_output_s
                    log.detail("structural fix partial — escalating to LLM")

                print(f"{C_YELLOW}...{C_RESET}", flush=True)

                # ── Abandon threshold check ────────────────────────────────────
                # If this test has already consumed MAX_FILE_ATTEMPTS LLM calls
                # across all outer iterations, stop spending tokens on it.
                # It is almost certainly blocked by something outside the LLM's
                # control (bad spec, env issue, unresolvable shared-module
                # conflict).  Mark it as abandoned and skip.
                _file_attempt_counts[test_file] = _file_attempt_counts.get(test_file, 0)
                if _file_attempt_counts[test_file] >= MAX_FILE_ATTEMPTS:
                    _warn(
                        f"  {short}: abandon threshold reached "
                        f"({MAX_FILE_ATTEMPTS} attempts) — skipping; "
                        "manual review required"
                    )
                    log.detail(f"ABANDONED: {test_file} hit {MAX_FILE_ATTEMPTS}-attempt limit")
                    _abandoned_files.add(test_file)
                    print(f"{C_RED}abandoned{C_RESET}")
                    continue

                # Compute blast radius for this specific failing test.
                # Any passing test that shares a direct source-file import
                # with test_file is at risk of regression if the agent edits
                # that shared source file.  We pass this list to the LLM so
                # it knows the full constraint surface before choosing a fix.
                at_risk = _blast_radius_tests(test_file, _passing_tests, _reverse_map)
                if at_risk:
                    log.detail(
                        f"blast radius for {Path(test_file).name}: "
                        + ", ".join(Path(t).name for t in at_risk)
                    )

                # Compute the minimum repair surface — the files the agent should
                # need to write to fix this test.  Derived from the test's direct
                # imports and the failure traceback.  Passed to _targeted_implement
                # as a named allowlist so the LLM knows the minimal change scope
                # before deciding what to write.  Together with blast_radius, this
                # brackets the acceptable change surface from both directions.
                repair_sfc = _compute_repair_surface(test_content, file_output)
                if repair_sfc:
                    log.detail(
                        f"repair surface for {Path(test_file).name}: "
                        + ", ".join(Path(f).name for f in repair_sfc)
                    )

                # ── Attempt 1 ─────────────────────────────────────────────────
                _file_attempt_counts[test_file] = _file_attempt_counts.get(test_file, 0) + 1
                attempt1_ts = datetime.now(timezone.utc).isoformat()
                new_paths, file_response = _targeted_implement(
                    test_file      = test_file,
                    test_content   = test_content,
                    failure_output = file_output,
                    milestone_id   = active_milestone,
                    distilled_ctx  = distilled_ctx or "",
                    wname          = wname,
                    system_prompt  = system_prompt,
                    existing_paths = all_written_this_session,
                    at_risk_tests  = at_risk or None,
                    repair_surface = repair_sfc or None,
                )
                written_paths.extend(new_paths)
                response = file_response
                all_written_this_session.update(new_paths)
                for p in new_paths:
                    log.detail(f"wrote: {p}")

                # ── Post-write blast-radius verification ───────────────────────
                # The LLM was told about at-risk tests in the prompt; now verify
                # the constraint was actually honoured.  Running at-risk tests
                # here (before the full suite) catches regressions at the point
                # of write — preventing them from compounding across files.
                # If any at-risk test now fails, roll back this write immediately.
                if at_risk and new_paths:
                    br_ok, br_regressed, br_rolled = _run_blast_radius_check(
                        at_risk=at_risk, wname=wname, since_ts=attempt1_ts
                    )
                    if not br_ok:
                        _err(
                            f"  {short}: blast-radius regression after attempt 1 "
                            f"— {len(br_regressed)} at-risk test(s) now failing; "
                            f"rolled back {br_rolled} file(s)"
                        )
                        for t in br_regressed:
                            _err(f"      ✖  {Path(t).name}")
                        log.detail(
                            f"BLAST-RADIUS ROLLBACK (attempt 1): {br_regressed}; "
                            f"{br_rolled} file(s) restored"
                        )
                        # Remove rolled-back paths from tracking
                        for p in new_paths:
                            written_paths.remove(p) if p in written_paths else None
                            all_written_this_session.discard(p)
                        # Re-run the target test against the rolled-back state
                        # to get a clean failure output for the retry
                        _, file_output = _run_specific_tests(test_file)
                        new_paths = []  # signal to retry logic: nothing written

                file_pass2, file_output2 = _run_specific_tests(test_file)

                # ── Per-file retry loop ────────────────────────────────────────
                # The retry call receives:
                #   - file_output2: what the implementation ACTUALLY got wrong
                #     (not the original missing-file error) — highest-signal RAG
                #   - prior_attempt_context: the build-log excerpt for this file
                #     from the current session, so Claude knows what it already
                #     tried and can make a surgical correction
                for retry_num in range(1, PER_FILE_RETRIES + 1):
                    if file_pass2:
                        break
                    _info(
                        f"  {short}: still failing — "
                        f"retry {retry_num}/{PER_FILE_RETRIES} with updated context"
                    )
                    log.detail(f"retry {retry_num} for {test_file}")
                    log.code_block(file_output2)

                    # ── Abandon threshold re-check before retry ────────────────
                    _file_attempt_counts[test_file] += 1
                    if _file_attempt_counts[test_file] > MAX_FILE_ATTEMPTS:
                        _warn(
                            f"  {short}: abandon threshold reached during retry — "
                            "skipping remaining retries"
                        )
                        _abandoned_files.add(test_file)
                        log.detail(
                            f"ABANDONED mid-retry: {test_file} at "
                            f"{_file_attempt_counts[test_file]} attempts"
                        )
                        break

                    # Extract the relevant build-log section for this test file
                    # so the retry call knows what was already attempted
                    prior_ctx = _build_log_excerpt_for_file(
                        build_log_path = build_log,
                        test_file      = test_file,
                        max_chars      = 1500,
                    )

                    retry_ts = datetime.now(timezone.utc).isoformat()
                    retry_paths, _ = _targeted_implement(
                        test_file             = test_file,
                        test_content          = test_content,
                        failure_output        = file_output2,
                        milestone_id          = active_milestone,
                        distilled_ctx         = distilled_ctx or "",
                        wname                 = wname,
                        system_prompt         = system_prompt,
                        existing_paths        = all_written_this_session,
                        prior_attempt_context = prior_ctx,
                        at_risk_tests         = at_risk or None,
                        repair_surface        = repair_sfc or None,
                    )
                    written_paths.extend(retry_paths)
                    all_written_this_session.update(retry_paths)
                    for p in retry_paths:
                        log.detail(f"wrote (retry {retry_num}): {p}")

                    # Post-write blast-radius check for retry as well
                    if at_risk and retry_paths:
                        br_ok, br_regressed, br_rolled = _run_blast_radius_check(
                            at_risk=at_risk, wname=wname, since_ts=retry_ts
                        )
                        if not br_ok:
                            _err(
                                f"  {short}: blast-radius regression after retry "
                                f"{retry_num} — rolled back {br_rolled} file(s)"
                            )
                            log.detail(
                                f"BLAST-RADIUS ROLLBACK (retry {retry_num}): "
                                f"{br_regressed}; {br_rolled} file(s) restored"
                            )
                            for p in retry_paths:
                                written_paths.remove(p) if p in written_paths else None
                                all_written_this_session.discard(p)
                            _, file_output2 = _run_specific_tests(test_file)
                            retry_paths = []

                    file_pass2, file_output2 = _run_specific_tests(test_file)

                icon = f"{C_GREEN}✔{C_RESET}" if file_pass2 else f"{C_RED}✖{C_RESET}"
                print(f"     {short:<52}  {icon}")
                if file_pass2 and test_file in _baseline_failing:
                    # This test was failing at session start but now passes.
                    # Promote it: from here on it must stay passing.
                    _promoted_to_passing.add(test_file)
                    log.detail(f"promoted to passing: {test_file}")
                if not file_pass2:
                    log.code_block(file_output2)

            # End of inner loop — evaluate before starting next outer round
            all_pass, full_output = run_tests_capture()
            log.code_block(full_output)

            if all_pass:
                break

            # ── Regression guard ───────────────────────────────────────────────
            # Classify current failures: pre-existing vs newly-caused regressions.
            # Env-skip files are excluded from both categories — they can never
            # be fixed in this environment and are not counted as regressions.
            current_failing = set(_collect_failing_test_files(full_output))
            current_failing -= _env_skip_files
            # A regression is either:
            #   (a) a test that was PASSING at session start and is now failing, OR
            #   (b) a test that was promoted to passing during this session
            #       (was in _baseline_failing but passed in a previous round)
            #       and has since been broken again.
            regressions = (current_failing - _baseline_failing) | (
                _promoted_to_passing & current_failing
            )
            if regressions:
                _err(
                    f"REGRESSION DETECTED after {iter_label}: "
                    f"{len(regressions)} test(s) that were passing are now failing:"
                )
                for tf in sorted(regressions):
                    _err(f"  ✖  {Path(tf).name}")
                _warn("Rolling back this round's writes to prevent compounding damage ...")

                # Restore all files written this round using the shared helper.
                # All journal entries at or after round_start_ts belong to this
                # round — blast-radius per-file rollbacks that already ran will
                # have no-op duplicates in the journal which are harmless.
                restored = _rollback_writes_since(wname, round_start_ts)
                if restored:
                    _ok(f"Rolled back {restored} file(s) from {iter_label}")
                    log.detail(
                        f"REGRESSION ROLLBACK: {len(regressions)} regression(s); "
                        f"{restored} file(s) restored from journal"
                    )
                else:
                    _warn("Write journal not found — cannot auto-rollback; use [rw] manually")
                # Stop the outer loop; don't start another round that will regress further
                break

            # Actionable failing count: exclude env-skips and abandoned files —
            # these will never be resolved by further LLM calls, so they must
            # not influence the convergence signal.
            actionable_failing = (
                current_failing - _env_skip_files - _abandoned_files
            )
            remaining_count = len(actionable_failing)
            if remaining_count == 0:
                break   # collection error or all remaining are env-skip / abandoned

            _info(
                f"End of {iter_label}: {remaining_count} actionable failing file(s)"
                + (f" — starting round {iteration + 1}" if iteration < MAX_ITERATIONS else "")
            )

            # ── Convergence / stall check ──────────────────────────────────────
            # Append this round's actionable count and check for stall.
            # A stall is defined as two consecutive rounds with no improvement
            # (count[N] >= count[N-1]).  A single flat round is possible due to
            # blast-radius rollbacks that preserved the count while preventing
            # regressions — we require two consecutive flat/worsening rounds
            # before escalating to avoid false positives.
            _round_failing_counts.append(remaining_count)
            if (
                len(_round_failing_counts) >= 3
                and _round_failing_counts[-1] >= _round_failing_counts[-2] >= _round_failing_counts[-3]
            ):
                _stall_detected = True
                _err(
                    f"STALL DETECTED after {iter_label}: actionable failing count has "
                    f"not decreased for 3 consecutive rounds "
                    f"({_round_failing_counts[-3]} → {_round_failing_counts[-2]} → "
                    f"{_round_failing_counts[-1]}) — "
                    "continuing will not converge; stopping early."
                )
                _warn(
                    "The agent is making no measurable progress.  Unlike oscillation "
                    "(same files cycling), this is a plateau — different files may be "
                    "failing each round but none are getting fixed.  Likely causes:\n"
                    "    1. Blast-radius conflicts blocking writes (check BLAST-RADIUS "
                    "ROLLBACK entries in the build log)\n"
                    "    2. Specs that require runtime state unavailable at test time\n"
                    "    3. Too many inter-dependent files in this milestone's scope\n"
                    "  Review the handoff summary and adjust the spec or split the "
                    "milestone before retrying."
                )
                log.detail(
                    f"STALL: round counts = {_round_failing_counts}; "
                    f"stopping at {iter_label}"
                )
                break

        if all_pass:
            print(f"\n  {C_BOLD}{C_GREEN}✔  All tests pass{C_RESET}\n")
            # ── Golden baseline certificate ────────────────────────────────────
            # Now that all tests pass, record the complete set of passing test
            # files in the progress file as a "golden baseline" for this
            # milestone.  Future S4 sessions (even in different [a] presses or
            # different days) will use this to detect cross-session regressions
            # — any test in the golden set must remain passing forever.
            _write_golden_baseline(wname, active_milestone, full_output)
            # Record "resolved" lesson for every file that was in _baseline_failing
            # and is now passing, so future sessions know these were fixed this way.
            for tf in sorted(_promoted_to_passing):
                _append_lesson(
                    wname, active_milestone, tf,
                    failure_class=_classify_failure(""),
                    outcome="resolved",
                    detail="promoted to passing in this S4 session",
                )
            # Reset the [a] press counter for this milestone/step so it starts
            # fresh if the operator returns to this step later.
            import json as _json
            _press_file = TRACKING_DIR / f"{wname}.press-counter.json"
            try:
                _pdata: dict = _json.loads(_press_file.read_text()) if _press_file.exists() else {}
                _pdata.pop(f"{active_milestone}-S4", None)
                _press_file.write_text(_json.dumps(_pdata, indent=2))
            except Exception:
                pass
        else:
            # ── Record lessons for this session's failures ─────────────────────
            # Persist compact records so future S4 sessions for this milestone
            # know which approaches were attempted and what the outcome was.
            # This is the mechanism that gives the build system cross-session
            # memory without requiring any external store — just a JSONL sidecar.
            for tf in sorted(_abandoned_files):
                fc = _classify_failure(
                    _baseline_output  # best available failure text at session close
                )
                _append_lesson(
                    wname, active_milestone, tf, fc, "abandoned",
                    detail=f"Hit {MAX_FILE_ATTEMPTS}-attempt limit without passing",
                )
            if _oscillation_detected:
                for tf in sorted(current_fingerprint):
                    _append_lesson(
                        wname, active_milestone, tf, "logic", "oscillation",
                        detail="Loop detected same failing set in two separate rounds",
                    )
            if _stall_detected:
                for tf in sorted(actionable_failing):
                    _append_lesson(
                        wname, active_milestone, tf, "logic", "stalled",
                        detail=f"No progress for 3 rounds: {_round_failing_counts}",
                    )

            # ── Classified failure report ──────────────────────────────────────
            # Distinguish pre-existing failures (S4 didn't make them worse) from
            # regressions (S4 broke something that was passing) and env-skips
            # (tests that require tooling unavailable in this environment).
            # This is critical for operator triage — they need to know whether
            # pressing [a] again might help or whether manual intervention is needed.
            remaining_raw = set(_collect_failing_test_files(full_output))
            pre_existing  = remaining_raw & _baseline_failing - _env_skip_files
            regressions   = remaining_raw - _baseline_failing - _env_skip_files
            env_skips     = _env_skip_files  # collected during inner loop

            rounds_str = f"{MAX_ITERATIONS} round(s) × {PER_FILE_RETRIES + 1} attempt(s)/file"
            print()
            print(f"  {C_BOLD}S4 completed — {rounds_str}{C_RESET}")

            if not remaining_raw and not env_skips:
                print(f"  {C_GREEN}All tests resolved{C_RESET}")
            else:
                if pre_existing:
                    print(
                        f"\n  {C_YELLOW}Pre-existing failures (not caused by this run "
                        f"— press [a] to retry):{C_RESET}"
                    )
                    for tf in sorted(pre_existing):
                        print(f"     {C_YELLOW}○{C_RESET}  {Path(tf).name}")

                if regressions:
                    print(
                        f"\n  {C_RED}REGRESSIONS (tests broken by this run "
                        f"— writes have been rolled back):{C_RESET}"
                    )
                    for tf in sorted(regressions):
                        print(f"     {C_RED}✖{C_RESET}  {Path(tf).name}")
                    print(
                        f"  {C_DIM}These tests were passing before S4 started. "
                        f"The rollback restored files to their pre-round state. "
                        f"Investigate manually or add the broken files to "
                        f"_ACCUMULATOR_FILES if they are shared infrastructure.{C_RESET}"
                    )

                if env_skips:
                    print(
                        f"\n  {C_DIM}Environment-skipped (require tooling not available "
                        f"here — cannot be fixed without installing the tool):{C_RESET}"
                    )
                    for tf in sorted(env_skips):
                        print(f"     {C_DIM}⊘{C_RESET}  {Path(tf).name}")

                if _abandoned_files:
                    print(
                        f"\n  {C_RED}Abandoned after {MAX_FILE_ATTEMPTS} attempts "
                        f"(manual review required):{C_RESET}"
                    )
                    for tf in sorted(_abandoned_files):
                        print(f"     {C_RED}∅{C_RESET}  {Path(tf).name}")
                    print(
                        f"  {C_DIM}These tests consumed {MAX_FILE_ATTEMPTS} LLM attempts "
                        "without converging.  Likely causes:\n"
                        "    • The acceptance criterion is untestable as written\n"
                        "    • A shared module has an incompatible interface change\n"
                        "    • A blast-radius conflict the LLM could not resolve narrowly\n"
                        "  Review the spec AC and the test assertions before retrying."
                        f"{C_RESET}"
                    )

            # ── Human handoff recommendation ───────────────────────────────────
            # Give the operator a clear, unambiguous next action rather than
            # leaving them to guess whether pressing [a] will help.
            # The recommendation is derived from which failure categories are
            # present and how many consecutive [a] presses have been made.
            import json as _json
            _press_file = TRACKING_DIR / f"{wname}.press-counter.json"
            try:
                _press_data: dict = _json.loads(_press_file.read_text()) if _press_file.exists() else {}
            except Exception:
                _press_data = {}
            _press_key = f"{active_milestone}-S4"
            _press_count: int = _press_data.get(_press_key, 0) + 1
            _press_data[_press_key] = _press_count
            _press_file.write_text(_json.dumps(_press_data, indent=2))

            print(f"\n  {C_BOLD}── Recommended next action ──{C_RESET}")
            if _stall_detected:
                print(
                    f"  {C_RED}DO NOT PRESS [a] — STALL DETECTED{C_RESET}\n"
                    f"  {C_DIM}Actionable failing count: {_round_failing_counts}\n"
                    "  No progress for 3 consecutive rounds — more LLM calls will not converge.\n"
                    "  Root causes to investigate:\n"
                    "    1. Blast-radius rollbacks blocking every write attempt\n"
                    "       (check BLAST-RADIUS ROLLBACK entries in the build log)\n"
                    "    2. Milestone scope too broad — split into smaller milestones\n"
                    "    3. Spec ACs that require runtime state unavailable at test time\n"
                    "    4. Abandoned files blocking dependencies of other failing tests\n"
                    f"  Round counts: {_round_failing_counts}{C_RESET}"
                )
            elif _oscillation_detected:
                print(
                    f"  {C_RED}DO NOT PRESS [a] — OSCILLATION DETECTED{C_RESET}\n"
                    f"  {C_DIM}The agent cycled between the same failure states across rounds.\n"
                    "  Pressing [a] again will immediately re-detect oscillation and stop.\n"
                    "  Root causes to investigate:\n"
                    "    1. A broken symbol in an accumulator file that now gets updated\n"
                    "       (check [accumulator: no new symbols found] lines in the log)\n"
                    "    2. Tests whose assertions don't match the spec — review the AC\n"
                    "    3. A missing fixture or conftest entry needed by the failing tests\n"
                    "  Fix the root cause manually, then press [a].{C_RESET}"
                )
            elif regressions:
                print(
                    f"  {C_RED}MANUAL INVESTIGATION REQUIRED{C_RESET}\n"
                    f"  {C_DIM}Regressions were detected and rolled back.  Do NOT press [a] "
                    "again — it will repeat the same regressing writes.\n"
                    "  Steps:\n"
                    "    1. Review the rolled-back files in the write journal\n"
                    "    2. Add shared infrastructure files to _ACCUMULATOR_FILES if missing\n"
                    "    3. Manually fix the regression, then press [a]{C_RESET}"
                )
            elif all(f in _env_skip_files for f in (remaining_raw or set())):
                print(
                    f"  {C_YELLOW}INSTALL REQUIRED TOOLING{C_RESET}\n"
                    f"  {C_DIM}All remaining failures require environment tooling "
                    "(npm, docker, redis …).  "
                    "Install the tool(s) listed above, then press [a].{C_RESET}"
                )
            elif _press_count >= 3 and pre_existing:
                print(
                    f"  {C_YELLOW}SPEC REVIEW RECOMMENDED{C_RESET}\n"
                    f"  {C_DIM}The same failures have persisted for {_press_count} consecutive "
                    "[a] presses.  The tests may be testing behaviour the spec doesn't "
                    "fully define, or the acceptance criteria may be untestable as written.\n"
                    "  Steps:\n"
                    "    1. Review the failing tests against the workplan ACs\n"
                    "    2. Clarify or strengthen the ACs in the workplan\n"
                    "    3. Re-run [d] to refresh distilled context\n"
                    f"    4. Press [a] again{C_RESET}"
                )
            elif pre_existing:
                print(
                    f"  {C_GREEN}Press [a] to continue{C_RESET}\n"
                    f"  {C_DIM}Pre-existing failures only — no regressions.  "
                    f"({_press_count} attempt(s) so far){C_RESET}"
                )
            else:
                print(f"  {C_GREEN}Press [a] to continue{C_RESET}")

            print(f"\n  {C_DIM}Details: {log.path.name}{C_RESET}\n")

        _s4_tests_passed = all_pass

    elif step_id == "S2":
        # ── S2 INTERFACE: single call, no tests ──────────────────────────────
        label_short = step_label.split(" -- ")[0] if " -- " in step_label else step_label
        try:
            with Spinner(f"{step_id} {label_short}  [{active_milestone}]"):
                response = call_claude(
                    system=system_prompt,
                    messages=[{"role": "user", "content": _build_user_content()}],
                    max_tokens=8192,
                )
        except RuntimeError as exc:
            _err(f"API call failed: {exc}")
            return

        narrative = re.sub(r"<<<FILE:.*?<<<END_FILE>>>", "", response, flags=re.DOTALL).strip()
        if narrative:
            print()
            print(narrative)

        file_blocks = _extract_files(response)
        if file_blocks:
            print()
            print(f"  {C_BOLD}Writing {len(file_blocks)} file(s){C_RESET}")
            for rel_path, content in file_blocks:
                rel_path, content, warn = _validate_and_redirect(rel_path, content)
                if warn:
                    _warn(f"  {warn}")
                if rel_path is None:    # protected — skip entirely
                    continue
                dest = PROJECT_ROOT / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                _ok(f"{rel_path}  ({len(content.splitlines())} lines)")
                written_paths.append(rel_path)

        if written_paths and wp.progress_file.exists():
            fps = store_contract_fingerprints(wp.progress_file, active_milestone)
            if fps:
                _ok(f"Interface fingerprints stored: {len(fps)} file(s)")

        ast_ok, missing = run_contract_completeness_check(written_paths, distilled_ctx or "")
        if not ast_ok and missing:
            _warn(f"Contract completeness: {len(missing)} method(s) missing:")
            for name in missing:
                _warn(f"  {name}()")

    else:
        # ── S8: gate on acceptance criteria before narrative review ────────
        if step_id == "S8":
            wp_path_s8 = find_workplan_file(wname)
            criteria_s8 = _parse_acceptance_criteria(
                wp_path_s8, active_milestone
            ) if wp_path_s8 else []
            if criteria_s8:
                print()
                print(f"  {C_BOLD}Acceptance criteria checklist for {active_milestone}:{C_RESET}")
                for i, c in enumerate(criteria_s8, 1):
                    print(f"    {i}. {c}")
                print()
                answer = input(
                    f"  {C_YELLOW}Are ALL {len(criteria_s8)} criteria demonstrably met? [y/N]{C_RESET} "
                ).strip().lower()
                if answer != "y":
                    _warn("S8 blocked — return to S4/S5/S6 until all criteria are met.")
                    return

        # ── S1, S5, S6, S8: single call, narrative only ───────────────────────
        label_short = step_label.split(" -- ")[0] if " -- " in step_label else step_label
        try:
            with Spinner(f"{step_id} {label_short}  [{active_milestone}]"):
                response = call_claude(
                    system=system_prompt,
                    messages=[{"role": "user", "content": _build_user_content()}],
                    max_tokens=8192,
                )
        except RuntimeError as exc:
            _err(f"API call failed: {exc}")
            return

        narrative = re.sub(r"<<<FILE:.*?<<<END_FILE>>>", "", response, flags=re.DOTALL).strip()
        if narrative:
            print()
            print(narrative)

        file_blocks = _extract_files(response)
        if file_blocks:
            print()
            print(f"  {C_BOLD}Writing {len(file_blocks)} file(s){C_RESET}")
            for rel_path, content in file_blocks:
                rel_path, content, warn = _validate_and_redirect(rel_path, content)
                if warn:
                    _warn(f"  {warn}")
                if rel_path is None:    # protected — skip entirely
                    continue
                dest = PROJECT_ROOT / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                _ok(f"{rel_path}  ({len(content.splitlines())} lines)")
                written_paths.append(rel_path)

    # ── OUTCOME PANEL ─────────────────────────────────────────────────────────
    print()
    print(f"  {C_BOLD}{C_CYAN}{'─' * w}{C_RESET}")
    print(f"  {C_BOLD}  OUTCOME{C_RESET}")
    print(f"  {C_BOLD}{C_CYAN}{'─' * w}{C_RESET}")
    if written_paths:
        print(f"  Files written  : {len(written_paths)}")
        for p in written_paths:
            print(f"    {C_DIM}+{C_RESET} {p}")
    else:
        print(f"  Files written  : 0  (non-file step)")

    cmds = _extract_next_commands(response)
    if cmds:
        print(f"  Next commands  :")
        bin_dir = VENV_PYTHON.parent
        for cmd in cmds:
            venv_note = ""
            exe = cmd.split()[0] if cmd.split() else ""
            if exe and (bin_dir / exe).exists():
                venv_note = f"  {C_DIM}(venv){C_RESET}"
            print(f"    {C_CYAN}${C_RESET} {cmd}{venv_note}")
    print(f"  {C_BOLD}{C_CYAN}{'─' * w}{C_RESET}")
    print()

    # ── Mark complete and advance ─────────────────────────────────────────────
    if wp.progress_file.exists():
        if step_id == "S3":
            if written_paths:
                next_step = advance_progress_step(wp.progress_file, active_milestone, step_id)
                if next_step:
                    _ok(f"S3 DONE  →  next: {C_BOLD}{next_step}{C_RESET}")
                action_auto_commit(active_milestone, step_id, step_label)
            else:
                _warn("No test files written — S3 not marked complete")
        elif step_id in ("S4", "S7"):
            # Use the result already captured by the S4 loop above.
            # Do NOT re-run pytest — that causes contradictory results.
            tests_ok = _s4_tests_passed
            if tests_ok is None:
                # Fallback: S4 loop didn't run (e.g. tests were already passing)
                tests_ok, _ = run_tests_capture()
            if tests_ok:
                next_step = advance_progress_step(wp.progress_file, active_milestone, step_id)
                if next_step:
                    _ok(f"Tests pass — {step_id} DONE  →  next: {C_BOLD}{next_step}{C_RESET}")
                else:
                    _ok(f"Tests pass — {active_milestone} complete")
                if written_paths:
                    action_auto_commit(active_milestone, step_id, step_label)
            else:
                _warn(f"Tests still failing — {step_id} NOT marked complete")
                _warn("Run [a] again to continue tackling remaining failures")
        else:
            # Non-test steps: explicit prompt
            answer = input(
                f"  {C_YELLOW}Mark {C_BOLD}{step_id}{C_YELLOW} ({step_label}) "
                f"DONE and advance to next step? [Y/n]{C_RESET} "
            ).strip().lower()
            if answer != "n":
                next_step = advance_progress_step(wp.progress_file, active_milestone, step_id)
                if next_step:
                    next_label = next((lbl for sid, lbl in STEP_LABELS if sid == next_step), next_step)
                    _ok(f"{step_id} DONE  →  next: {C_BOLD}{next_step}{C_RESET} {next_label}")
                    _info("Run [a] again to execute the next step")
                else:
                    _ok(f"{active_milestone} fully complete — all steps DONE")
                if written_paths:
                    action_auto_commit(active_milestone, step_id, step_label)
            else:
                _info(f"{step_id} not marked complete — run [a] again when ready")

# ---------------------------------------------------------------------------
# Other build actions
# ---------------------------------------------------------------------------

def action_repair_progress(all_wt: list[WorkplanTracking]) -> None:
    """
    Scan the active workplan's progress file for lines where the bracket
    expression was eaten by the old buggy advance_progress_step regex, then
    repair them from the STEP_LABELS template.

    A corrupted line looks like:
       UNDERSTAND -- review spec                               DONE
    instead of:
       [M0-S1] UNDERSTAND -- review spec                      DONE

    Also repairs any header/step-line sync issues.
    """
    _h2("Repair progress file")
    active_wt = resolve_active_workplan(all_wt)
    if not active_wt or not active_wt.progress:
        _warn("No active workplan with a progress file.")
        return

    wp = active_wt.progress
    path = wp.progress_file
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    repaired_lines = []
    repairs = 0

    # Build a lookup: step label text -> (milestone_id, step_id)
    # We need to match orphaned label lines back to their step IDs
    label_to_sid: dict[str, tuple[str,str]] = {}
    for mid, _ in MILESTONE_LIST:
        for sid, slabel in STEP_LABELS:
            label_to_sid[slabel.lower()] = (mid, sid)

    status_re  = re.compile(r"(DONE|IN_PROGRESS|NOT_STARTED|BLOCKED|SKIPPED)$", re.IGNORECASE)
    bracket_re = re.compile(r"^\s+\[M\d+", re.IGNORECASE)

    prev_mid = "M0"
    for line in lines:
        # Track current milestone from milestone-level lines
        mm = re.match(r"^\[(?P<mid>M\d+)\]", line)
        if mm:
            prev_mid = mm.group("mid")
            repaired_lines.append(line)
            continue

        # Detect a corrupted step line: indented, ends with a status word,
        # does NOT start with a bracket
        stripped = line.strip()
        sm = status_re.search(stripped)
        if sm and stripped and not bracket_re.match(line) and len(stripped) > 10:
            status_word = sm.group(1)
            label_text  = stripped[: stripped.rfind(status_word)].strip()
            key = label_text.lower()
            # Try to find which step this label belongs to
            if key in label_to_sid:
                _, sid = label_to_sid[key]
                # Reconstruct the correct line
                fixed = f"  [{prev_mid}-{sid}] {label_text:<52s}  {status_word}"
                repaired_lines.append(fixed)
                repairs += 1
                _ok(f"Repaired: {prev_mid}-{sid} ({status_word})")
                continue

        repaired_lines.append(line)

    if repairs == 0:
        _ok("No corrupted lines found — progress file looks clean.")
        return

    path.write_text("\n".join(repaired_lines) + "\n", encoding="utf-8")
    _ok(f"Repaired {repairs} line(s). Progress file updated.")
    _info("Run [a] — the step table should now show correct statuses.")


def action_pip_install() -> None:
    """Force-reinstall all dev tool dependencies (runs automatically when missing)."""
    _h2("Installing dev tools")
    _info(f"Packages: {', '.join(DEV_PACKAGES)}")
    ok = _ensure_dev_tools(quiet=False)
    if ok:
        _ok("All dev tools installed. Readiness panel will update on next menu render.")
    else:
        _err("Install failed — check output above and verify network/venv.")


def action_run_tests() -> None:
    _h2("Test suite (pytest + coverage)")
    _run(
        [str(VENV_PYTHON), "-m", "pytest",
         "tests/", "--tb=short", "--cov=.", "--cov-report=term-missing", "-q"],
        check=False,
    )


def action_quality_gate(
    all_wt: Optional[list[WorkplanTracking]] = None,
    auto_advance: bool = False,
) -> bool:
    """
    Run format -> lint -> type-check -> tests.

    If all_wt is provided and auto_advance=True (improvement #4/#6):
      - On PASS: auto-advances the active progress step to DONE and offers commit.

    Returns True if all gates passed.
    """
    _h2("Quality gate: format -> lint -> type-check -> tests")
    bin_dir = VENV_PYTHON.parent
    gates = [
        ([str(bin_dir / "black"), "--check", "."],          "Format check (black)"),
        ([str(bin_dir / "ruff"),  "check", "."],             "Lint (ruff)"),
        ([str(bin_dir / "mypy"),  ".",
          "--ignore-missing-imports"],                        "Type check (mypy)"),
        ([str(VENV_PYTHON), "-m", "pytest",
          "tests/", "-q", "--tb=short"],                     "Tests (pytest)"),
    ]
    all_ok = True
    for cmd, label in gates:
        if not Path(cmd[0]).exists():
            _warn(f"{label}: {cmd[0]} not found in .venv -- skipping")
            continue
        _info(f"Running: {label}")
        r = _run(cmd, check=False)
        (_ok if r.returncode == 0 else _err)(
            label + ("" if r.returncode == 0 else f" FAILED (exit {r.returncode})")
        )
        if r.returncode != 0:
            all_ok = False
    print()
    (_ok if all_ok else _warn)("Quality gate " + ("PASSED" if all_ok else "has failures"))

    # Improvement #4/#6: on clean pass, offer to advance progress and commit
    if all_ok and all_wt is not None:
        active_wt = resolve_active_workplan(all_wt)
        if active_wt and active_wt.progress and active_wt.progress.progress_file.exists():
            wp       = active_wt.progress
            step_id  = _step_id_from_detail(wp.resume_detail)
            if step_id == "S5":  # quality gate IS step S5
                next_s = advance_progress_step(
                    wp.progress_file, wp.active_milestone, "S5"
                )
                if next_s:
                    _ok(f"Progress: S5 DONE -> {next_s}")
            step_label = next((lbl for sid, lbl in STEP_LABELS if sid == step_id), step_id)
            action_auto_commit(wp.active_milestone, step_id, step_label)

    return all_ok


def action_docker_up() -> None:
    _h2("Docker Compose up")
    for p in (PROJECT_ROOT / "infra" / "compose" / "docker-compose.yml",
              PROJECT_ROOT / "docker-compose.yml"):
        if p.exists():
            _run(["docker", "compose", "-f", str(p), "up", "-d"], check=False)
            return
    _warn("No docker-compose.yml found.")


def action_docker_down() -> None:
    _h2("Docker Compose down")
    for p in (PROJECT_ROOT / "infra" / "compose" / "docker-compose.yml",
              PROJECT_ROOT / "docker-compose.yml"):
        if p.exists():
            _run(["docker", "compose", "-f", str(p), "down"], check=False)
            return
    _warn("No docker-compose.yml found.")


def action_run_migrations() -> None:
    _h2("Alembic migrations")
    alembic = VENV_PYTHON.parent / "alembic"
    if not alembic.exists():
        _warn("alembic not found in .venv -- install it first.")
        return
    if not (PROJECT_ROOT / "alembic.ini").exists():
        _warn("alembic.ini not found at project root.")
        return
    _run([str(alembic), "upgrade", "head"], check=False)


def action_show_progress(all_wt: list[WorkplanTracking]) -> None:
    if not all_wt:
        _warn("No tracking files found.")
        return
    for wt in all_wt:
        _h2(wt.workplan_name)
        if wt.progress:
            for e in wt.progress.entries:
                note = f"  <- {e.blocking_issue}" if e.blocking_issue else ""
                print(f"  [{e.milestone_id:3s}] {e.label:<50s} {_col(e.status)}{note}")


def action_show_issues(all_wt: list[WorkplanTracking]) -> None:
    shown = False
    for wt in all_wt:
        open_iss = [i for i in wt.issues if i.status.upper() != "RESOLVED"]
        if open_iss:
            _h2(f"Open issues -- {wt.workplan_name}")
            for iss in open_iss:
                print(f"  {C_BOLD}{iss.number}{C_RESET} [{_col(iss.status)}] {iss.title}")
                if iss.symptoms:
                    _info(iss.symptoms[:120])
                if iss.fix and iss.fix.lower() not in ("tbd", "-", ""):
                    _info(f"Fix: {iss.fix[:100]}")
            shown = True
    if not shown:
        _ok("No open issues.")


def action_show_lessons(all_wt: list[WorkplanTracking]) -> None:
    for wt in all_wt:
        if wt.lessons:
            _h2(f"Lessons -- {wt.workplan_name}")
            for ll in wt.lessons:
                print(f"  {C_BOLD}{ll.number}{C_RESET}  {C_CYAN}{ll.title}{C_RESET}")
                _info(ll.lesson[:120])
    shared = _parse_lessons(SHARED_LESSONS)
    if shared:
        _h2("Shared lessons (all phases)")
        for ll in shared:
            print(f"  {C_BOLD}{ll.number}{C_RESET}  {C_CYAN}{ll.title}{C_RESET}")
            _info(ll.lesson[:120])


MILESTONE_LIST = [
    ("M0",  "Bootstrap"),
    ("M1",  "Docker Runtime"),
    ("M2",  "DB Schema + Migrations + Audit Ledger"),
    ("M3",  "Auth + RBAC"),
    ("M4",  "Jobs + Queue Classes + Compute Policy"),
    ("M5",  "Artifact Registry + Storage Abstraction"),
    ("M6",  "Feed Registry + Versioned Config + Connectivity Tests"),
    ("M7",  "Ingest Pipeline"),
    ("M8",  "Verification + Gaps + Anomalies + Certification"),
    ("M9",  "Symbol Lineage"),
    ("M10", "Parity Service"),
    ("M11", "Alerting + Observability Hardening"),
    ("M12", "Operator API Docs + Acceptance Pack"),
]
STEP_LABELS = [
    ("S1", "UNDERSTAND -- review spec"),
    ("S2", "INTERFACE FIRST -- define contracts"),
    ("S3", "RED -- write failing tests"),
    ("S4", "GREEN -- implement"),
    ("S5", "QUALITY GATE -- format/lint/type/coverage"),
    ("S6", "REFACTOR"),
    ("S7", "INTEGRATION -- integration tests"),
    ("S8", "REVIEW -- checklist sign-off"),
]


def _bootstrap_one(wname: str) -> None:
    """Create skeleton .progress, .issues, and .lessons-learned for one workplan stem."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)

    pp = TRACKING_DIR / f"{wname}.progress"
    if not pp.exists():
        lines = [
            f"# Progress: {wname.replace('_', ' ')}",
            f"# Workplan: {wname}.md",
            f"# Last updated: {now}",
            "# Active milestone: M0",
            "# Active step: STEP 1 -- UNDERSTAND (begin M0 Bootstrap)",
            "",
        ]
        for mid, label in MILESTONE_LIST:
            lines.append(f"[{mid}] {label:<58s}  NOT_STARTED")
            for sid, slabel in STEP_LABELS:
                lines.append(f"  [{mid}-{sid}] {slabel:<52s}  NOT_STARTED")
        pp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _ok(f"Created {pp.name}")
    else:
        _info(f"{pp.name} already exists -- skipped")

    ip = TRACKING_DIR / f"{wname}.issues"
    if not ip.exists():
        ip.write_text(
            f"# Issues: {wname.replace('_', ' ')}\n"
            f"# Workplan: {wname}.md\n"
            f"# Last updated: {now}\n\n"
            "# Status: IDENTIFIED | WORKING | RESOLVED\n\n"
            "---\n# ISS-001\n# Title:      <description>\n"
            "# Status:     IDENTIFIED\n# Milestone:  MX\n"
            "# Discovered: <ISO-8601>\n# Resolved:   --\n"
            "# Symptoms:   <what you observed>\n"
            "# Root cause: <investigation findings>\n"
            "# Fix:        TBD\n# Lesson:     --\n",
            encoding="utf-8",
        )
        _ok(f"Created {ip.name}")
    else:
        _info(f"{ip.name} already exists -- skipped")

    lp = TRACKING_DIR / f"{wname}.lessons-learned"
    if not lp.exists():
        lp.write_text(
            f"# Lessons Learned: {wname.replace('_', ' ')}\n"
            f"# Workplan: {wname}.md\n"
            f"# Last updated: {now}\n\n"
            "---\n# LL-001\n# Title:     <pattern-level title>\n"
            "# Milestone: MX\n# Source:    ISS-NNN\n"
            "# Lesson:    <broadly applicable lesson>\n"
            "# Apply to:  <milestones/phases>\n",
            encoding="utf-8",
        )
        _ok(f"Created {lp.name}")
    else:
        _info(f"{lp.name} already exists -- skipped")


def action_bootstrap() -> None:
    _h2("Bootstrapping tracking files")
    TRACKING_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Discover workplan files from SPEC_DIR (and project root as fallback)
    found = [
        p.stem for p in SPEC_DIR.rglob("*.md")
        if "workplan-tracking" not in str(p)
           and ("workplan" in p.stem.lower() or "plan" in p.stem.lower())
    ]
    if not found:
        found = [
            p.stem for p in PROJECT_ROOT.rglob("*workplan*.md")
            if "workplan-tracking" not in str(p)
        ]
    names = found or ["FXLab_Phase_1_workplan_v3"]

    for wname in names:
        _bootstrap_one(wname)

    if not SHARED_LESSONS.exists():
        SHARED_LESSONS.write_text(
            f"# FXLab Shared Lessons (cross-phase)\n"
            f"# Promote here when Apply-to spans 2+ phases.\n"
            f"# Last updated: {now}\n\n"
            "---\n# LL-S001\n# Title:     <shared lesson>\n"
            "# Milestone: <originating>\n# Source:    ISS-NNN\n"
            "# Lesson:    <lesson>\n# Apply to:  All phases\n",
            encoding="utf-8",
        )
        _ok(f"Created {SHARED_LESSONS.name}")
    else:
        _info(f"{SHARED_LESSONS.name} already exists -- skipped")


def action_show_env() -> None:
    _h2("Environment configuration")
    _info(f".env file:         {ENV_FILE}  ({'found' if ENV_FILE.exists() else 'NOT FOUND'})")
    ok, msg = validate_api_key()
    ((_ok if ok else _err))(f"ANTHROPIC_API_KEY: {msg}")
    _info(f"ANTHROPIC_MODEL:   {os.environ.get('ANTHROPIC_MODEL', DEFAULT_MODEL)} "
          f"{'(default)' if 'ANTHROPIC_MODEL' not in os.environ else '(from env)'}")
    _info(f"VENV_PYTHON:       {VENV_PYTHON}  "
          f"({'exists' if VENV_PYTHON.exists() else 'missing'})")


def action_open_shell() -> None:
    _h2("Activate venv")
    _info(f"Run:  source {VENV_ACTIVATE}")
    _info("(Cannot auto-activate in the parent shell -- copy the command above.)")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

MENU_ITEMS: list[tuple[str, str]] = [
    ("w",  "Workplan -- browse User Spec/ and select workplan + spec"),
    ("d",  "Distil -- generate/refresh per-milestone context from spec [AI]"),
    ("dv", "Distil debug -- diagnose why sections show as 0"),
    ("r",  "Resume -- continue from last saved position"),
    ("a",  "Agentic build -- drive next milestone step with Claude [AI]"),
    ("c",  "Claude brief -- AI session summary [AI]"),
    ("p",  "Show full progress summary"),
    ("i",  "Show all open issues"),
    ("l",  "Show all lessons learned"),
    ("b",  "Bootstrap / refresh tracking files"),
    ("pi", "Pip install -- force-reinstall dev tools (runs automatically when missing)"),
    ("fx", "Fix progress -- repair corrupted progress file"),
    ("rw", "Rollback -- revert files from last [a] run"),
    ("t",  "Run test suite"),
    ("q",  "Run quality gate (format + lint + type + tests)"),
    ("h",  "Handoff -- write session summary doc [AI]"),
    ("du", "Docker Compose up"),
    ("dd", "Docker Compose down"),
    ("m",  "Run database migrations (Alembic)"),
    ("e",  "Show environment / API key status"),
    ("sh", "Show venv activate command"),
    ("x",  "Exit"),
]



# ---------------------------------------------------------------------------
# Environment readiness  — checks all pre-conditions and drives the menu
# ---------------------------------------------------------------------------

@dataclass
class ReadinessCheck:
    """A single environment pre-condition with its fix action."""
    key:     str            # short ID
    label:   str            # what is being checked
    ok:      bool           # is it satisfied?
    detail:  str            # one-line status
    fix_key: str            # menu key that fixes this, or ""
    fix_hint: str           # human instruction if no menu key
    blocking: bool = True   # if True, [a] is gated on this


def run_readiness_checks(
    api_ok: bool,
    all_wt: list[WorkplanTracking],
) -> list[ReadinessCheck]:
    """
    Run all environment pre-condition checks and return results.
    Checks are ordered: fix them top-to-bottom.
    """
    checks: list[ReadinessCheck] = []
    sel    = load_active_selection()
    active = resolve_active_workplan(all_wt)

    # ── 1. Workplan selected ─────────────────────────────────────────────────
    if sel and sel.workplan_path and sel.workplan_path.exists():
        checks.append(ReadinessCheck(
            key="workplan", label="Workplan selected",
            ok=True, detail=sel.workplan_path.name,
            fix_key="", fix_hint="",
        ))
    else:
        checks.append(ReadinessCheck(
            key="workplan", label="Workplan selected",
            ok=False, detail="No workplan file chosen",
            fix_key="w", fix_hint='Press [w] to browse User Spec/ and select a workplan',
        ))

    # ── 2. Tracking files exist ──────────────────────────────────────────────
    if active and active.progress:
        checks.append(ReadinessCheck(
            key="tracking", label="Tracking files exist",
            ok=True, detail=f"{active.workplan_name}.progress found",
            fix_key="", fix_hint="",
        ))
    else:
        checks.append(ReadinessCheck(
            key="tracking", label="Tracking files exist",
            ok=False, detail="No .progress file — run [b] to bootstrap",
            fix_key="b", fix_hint='Press [b] to create tracking files',
        ))

    # ── 3. Context distilled ─────────────────────────────────────────────────
    if active:
        dp = distilled_file_path(active.workplan_name)
        if dp.exists():
            sections = list(_DISTIL_SECTION_RE.finditer(dp.read_text()))
            n = len(sections)
            ok = n >= 13
            checks.append(ReadinessCheck(
                key="distil", label="Context distilled",
                ok=ok,
                detail=f"{n}/13 milestones distilled" if not ok else f"All 13 milestones distilled",
                fix_key="d", fix_hint='Press [d] to generate per-milestone context',
                blocking=False,  # can still run [a] without distil, just less context
            ))
        else:
            checks.append(ReadinessCheck(
                key="distil", label="Context distilled",
                ok=False, detail="No distilled file — run [d] for token-efficient builds",
                fix_key="d", fix_hint='Press [d] to distil spec into per-milestone context',
                blocking=False,
            ))
    
    # ── 4. API key ───────────────────────────────────────────────────────────
    if api_ok:
        checks.append(ReadinessCheck(
            key="api", label="Anthropic API key",
            ok=True, detail="Key present and valid format",
            fix_key="", fix_hint="",
        ))
    else:
        checks.append(ReadinessCheck(
            key="api", label="Anthropic API key",
            ok=False, detail="Missing or malformed — AI features disabled",
            fix_key="e", fix_hint='Add ANTHROPIC_API_KEY=sk-ant-... to .env',
        ))

    # ── 5. Python dev tools — auto-install if missing ───────────────────────
    bin_dir = VENV_PYTHON.parent
    missing_bins = [t for t in DEV_BINARIES if not (bin_dir / t).exists()]
    pytest_ok = True
    if not missing_bins:
        r = subprocess.run(
            [str(VENV_PYTHON), "-m", "pytest", "--version"],
            capture_output=True,
        )
        pytest_ok = r.returncode == 0

    if missing_bins or not pytest_ok:
        # Auto-install immediately rather than surface a warning
        _info(f"Dev tools missing ({', '.join(missing_bins or ['pytest'])}) -- installing now ...")
        installed_ok = _ensure_dev_tools(quiet=False)
        # Re-check after install
        missing_bins = [t for t in DEV_BINARIES if not (bin_dir / t).exists()]
        if not missing_bins:
            r = subprocess.run(
                [str(VENV_PYTHON), "-m", "pytest", "--version"],
                capture_output=True,
            )
            pytest_ok = r.returncode == 0

    if not missing_bins and pytest_ok:
        checks.append(ReadinessCheck(
            key="tools", label="Dev tools installed",
            ok=True, detail="pytest, black, ruff, mypy present",
            fix_key="", fix_hint="",
        ))
    else:
        # Install failed — surface for manual intervention
        still_missing = missing_bins or (["pytest"] if not pytest_ok else [])
        checks.append(ReadinessCheck(
            key="tools", label="Dev tools installed",
            ok=False,
            detail=f"Auto-install failed. Missing: {', '.join(still_missing)}",
            fix_key="pi", fix_hint="Check network access and venv integrity",
        ))

    # ── 6. Git initialised ───────────────────────────────────────────────────
    git_dir = PROJECT_ROOT / ".git"
    if git_dir.exists():
        checks.append(ReadinessCheck(
            key="git", label="Git repository",
            ok=True, detail=".git directory found",
            fix_key="", fix_hint="",
            blocking=False,
        ))
    else:
        checks.append(ReadinessCheck(
            key="git", label="Git repository",
            ok=False, detail="Not a git repo — commits and diffs won't work",
            fix_key="", fix_hint="Run: git init && git add -A && git commit -m 'chore: initial commit'",
            blocking=False,
        ))

    # ── 7. Open blocking issues ──────────────────────────────────────────────
    if active:
        blocking_issues = [
            i for i in active.issues
            if i.status.upper() in ("IDENTIFIED", "WORKING")
        ]
        if blocking_issues:
            checks.append(ReadinessCheck(
                key="issues", label="Open issues",
                ok=False,
                detail=f"{len(blocking_issues)} open issue(s) — review before building",
                fix_key="i", fix_hint="Press [i] to review open issues",
                blocking=False,
            ))
        else:
            checks.append(ReadinessCheck(
                key="issues", label="Open issues",
                ok=True, detail="No open issues",
                fix_key="", fix_hint="",
                blocking=False,
            ))

    return checks


def print_readiness_panel(checks: list[ReadinessCheck]) -> tuple[bool, bool]:
    """Show only failures. Passing state is a single quiet line."""
    blocking_ok = all(c.ok for c in checks if c.blocking)
    any_warn    = any(not c.ok for c in checks if not c.blocking)
    failures    = [c for c in checks if not c.ok and c.blocking]
    warnings    = [c for c in checks if not c.ok and not c.blocking]
    n_pass      = sum(1 for c in checks if c.ok)

    if failures:
        for ch in failures:
            print(f"  {C_RED}✖{C_RESET}  {C_BOLD}{ch.label}{C_RESET}: {ch.detail}")
            if ch.fix_key:
                print(f"     {C_YELLOW}→ press [{ch.fix_key}]{C_RESET}  {ch.fix_hint}")
            elif ch.fix_hint:
                print(f"     {C_YELLOW}→ {ch.fix_hint}{C_RESET}")
        print()
    else:
        warn_note = ""
        if warnings:
            warn_note = f"  {C_YELLOW}[!] {', '.join(c.label for c in warnings)}{C_RESET}"
        print(f"  {C_GREEN}✔{C_RESET}  {C_DIM}Ready  ({n_pass} checks){C_RESET}{warn_note}")
        print()

    return blocking_ok, any_warn


def print_menu(
    resume: Optional[tuple[str, str, str]],
    api_ok: bool,
    all_wt: list[WorkplanTracking],
) -> tuple[bool, list[ReadinessCheck]]:
    """
    Print the full menu and return (build_ready, checks) so the main
    loop can gate [a] without re-running the checks.
    """
    _h1("FXLab Build Menu")

    # ── Readiness panel ───────────────────────────────────────────────────────
    checks    = run_readiness_checks(api_ok, all_wt)
    build_ok, _ = print_readiness_panel(checks)

    # ── Menu items ────────────────────────────────────────────────────────────
    sel = load_active_selection()
    for key, label in MENU_ITEMS:
        prefix = f"  {C_BOLD}[{key:>2s}]{C_RESET}"

        if key == "a":
            if build_ok:
                step_hint = ""
                if resume:
                    _, milestone, detail = resume
                    step_hint = f"  {C_GREEN}← {milestone}: {detail[:38]}{C_RESET}"
                print(f"{prefix}  {label}{step_hint}")
            else:
                # Dim and note which check to fix first
                first_fail = next((c for c in checks if not c.ok and c.blocking), None)
                block_note = f"  {C_RED}← fix [{first_fail.fix_key}] first{C_RESET}" if first_fail and first_fail.fix_key else ""
                print(f"{prefix}  {C_DIM}{label}{C_RESET}{block_note}")

        elif key == "w":
            if sel:
                wp_short   = sel.workplan_path.name if sel.workplan_path else sel.workplan_stem
                spec_short = sel.spec_path.name if sel.spec_path else "no spec"
                hint = f"{wp_short} / {spec_short}"
            else:
                hint = "none selected"
            print(f"{prefix}  {label}  {C_DIM}({hint}){C_RESET}")

        elif key == "r":
            if resume:
                _, milestone, detail = resume
                hint = f"  {C_GREEN}<- {milestone}: {detail[:42]}{C_RESET}"
                print(f"{prefix}  {label}{hint}")
            else:
                print(f"{prefix}  {label}  {C_DIM}(nothing in progress){C_RESET}")

        elif "[AI]" in label:
            api_tag = f" {C_GREEN}[API OK]{C_RESET}" if api_ok else f" {C_RED}[API MISSING]{C_RESET}"
            clean   = label.replace("[AI]", "").rstrip()
            print(f"{prefix}  {clean}{api_tag}")

        else:
            print(f"{prefix}  {label}")

    print()
    return build_ok, checks


def handle_choice(
    choice: str,
    resume: Optional[tuple[str, str, str]],
    all_wt: list[WorkplanTracking],
    api_ok: bool,
    build_ok: bool = True,
) -> bool:
    """Return True to keep looping, False to exit."""
    c = choice.strip().lower()

    def _need_api() -> bool:
        if not api_ok:
            _err("ANTHROPIC_API_KEY is not set or invalid.")
            _err("Add it to .env at the project root and restart build.py.")
            return False
        return True

    def _need_ready() -> bool:
        if not build_ok:
            _err("Environment is not ready for building.")
            _err("Fix the blocking checks shown in the readiness panel first.")
            return False
        return True

    if c == "w":
        action_select_workplan(all_wt)
        # Resume hint is refreshed by the main loop's discover_tracking() call
    elif c == "d":
        if _need_api():
            action_distil(all_wt)
    elif c == "dv":
        action_distil_debug(all_wt)
    elif c == "r":
        if resume:
            _, milestone, detail = resume
            _h2(f"Resume: {milestone}")
            _info(f"Next step: {detail}")
            _info("Use [a] to have Claude drive the implementation.")
        else:
            _ok("Nothing in progress. Mark a milestone IN_PROGRESS in the .progress file.")
    elif c == "a":
        if _need_ready() and _need_api():
            action_agentic_build(all_wt)
    elif c == "c":
        if _need_api():
            action_ai_brief(all_wt)
    elif c == "p":   action_show_progress(all_wt)
    elif c == "i":   action_show_issues(all_wt)
    elif c == "l":   action_show_lessons(all_wt)
    elif c == "b":   action_bootstrap()
    elif c == "pi":  action_pip_install()
    elif c == "fx":  action_repair_progress(all_wt)
    elif c == "rw":  action_rollback_last_run(all_wt)
    elif c == "t":   action_run_tests()
    elif c == "q":   action_quality_gate(all_wt=all_wt)
    elif c == "h":
        action_handoff(all_wt, api_ok)
    elif c == "du":  action_docker_up()
    elif c == "dd":  action_docker_down()
    elif c == "m":   action_run_migrations()
    elif c == "e":   action_show_env()
    elif c == "sh":  action_open_shell()
    elif c == "x":
        print(f"\n{C_DIM}Goodbye.{C_RESET}\n")
        return False
    else:
        _warn(f"Unknown choice: '{c}'")

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _self_check() -> None:
    """
    Structural integrity check run on every startup.
    Catches broken patches before they cause runtime errors mid-build.
    """
    import ast as _ast
    from collections import Counter as _Counter

    src  = Path(__file__).read_text(encoding="utf-8")
    tree = _ast.parse(src)

    REQUIRED = {
        "_targeted_implement":         (True,  15),
        "_merge_conftest":             (True,   5),
        "_validate_and_redirect":      (True,   5),
        "_collect_failing_test_files": (True,   3),
        "_extract_files":              (True,   3),
        "advance_progress_step":       (True,   8),
        "run_tests_capture":           (True,   5),
        "_ensure_dev_tools":           (True,   5),
        "_ensure_package_inits":       (False,  3),
        "action_agentic_build":        (False, 20),
    }
    REQUIRED_CONSTS = [
        "_CANONICAL_REDIRECTS", "_CANONICAL_PATHS",
        "_CONFTEST_MERGE_DIRS", "DEV_PACKAGES",
        "MILESTONE_LIST", "STEP_LABELS",
    ]

    errors = []
    fn_nodes = {n.name: n for n in _ast.walk(tree) if isinstance(n, _ast.FunctionDef)}

    for fn, (must_return, min_s) in REQUIRED.items():
        if fn not in fn_nodes:
            errors.append(f"{fn}() missing"); continue
        node = fn_nodes[fn]
        if len(node.body) < min_s:
            errors.append(f"{fn}() too short ({len(node.body)} < {min_s})")
        if must_return:
            last = node.body[-1]
            ok = isinstance(last, _ast.Return)
            if not ok and isinstance(last, _ast.If):
                def er(s): return bool(s) and isinstance(s[-1], _ast.Return)
                ok = er(last.body) and er(last.orelse)
            if not ok:
                errors.append(f"{fn}() missing return (ends {type(last).__name__} L{last.lineno})")

    ti = fn_nodes.get("_targeted_implement")
    if ti and not any(
        isinstance(n, _ast.Call) and getattr(n.func, "id", "") == "_extract_files"
        for n in _ast.walk(ti)
    ):
        errors.append("_extract_files not inside _targeted_implement (write loop orphaned)")

    top_consts = set()
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Assign) and n.col_offset == 0:
            for t in n.targets:
                if isinstance(t, _ast.Name):
                    top_consts.add(t.id)
        elif isinstance(n, _ast.AnnAssign) and n.col_offset == 0:
            if isinstance(n.target, _ast.Name):
                top_consts.add(n.target.id)
    for c in REQUIRED_CONSTS:
        if c not in top_consts:
            errors.append(f"module constant {c} missing")

    dupes = [k for k, v in _Counter(
        n.name for n in _ast.walk(tree)
        if isinstance(n, _ast.FunctionDef) and n.col_offset == 0
    ).items() if v > 1]
    if dupes:
        errors.append(f"duplicate functions: {dupes}")

    if errors:
        print(f"  {C_RED}build.py integrity check failed — download a fresh copy:{C_RESET}")
        for e in errors:
            print(f"    {C_RED}✖{C_RESET}  {e}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FXLab build menu -- venv, tracking, and agentic dev tasks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--no-brief", action="store_true",
                        help="Skip the AI session brief at startup.")
    parser.add_argument("--run", metavar="CHOICE",
                        help="Run one menu action non-interactively (e.g. --run t).")
    args = parser.parse_args()

    # Verify own structural integrity before doing anything
    _self_check()

    # Silent startup — only surface actual problems
    load_dotenv()
    api_ok, api_msg = validate_api_key()
    if not api_ok:
        _warn(f"API key: {api_msg}  →  add ANTHROPIC_API_KEY to .env")
    ensure_venv()
    _ensure_dev_tools(quiet=True)  # also calls _ensure_package_inits

    # 3. Discover tracking state
    all_wt = discover_tracking()
    resume = find_resume(all_wt)

    # 4. Session brief
    if not args.no_brief:
        if api_ok and all_wt:
            action_ai_brief(all_wt)
        else:
            print_plain_brief(all_wt)

    # 5. Non-interactive mode
    if args.run:
        handle_choice(args.run, resume, all_wt, api_ok)
        return

    # 6. Interactive menu loop
    while True:
        build_ok, _ = print_menu(resume, api_ok, all_wt)
        try:
            choice = input(f"{C_BOLD}Choice:{C_RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            print(f"{C_DIM}Interrupted.{C_RESET}")
            break
        if not handle_choice(choice, resume, all_wt, api_ok, build_ok):
            break
        # Refresh state each loop iteration
        all_wt = discover_tracking()
        resume = find_resume(all_wt)


if __name__ == "__main__":
    main()

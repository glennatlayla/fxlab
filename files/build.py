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
import ast
import hashlib
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
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
TRACKING_DIR = PROJECT_ROOT / "docs" / "workplan-tracking"
SHARED_LESSONS = TRACKING_DIR / "SHARED_LESSONS.md"
ACTIVE_WORKPLAN_FILE = TRACKING_DIR / ".active_workplan"  # persists as JSON
# User Spec dir: where workplan and software-spec .md files live.
# Checked in order; first match wins.
_SPEC_DIR_CANDIDATES = ["User Spec", "user_spec", "specs", "Specs", "docs"]
SPEC_DIR = next(
    (PROJECT_ROOT / d for d in _SPEC_DIR_CANDIDATES if (PROJECT_ROOT / d).is_dir()),
    PROJECT_ROOT,  # fallback: browse project root
)
ENV_FILE = PROJECT_ROOT / ".env"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_DEV = PROJECT_ROOT / "requirements-dev.txt"

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"  # override via .env ANTHROPIC_MODEL

if platform.system() == "Windows":
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
    VENV_ACTIVATE = VENV_DIR / "Scripts" / "activate.bat"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_PIP = VENV_DIR / "bin" / "pip"
    VENV_ACTIVATE = VENV_DIR / "bin" / "activate"

USE_COLOUR = sys.stdout.isatty() and platform.system() != "Windows"

C_RESET = "\033[0m" if USE_COLOUR else ""
C_BOLD = "\033[1m" if USE_COLOUR else ""
C_DIM = "\033[2m" if USE_COLOUR else ""
C_RED = "\033[91m" if USE_COLOUR else ""
C_YELLOW = "\033[93m" if USE_COLOUR else ""
C_GREEN = "\033[92m" if USE_COLOUR else ""
C_CYAN = "\033[96m" if USE_COLOUR else ""
C_MAGENTA = "\033[95m" if USE_COLOUR else ""

# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------


def _h1(msg: str) -> None:
    w = 72
    print(f"\n{C_BOLD}{C_CYAN}{'=' * w}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}  {msg}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * w}{C_RESET}")


def _h2(msg: str) -> None:
    print(f"\n{C_BOLD}{C_MAGENTA}-- {msg} {C_RESET}")


def _ok(msg: str) -> None:
    print(f"  {C_GREEN}+{C_RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {C_YELLOW}!{C_RESET}  {msg}")


def _err(msg: str) -> None:
    print(f"  {C_RED}x{C_RESET}  {msg}")


def _info(msg: str) -> None:
    print(f"  {C_DIM}.{C_RESET}  {msg}")


def _sep() -> None:
    print(f"{C_DIM}{'-' * 72}{C_RESET}")


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
        key = key.strip()
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
        self._msg = msg
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        frames = itertools.cycle(["|", "/", "-", "\\"])
        while not self._stop.is_set():
            print(f"\r  {C_CYAN}{next(frames)}{C_RESET}  {self._msg} ...", end="", flush=True)
            time.sleep(0.12)
        print(f"\r{' ' * (len(self._msg) + 14)}\r", end="", flush=True)

    def __enter__(self) -> Spinner:
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
    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    payload = json.dumps(
        {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
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
            [
                str(VENV_PYTHON),
                "-c",
                "import sys, pip; print(sys.version_info.major, sys.version_info.minor)",
            ],
            capture=True,
        )
        major, minor = map(int, result.stdout.strip().split())
        if (major, minor) < (3, 12):
            return False, f"Python {major}.{minor} found; 3.12+ required"
        return True, f"Python {major}.{minor} -- OK"
    except Exception as exc:
        return False, f"Validation probe failed: {exc}"


def _find_python_312() -> str | None:
    """
    Return path to the best available Python 3.12+ binary by searching:
      1. Explicitly versioned names on PATH (python3.13, python3.12)
      2. Homebrew prefixes: Apple Silicon /opt/homebrew, Intel /usr/local
      3. pyenv shims and versions directory (~/.pyenv)
      4. Python.org macOS framework installer
      5. Generic python3 / python on PATH
      6. sys.executable as last resort
    """
    MIN = (3, 12)

    def _version_ok(exe: str) -> bool:
        try:
            r = subprocess.run(
                [exe, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode != 0:
                return False
            return tuple(map(int, r.stdout.strip().split())) >= MIN
        except Exception:
            return False

    candidates: list[str] = []

    # 1. Versioned names on PATH
    for name in ("python3.13", "python3.12"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    # 2. Homebrew
    for prefix in ("/opt/homebrew", "/usr/local"):
        for minor in (13, 12):
            p = f"{prefix}/bin/python3.{minor}"
            if Path(p).exists():
                candidates.append(p)
        p = f"{prefix}/bin/python3"
        if Path(p).exists():
            candidates.append(p)

    # 3. pyenv
    pyenv_root = Path(os.environ.get("PYENV_ROOT", Path.home() / ".pyenv"))
    if pyenv_root.exists():
        for minor in (13, 12):
            p = pyenv_root / "shims" / f"python3.{minor}"
            if p.exists():
                candidates.append(str(p))
        versions_dir = pyenv_root / "versions"
        if versions_dir.exists():
            for ver_dir in sorted(versions_dir.iterdir(), reverse=True):
                try:
                    parts = ver_dir.name.split(".")
                    if int(parts[0]) == 3 and int(parts[1]) >= 12:
                        p = ver_dir / "bin" / "python3"
                        if p.exists():
                            candidates.append(str(p))
                except (ValueError, IndexError):
                    pass

    # 4. Python.org macOS framework
    for minor in (13, 12):
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
        _err("Could not find Python 3.12+ on this system.")
        _err("Install options:")
        _err("  brew install python@3.12")
        _err("  pyenv install 3.12.x && pyenv global 3.12.x")
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
    installed = False
    for req in (REQUIREMENTS, REQUIREMENTS_DEV):
        if req.exists():
            _info(f"Installing {req.name} ...")
            _run([str(VENV_PIP), "install", "-r", str(req), "--quiet"])
            _ok(f"{req.name} installed")
            installed = True
    if not installed:
        _warn("No requirements files found -- skipping package install")


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
    answer = input(f"  {C_YELLOW}Delete and recreate .venv? [y/N]{C_RESET} ").strip().lower()
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
    else:
        _err(f"Recreated .venv still fails validation: {msg2}")
        _err("Please inspect .venv manually before continuing.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Tracking file data structures
# ---------------------------------------------------------------------------


@dataclass
class ProgressEntry:
    milestone_id: str
    label: str
    status: str
    blocking_issue: str = ""
    steps: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class WorkplanProgress:
    workplan_name: str
    progress_file: Path
    last_updated: str
    active_milestone: str
    active_step: str
    resume_detail: str
    entries: list[ProgressEntry] = field(default_factory=list)


@dataclass
class Issue:
    number: str
    title: str
    status: str
    milestone: str
    discovered: str
    resolved: str
    symptoms: str
    root_cause: str
    fix: str
    lesson_ref: str


@dataclass
class Lesson:
    number: str
    title: str
    milestone: str
    source: str
    lesson: str
    apply_to: str


@dataclass
class WorkplanTracking:
    workplan_name: str
    progress: WorkplanProgress | None = None
    issues: list[Issue] = field(default_factory=list)
    lessons: list[Lesson] = field(default_factory=list)


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


def _parse_progress(path: Path) -> WorkplanProgress | None:
    if not path.exists():
        return None
    headers: dict[str, str] = {}
    entries: list[ProgressEntry] = []
    current: ProgressEntry | None = None

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
            current.steps.append((step_m.group("label").strip(), step_m.group("status").upper()))
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
        block,
        re.MULTILINE | re.DOTALL,
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
        issues.append(
            Issue(
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
            )
        )
    return issues


def _parse_lessons(path: Path) -> list[Lesson]:
    if not path.exists():
        return []
    lessons: list[Lesson] = []
    for block in re.split(r"\n---\n", path.read_text(encoding="utf-8")):
        m = re.search(r"(LL-\d+)", block)
        if not m:
            continue
        lessons.append(
            Lesson(
                number=m.group(1),
                title=_block_field(block, "Title"),
                milestone=_block_field(block, "Milestone"),
                source=_block_field(block, "Source"),
                lesson=_block_field(block, "Lesson"),
                apply_to=_block_field(block, "Apply to"),
            )
        )
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
        wt.issues = _parse_issues(TRACKING_DIR / f"{stem}.issues")
        wt.lessons = _parse_lessons(TRACKING_DIR / f"{stem}.lessons-learned")
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
    workplan_stem: str  # stem used for tracking files
    workplan_path: Path  # absolute path to the workplan .md
    spec_path: Path | None  # absolute path to the software spec .md (optional)


def load_active_selection() -> ActiveSelection | None:
    """Load the persisted workplan + spec selection from .active_workplan (JSON)."""
    if not ACTIVE_WORKPLAN_FILE.exists():
        return None
    try:
        data = json.loads(ACTIVE_WORKPLAN_FILE.read_text(encoding="utf-8"))
        wp_path = PROJECT_ROOT / data["workplan_path"]
        sp_raw = data.get("spec_path", "")
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
        "spec_path": str(sel.spec_path.relative_to(PROJECT_ROOT)) if sel.spec_path else "",
    }
    ACTIVE_WORKPLAN_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def resolve_active_workplan(
    all_wt: list[WorkplanTracking],
) -> WorkplanTracking | None:
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
) -> Path | None:
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
    last_parent: Path | None = None
    for idx, fp in enumerate(files, 1):
        parent = fp.parent
        if parent != last_parent:
            rel_parent = parent.relative_to(PROJECT_ROOT)
            print(f"\n  {C_DIM}{rel_parent}/{C_RESET}")
            last_parent = parent
        size_kb = fp.stat().st_size / 1024
        print(f"    {C_BOLD}[{idx:>2}]{C_RESET}  {fp.name}  {C_DIM}({size_kb:.1f} KB){C_RESET}")

    skip_hint = " / s=skip" if allow_skip else ""
    print()
    try:
        raw = (
            input(f"  {C_YELLOW}{prompt} (1-{len(files)}{skip_hint} / Enter=cancel):{C_RESET} ")
            .strip()
            .lower()
        )
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


def action_select_workplan(all_wt: list[WorkplanTracking]) -> WorkplanTracking | None:
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


def find_resume(all_wt: list[WorkplanTracking]) -> tuple[str, str, str] | None:
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


def find_workplan_file(workplan_name: str) -> Path | None:
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


def find_spec_file() -> Path | None:
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

# Matches any of these heading styles Claude might produce:
#   ## MILESTONE: M0 -- Bootstrap
#   ## M0 -- Bootstrap
#   ## M0: Bootstrap
#   ## Milestone M0 -- Bootstrap
#   ## Milestone M0: Bootstrap
#   ## M0
_DISTIL_SECTION_RE = re.compile(
    r"##\s+"  # ## (required)
    r"(?:MILESTONE:\s*)?"  # optional "MILESTONE:" prefix
    r"(?:Milestone\s+)?"  # optional "Milestone " prefix
    r"(?P<mid>M\d+[A-Z]?)"  # M0, M1 … M12
    r"(?:\s*(?:--|:)\s*(?P<label>[^\n]+))?"  # optional " -- label" or ": label"
    r"\n(?P<body>.*?)(?=\n##\s+(?:MILESTONE:|Milestone\s+)?M\d|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def distilled_file_path(workplan_stem: str) -> Path:
    return TRACKING_DIR / f"{workplan_stem}.distilled.md"


def load_milestone_context(workplan_stem: str, milestone_id: str) -> str:
    """
    Return the distilled context block for a specific milestone, or "".
    Falls back to "" gracefully when the distilled file does not yet exist
    (caller should warn the user to run [d] first).
    """
    dp = distilled_file_path(workplan_stem)
    if not dp.exists():
        return ""

    text = dp.read_text(encoding="utf-8")
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
    omitted = len(raw) - keep_head - keep_tail
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
    if up == "DONE":
        return f"{C_GREEN}{s}{C_RESET}"
    if up == "IN_PROGRESS":
        return f"{C_CYAN}{s}{C_RESET}"
    if up == "BLOCKED":
        return f"{C_RED}{s}{C_RESET}"
    if up in ("WORKING", "IDENTIFIED"):
        return f"{C_YELLOW}{s}{C_RESET}"
    if up == "RESOLVED":
        return f"{C_GREEN}{s}{C_RESET}"
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

_DISTIL_SYSTEM = """You are a senior technical architect preparing per-milestone context documents
for an AI-assisted software engineering workflow.

You will receive:
  - A software specification document (the authoritative design reference).
  - A workplan document listing milestones with acceptance criteria and
    implementation guidance.

Your task is to produce a distilled context file that will be injected, one
section at a time, into future prompts that drive milestone implementation.
The file must be TOKEN-EFFICIENT: every word must earn its place.
A developer agent reading one section should have exactly what it needs for
that milestone and nothing more.

Output format -- produce this EXACTLY, no preamble, no postamble.
CRITICAL: every section heading MUST start with "## MILESTONE: MX --" exactly as shown.
Do not use "## M0", "## Milestone M0", or any other variation.

## MILESTONE: M0 -- <label from workplan>
### Spec Context
<2-4 bullet points of spec content directly relevant to this milestone.
Quote exact names, types, field lists, and rules from the spec where precise
wording matters. Omit anything not directly used in this milestone.>

### Key Constraints
<2-4 bullets: non-negotiable rules from CLAUDE.md / spec that apply here.
E.g. "All IDs must be ULIDs", "Feed edits create new versions, never mutate",
"Every mutation writes an immutable audit_event".>

### Interface Contracts
<List the concrete interfaces, Pydantic schemas, abstract base classes, and
API endpoint signatures that must be defined or consumed in this milestone.
Use exact names from the spec. Omit anything that belongs to a later milestone.>

### Acceptance Criteria
<Copy or tightly paraphrase the acceptance criteria checkboxes from the
workplan for this milestone. These are the tests that must pass.>

---
## MILESTONE: M1 -- <label>
<same four sections>

---
<continue for every milestone in the workplan>

Rules:
- Use the exact milestone IDs and labels from the workplan (M0, M1, M2 ...).
- Each section must be self-contained: a reader who sees only that section
  and the CLAUDE.md engineering protocol should be able to implement the step.
- Maximum ~500 words per milestone section. Prefer bullets over prose.
- Do NOT include implementation code, guesses, or content not grounded in
  the spec or workplan.
- End the file with a single line: <!-- distilled -->
"""


def _distil_refresh_section(
    sel: ActiveSelection,
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
                ll
                for ll in wt.lessons
                if milestone_id.lower() in ll.apply_to.lower() or "all" in ll.apply_to.lower()
            ]
            if relevant:
                lessons_text = "\n".join(
                    f"- {ll.number}: {ll.title}\n  {ll.lesson}" for ll in relevant
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
    _info(f"Size: {len(raw):,} chars  ({len(raw) // 4} tokens approx)")
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
            print(
                f"  {C_BOLD}{m.group('mid'):>3s}{C_RESET}  "
                f"{(m.group('label') or '').strip():<45s}  "
                f"{C_DIM}~{tokens} tokens{C_RESET}"
            )
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
                _info(f"... and {len(headings) - 20} more")
        print()
        _warn("The distilled file uses headings that don't match the regex.")
        _warn("Option 1: Delete the file and re-run [d] (the prompt is now stricter).")
        _warn("Option 2: Manually edit headings to '## MILESTONE: MX -- label' format.")
        _info(f"File path: {dp}")


def action_distil(
    all_wt: list[WorkplanTracking],
    refresh_milestone: str | None = None,
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
        answer = (
            input(
                f"  {C_YELLOW}Distilled file exists.  "
                f"[f]ull regen / [r]efresh one milestone / [c]ancel:{C_RESET} "
            )
            .strip()
            .lower()
        )
        if answer == "c":
            _info("Cancelled.")
            return
        if answer == "r":
            mid = input(f"  {C_YELLOW}Milestone to refresh (e.g. M3):{C_RESET} ").strip().upper()
            refresh_milestone = mid if mid else None

    if refresh_milestone:
        _distil_refresh_section(sel, dp, refresh_milestone, all_wt)
        return

    # Full regeneration -- warn if file exists
    if dp.exists():
        size_kb = dp.stat().st_size / 1024
        answer = (
            input(
                f"  {C_YELLOW}Distilled file already exists ({size_kb:.1f} KB).  "
                f"Regenerate all? [y/N]{C_RESET} "
            )
            .strip()
            .lower()
        )
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
    spec_text = load_spec_content_raw()

    if not spec_text:
        answer = (
            input(f"  {C_YELLOW}No spec file selected.  Distil from workplan only? [y/N]{C_RESET} ")
            .strip()
            .lower()
        )
        if answer != "y":
            _info("Aborted. Use [w] to select a spec file first.")
            return

    # Estimate and show token counts (rough: 1 token ≈ 4 chars)
    wp_tokens = len(workplan_text) // 4
    spec_tokens = len(spec_text) // 4
    total_in = wp_tokens + spec_tokens
    _info(f"Workplan:  ~{wp_tokens:,} tokens")
    _info(f"Spec:      ~{spec_tokens:,} tokens")
    _info(f"Total in:  ~{total_in:,} tokens  (one-time cost)")
    _info("Output:    per-milestone context blocks (~400-600 tokens each, reused every build)")

    answer = input(f"  {C_YELLOW}Proceed with distillation? [y/N]{C_RESET} ").strip().lower()
    if answer != "y":
        _info("Aborted.")
        return

    user_content = (
        "## Workplan\n\n"
        f"{workplan_text}\n\n"
        "## Software Specification\n\n"
        f"{spec_text if spec_text else '(no spec provided -- use workplan only)'}"
    )

    try:
        with Spinner("Claude is distilling per-milestone context"):
            result = call_claude(
                system=_DISTIL_SYSTEM,
                messages=[{"role": "user", "content": user_content}],
                max_tokens=8192,
            )
    except RuntimeError as exc:
        _err(f"Distillation failed: {exc}")
        return

    if "<!-- distilled -->" not in result:
        _warn("Response did not contain the expected end marker -- may be incomplete.")
        # Still try to save and parse it; Claude sometimes omits the marker
        _warn("Saving anyway and attempting to parse sections...")

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
    header = (
        f"<!-- FXLab distilled context\n"
        f"     Workplan: {workplan_stem}\n"
        f"     Spec:     {sel.spec_path.name if sel.spec_path else 'none'}\n"
        f"     Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
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
        print(
            f"  {C_BOLD}{m.group('mid'):>3s}{C_RESET}  "
            f"{m.group('label'):<45s}  {C_DIM}~{ctx_tokens} tokens{C_RESET}"
        )

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
    active_wt = resolve_active_workplan(all_wt)
    active_stem = active_wt.workplan_name if active_wt else ""
    active_mid = active_wt.progress.active_milestone if (active_wt and active_wt.progress) else ""

    distilled_ctx = (
        load_milestone_context(active_stem, active_mid) if active_stem and active_mid else ""
    )
    if distilled_ctx:
        _info(f"Using distilled context for {active_mid} (~{len(distilled_ctx) // 4} tokens)")
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

Output files using <<<FILE>>> blocks.

After files, add:
## Test Coverage Plan
- List each test and what behaviour it verifies
- Confirm each test will fail before implementation exists
""",
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

After files, add:
## Next Commands
- <exact pytest command to verify tests pass>

State which acceptance criteria from the workplan are now satisfied.
""",
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

_STEP_ID_RE = re.compile(r"S(\d+)", re.IGNORECASE)


def _step_id_from_detail(resume_detail: str) -> str:
    """Extract step ID (S1-S8) from a progress file resume_detail string."""
    m = _STEP_ID_RE.search(resume_detail)
    return f"S{m.group(1)}" if m else "S4"  # default to GREEN if ambiguous


def _system_for_step(step_id: str) -> str:
    """Return the appropriate system prompt for the given step ID."""
    return _STEP_PROMPTS.get(step_id.upper(), _STEP_PROMPTS["S4"])


_AGENT_SYSTEM = _STEP_PROMPTS["S4"]  # legacy alias for direct calls


def _extract_files(response: str) -> list[tuple[str, str]]:
    """Parse <<<FILE: path>>> ... <<<END_FILE>>> blocks from a Claude response."""
    pattern = re.compile(
        r"<<<FILE:\s*(?P<path>[^\n>]+)>>>\n(?P<content>.*?)<<<END_FILE>>>",
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
    """Prompt before writing a file to disk. Returns True to write."""
    line_count = len(content.splitlines())
    print(f"\n  {C_BOLD}File:{C_RESET} {C_CYAN}{rel_path}{C_RESET}  ({line_count} lines)")
    answer = input(f"  {C_YELLOW}Write? [Y/n/p=preview]{C_RESET} ").strip().lower()
    if answer == "p":
        for i, line in enumerate(content.splitlines()[:50], 1):
            print(f"  {C_DIM}{i:3d}{C_RESET}  {line}")
        if line_count > 50:
            _info(f"... ({line_count - 50} more lines)")
        answer = input(f"  {C_YELLOW}Write? [Y/n]{C_RESET} ").strip().lower()
    return answer != "n"


# ---------------------------------------------------------------------------
# Prerequisite gate  (improvement #3)
# ---------------------------------------------------------------------------

# Hardcoded dependency chain matching the workplan milestone graph.
# Key = milestone that has prerequisites; value = list of required-DONE milestones.
_MILESTONE_DEPS: dict[str, list[str]] = {
    "M1": ["M0"],
    "M2": ["M1"],
    "M3": ["M2"],
    "M4": ["M3"],
    "M5": ["M4"],
    "M6": ["M5"],
    "M7": ["M6"],
    "M8": ["M7"],
    "M9": ["M2", "M7"],
    "M10": ["M4", "M7"],
    "M11": ["M4", "M8", "M10"],
    "M12": ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11"],
}


def check_prerequisites(active_wt: WorkplanTracking, milestone_id: str) -> tuple[bool, list[str]]:
    """
    Check that all prerequisite milestones are DONE in the progress file.
    Returns (ok, list_of_blocking_milestone_ids).
    """
    if active_wt.progress is None:
        return True, []  # can't check, don't block

    required = _MILESTONE_DEPS.get(milestone_id.upper(), [])
    if not required:
        return True, []

    done_ids = {e.milestone_id.upper() for e in active_wt.progress.entries if e.status == "DONE"}
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
    text = (
        re.sub(
            re.escape(_FINGERPRINT_MARKER) + r".*?(?=\n#|\Z)",
            "",
            text,
            flags=re.DOTALL,
        ).rstrip()
        + "\n"
    )
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    block = "\n" + _FINGERPRINT_MARKER + f" milestone={milestone_id} ts={now_ts}\n"
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
        distilled_text,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_m:
        return []
    section = section_m.group(1)
    # Match bare method names: word chars followed by optional whitespace then (
    names = re.findall(r"([a-z_][a-z0-9_]{2,})\s*\(", section, re.IGNORECASE)
    # Exclude Python builtins and common noise words
    skip = {
        "def",
        "class",
        "if",
        "for",
        "while",
        "return",
        "raise",
        "print",
        "isinstance",
        "hasattr",
        "getattr",
        "setattr",
        "len",
        "str",
        "int",
        "dict",
        "list",
        "tuple",
        "set",
        "type",
        "super",
        "object",
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


def run_tests_capture(test_dir: str = "tests/") -> tuple[bool, str]:
    """
    Run pytest and capture output.  Returns (passed, failure_output).
    failure_output is empty string on success.
    """
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "pytest", test_dir, "--tb=short", "-q", "--no-header"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    passed = result.returncode == 0
    output = (result.stdout + result.stderr).strip()
    return passed, ("" if passed else output)


# ---------------------------------------------------------------------------
# Progress file auto-advance  (improvement #4)
# ---------------------------------------------------------------------------


def _step_sequence() -> list[str]:
    return [sid for sid, _ in STEP_LABELS]


def advance_progress_step(
    progress_path: Path, milestone_id: str, completed_step_id: str
) -> str | None:
    """
    Mark completed_step_id as DONE for milestone_id and advance Active step.
    Returns the next step ID, or None if the milestone is now fully complete.
    Updates the progress file in-place.
    """
    if not progress_path.exists():
        return None

    text = progress_path.read_text(encoding="utf-8")
    seq = _step_sequence()

    # Mark the completed step DONE
    old_entry = f"[{milestone_id}-{completed_step_id}]"
    # Replace status on the line containing this entry
    text = re.sub(
        re.escape(old_entry) + r"([^\n]+?)(NOT_STARTED|IN_PROGRESS)",
        r"\1DONE",
        text,
    )

    # Find next step
    try:
        current_idx = seq.index(completed_step_id.upper())
        next_step = seq[current_idx + 1] if current_idx + 1 < len(seq) else None
    except ValueError:
        next_step = None

    # Update header lines
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = re.sub(r"^# Last updated:.*$", f"# Last updated: {now}", text, flags=re.MULTILINE)

    if next_step:
        # Find the label for next step
        next_label = next((lbl for sid, lbl in STEP_LABELS if sid == next_step), next_step)
        new_active = f"STEP {seq.index(next_step) + 1} -- {next_label} ({milestone_id})"
        text = re.sub(
            r"^# Active step:.*$", f"# Active step: {new_active}", text, flags=re.MULTILINE
        )
        # Mark the next step IN_PROGRESS
        text = re.sub(
            r"(\["
            + re.escape(milestone_id)
            + r"-"
            + re.escape(next_step)
            + r"\][^\n]+?)NOT_STARTED",
            r"\1IN_PROGRESS",
            text,
        )
    else:
        # All steps done -- mark the milestone itself DONE
        text = re.sub(
            r"(\[" + re.escape(milestone_id) + r"\][^\n]+?)(IN_PROGRESS|NOT_STARTED)",
            r"\1DONE",
            text,
        )
        text = re.sub(
            r"^# Active step:.*$",
            f"# Active step: {milestone_id} COMPLETE -- advance Active milestone",
            text,
            flags=re.MULTILINE,
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
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
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
        f"feat({milestone_id.lower()}-{step_id.lower()}): {step_label.lower().replace(' -- ', ' ')}"
    )
    print(f"\n  {C_BOLD}Proposed commit message:{C_RESET}")
    print(f"  {C_CYAN}{msg}{C_RESET}")
    answer = input(f"  {C_YELLOW}Commit all changes? [y/N/e=edit]{C_RESET} ").strip().lower()
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
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
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
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        git_diff = r.stdout.strip()
        if not git_diff:
            # Try against last commit if nothing staged
            r2 = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
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


def action_agentic_build(all_wt: list[WorkplanTracking]) -> None:
    """
    Drive the next milestone step with Claude as implementation agent.

    Improvements active:
      #2 Per-step system prompts    -- S1-S8 each get a purpose-built prompt
      #3 Prerequisite gate          -- blocks if upstream milestones not DONE
      #4 Progress auto-advance      -- marks step DONE and advances on success
      #6 Auto-commit gate           -- offers conventional commit after clean run
      #7 Contract completeness AST  -- verifies method names exist after GREEN
      #8 Contract fingerprinting    -- stores/checks interface hashes after S2
      #1 Iteration loop             -- retries up to 3x with test failure output
    """
    _h2("Agentic milestone execution")
    MAX_ITERATIONS = 3

    active_wt = resolve_active_workplan(all_wt)
    if active_wt is None:
        _warn("No active workplan selected. Use [w] to select one first.")
        return
    if active_wt.progress is None:
        _warn(f"Workplan '{active_wt.workplan_name}' has no .progress file.")
        _warn("Run [b] to bootstrap tracking files.")
        return

    wp = active_wt.progress
    wname = active_wt.workplan_name
    active_milestone = wp.active_milestone
    active_step = wp.resume_detail
    step_id = _step_id_from_detail(active_step)
    system_prompt = _system_for_step(step_id)

    _info(f"Workplan:  {wname}")
    _info(f"Milestone: {C_BOLD}{active_milestone}{C_RESET}")
    _info(f"Step:      {C_BOLD}{active_step}{C_RESET}  [{step_id}]")

    # ── Improvement #3: prerequisite gate ───────────────────────────────────
    prereqs_ok, blocking = check_prerequisites(active_wt, active_milestone)
    if not prereqs_ok:
        _err(f"Prerequisites not met for {active_milestone}:")
        for b in blocking:
            _err(f"  {b} must be DONE first")
        answer = input(f"  {C_YELLOW}Override and proceed anyway? [y/N]{C_RESET} ").strip().lower()
        if answer != "y":
            return

    # ── Improvement #8: contract drift check ────────────────────────────────
    if wp.progress_file.exists():
        fp_ok, drifted = check_contract_fingerprints(wp.progress_file)
        if not fp_ok:
            _warn("Interface contracts have changed since last S2 step:")
            for d in drifted:
                _warn(f"  {d}")
            _warn("Downstream milestones may have stale context.")
            _warn("Consider re-running [d] to refresh distilled context.")

    # ── Load workplan spec section ───────────────────────────────────────────
    workplan_path = find_workplan_file(wname)
    workplan_section = ""
    if workplan_path and workplan_path.exists():
        full_text = workplan_path.read_text(encoding="utf-8")
        pat = re.compile(
            rf"###\s+Milestone\s+{re.escape(active_milestone)}[\s:].+?"
            rf"(?=\n###\s+Milestone\s+M|\Z)",
            re.DOTALL | re.IGNORECASE,
        )
        m = pat.search(full_text)
        if m:
            workplan_section = m.group(0)
            _info(f"Workplan section: {len(workplan_section.splitlines())} lines")
        else:
            workplan_section = full_text[:8000]
            _warn("Could not isolate milestone section; using truncated workplan")
    else:
        _warn(f"Workplan file not found for '{wname}'")

    distilled_ctx = load_milestone_context(wname, active_milestone)
    if distilled_ctx:
        _info(f"Distilled context: ~{len(distilled_ctx) // 4} tokens")
        spec_section = f"## Distilled Context for {active_milestone}\n\n{distilled_ctx}\n\n"
    else:
        if not distilled_file_path(wname).exists():
            _warn("No distilled context -- run [d] first (recommended).")
        spec_section = ""

    state_dump = build_state_dump(all_wt)

    def _build_user_content(extra: str = "") -> str:
        return (
            f"## Active Task\n\n"
            f"Workplan: {wname}\n"
            f"Milestone: {active_milestone}\n"
            f"Step: {active_step} [{step_id}]\n\n"
            f"{spec_section}"
            f"## Workplan Spec for {active_milestone}\n\n"
            f"{workplan_section or '(no workplan section found)'}\n\n"
            f"## Current Project State\n\n"
            f"{state_dump}\n\n"
            f"{extra}"
            f"## Instructions\n\n"
            f"Implement '{active_step}' [{step_id}] for {active_milestone}.\n"
            f"Output complete production-quality files using the <<<FILE>>> format.\n"
            f"Do not implement beyond this step.\n"
        )

    print()
    confirm = input(f"  {C_YELLOW}Send to Claude and generate? [y/N]{C_RESET} ").strip().lower()
    if confirm != "y":
        _info("Aborted.")
        return

    # ── Improvement #1: iteration loop with test feedback ───────────────────
    messages: list[dict] = []
    written_paths: list[str] = []
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        extra_ctx = ""
        if iteration > 1:
            _h2(f"Iteration {iteration}/{MAX_ITERATIONS} -- retrying with test feedback")

        user_content = _build_user_content(extra_ctx)
        messages = [{"role": "user", "content": user_content}]

        try:
            with Spinner(f"Claude [{step_id}] {active_milestone} iter {iteration}"):
                response = call_claude(
                    system=system_prompt,
                    messages=messages,
                    max_tokens=8192,
                )
        except RuntimeError as exc:
            _err(f"API call failed: {exc}")
            return

        # Print narrative
        narrative = re.sub(r"<<<FILE:.*?<<<END_FILE>>>", "", response, flags=re.DOTALL).strip()
        if narrative:
            print()
            print(narrative)
            print()

        # Write files
        file_blocks = _extract_files(response)
        if file_blocks:
            _h2(f"Files to write ({len(file_blocks)} total)")
            written_paths = []
            for rel_path, content in file_blocks:
                if _confirm_write(rel_path, content):
                    dest = PROJECT_ROOT / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(content, encoding="utf-8")
                    _ok(f"Written: {rel_path}")
                    written_paths.append(rel_path)
                else:
                    _warn(f"Skipped: {rel_path}")
        else:
            _warn("No <<<FILE>>> blocks in response.")
            break

        # ── Improvement #7: contract completeness check (after S2/S4) ───────
        if step_id in ("S2", "S4") and distilled_ctx:
            ast_ok, missing = run_contract_completeness_check(written_paths, distilled_ctx)
            if not ast_ok:
                _warn(f"Contract completeness: {len(missing)} method(s) not found in output:")
                for name in missing:
                    _warn(f"  missing: {name}()")
                if step_id == "S4":
                    _warn("These will likely cause test failures -- see iteration feedback below.")
            else:
                _ok("Contract completeness: all interface methods present.")

        # ── Improvement #8: store fingerprints after S2 ──────────────────────
        if step_id == "S2" and wp.progress_file.exists():
            fps = store_contract_fingerprints(wp.progress_file, active_milestone)
            if fps:
                _ok(f"Contract fingerprints stored: {len(fps)} interface file(s)")

        # ── Run tests and decide whether to iterate ──────────────────────────
        if step_id in ("S3", "S4", "S7"):
            _h2("Running tests to verify output")
            tests_pass, failure_output = run_tests_capture()
            if tests_pass:
                _ok("All tests pass.")
                break
            else:
                _err(f"Tests failed (iteration {iteration}/{MAX_ITERATIONS})")
                if iteration < MAX_ITERATIONS:
                    trunc = failure_output[:3000]
                    _info(f"Feeding {len(trunc)} chars of failure output back to Claude...")
                    extra_ctx = (
                        f"## Test Failure Output (iteration {iteration})\n\n"
                        f"The files you wrote in the previous attempt produced these failures:\n\n"
                        f"```\n{trunc}\n```\n\n"
                        f"Analyse the failures, then output corrected files.\n\n"
                    )
                    # Re-build with failure context appended
                    user_content = _build_user_content(extra_ctx)
                    messages = [{"role": "user", "content": user_content}]
                else:
                    _warn("Max iterations reached. Review failures manually.")
                    print()
                    print(failure_output[:2000])
        else:
            # Non-test steps don't iterate
            break

    # ── Print next commands ──────────────────────────────────────────────────
    cmds = _extract_next_commands(response)
    if cmds:
        _h2("Next commands")
        bin_dir = VENV_PYTHON.parent
        for cmd in cmds:
            print(f"  {C_CYAN}${C_RESET}  {cmd}")
            exe = cmd.split()[0] if cmd.split() else ""
            if exe and (bin_dir / exe).exists():
                _info(f"     -> {bin_dir / exe}")

    # ── Improvement #4: auto-advance progress ───────────────────────────────
    tests_clean = (step_id not in ("S3", "S4", "S7")) or (
        step_id in ("S3", "S4", "S7") and run_tests_capture()[0]
    )
    if written_paths and tests_clean and wp.progress_file.exists():
        next_step = advance_progress_step(wp.progress_file, active_milestone, step_id)
        if next_step:
            _ok(f"Progress advanced: {step_id} -> {next_step} (updated .progress file)")
        else:
            _ok(f"Milestone {active_milestone} fully complete in progress file.")

    # ── Improvement #6: auto-commit ──────────────────────────────────────────
    if written_paths:
        step_label = next((lbl for sid, lbl in STEP_LABELS if sid == step_id), step_id)
        action_auto_commit(active_milestone, step_id, step_label)

    print()
    _info(f"Tracking dir: {TRACKING_DIR}")


# ---------------------------------------------------------------------------
# Other build actions
# ---------------------------------------------------------------------------


def action_run_tests() -> None:
    _h2("Test suite (pytest + coverage)")
    _run(
        [
            str(VENV_PYTHON),
            "-m",
            "pytest",
            "tests/",
            "--tb=short",
            "--cov=.",
            "--cov-report=term-missing",
            "-q",
        ],
        check=False,
    )


def action_quality_gate(
    all_wt: list[WorkplanTracking] | None = None,
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
        ([str(bin_dir / "black"), "--check", "."], "Format check (black)"),
        ([str(bin_dir / "ruff"), "check", "."], "Lint (ruff)"),
        ([str(bin_dir / "mypy"), ".", "--ignore-missing-imports"], "Type check (mypy)"),
        ([str(VENV_PYTHON), "-m", "pytest", "tests/", "-q", "--tb=short"], "Tests (pytest)"),
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
            wp = active_wt.progress
            step_id = _step_id_from_detail(wp.resume_detail)
            if step_id == "S5":  # quality gate IS step S5
                next_s = advance_progress_step(wp.progress_file, wp.active_milestone, "S5")
                if next_s:
                    _ok(f"Progress: S5 DONE -> {next_s}")
            step_label = next((lbl for sid, lbl in STEP_LABELS if sid == step_id), step_id)
            action_auto_commit(wp.active_milestone, step_id, step_label)

    return all_ok


def action_docker_up() -> None:
    _h2("Docker Compose up")
    for p in (
        PROJECT_ROOT / "infra" / "compose" / "docker-compose.yml",
        PROJECT_ROOT / "docker-compose.yml",
    ):
        if p.exists():
            _run(["docker", "compose", "-f", str(p), "up", "-d"], check=False)
            return
    _warn("No docker-compose.yml found.")


def action_docker_down() -> None:
    _h2("Docker Compose down")
    for p in (
        PROJECT_ROOT / "infra" / "compose" / "docker-compose.yml",
        PROJECT_ROOT / "docker-compose.yml",
    ):
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
    ("M0", "Bootstrap"),
    ("M1", "Docker Runtime"),
    ("M2", "DB Schema + Migrations + Audit Ledger"),
    ("M3", "Auth + RBAC"),
    ("M4", "Jobs + Queue Classes + Compute Policy"),
    ("M5", "Artifact Registry + Storage Abstraction"),
    ("M6", "Feed Registry + Versioned Config + Connectivity Tests"),
    ("M7", "Ingest Pipeline"),
    ("M8", "Verification + Gaps + Anomalies + Certification"),
    ("M9", "Symbol Lineage"),
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
        p.stem
        for p in SPEC_DIR.rglob("*.md")
        if "workplan-tracking" not in str(p)
        and ("workplan" in p.stem.lower() or "plan" in p.stem.lower())
    ]
    if not found:
        found = [
            p.stem for p in PROJECT_ROOT.rglob("*workplan*.md") if "workplan-tracking" not in str(p)
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
    (_ok if ok else _err)(f"ANTHROPIC_API_KEY: {msg}")
    _info(
        f"ANTHROPIC_MODEL:   {os.environ.get('ANTHROPIC_MODEL', DEFAULT_MODEL)} "
        f"{'(default)' if 'ANTHROPIC_MODEL' not in os.environ else '(from env)'}"
    )
    _info(f"VENV_PYTHON:       {VENV_PYTHON}  ({'exists' if VENV_PYTHON.exists() else 'missing'})")


def action_open_shell() -> None:
    _h2("Activate venv")
    _info(f"Run:  source {VENV_ACTIVATE}")
    _info("(Cannot auto-activate in the parent shell -- copy the command above.)")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

MENU_ITEMS: list[tuple[str, str]] = [
    ("w", "Workplan -- browse User Spec/ and select workplan + spec"),
    ("d", "Distil -- generate/refresh per-milestone context from spec [AI]"),
    ("dv", "Distil debug -- diagnose why sections show as 0"),
    ("r", "Resume -- continue from last saved position"),
    ("a", "Agentic build -- drive next milestone step with Claude [AI]"),
    ("c", "Claude brief -- AI session summary [AI]"),
    ("p", "Show full progress summary"),
    ("i", "Show all open issues"),
    ("l", "Show all lessons learned"),
    ("b", "Bootstrap / refresh tracking files"),
    ("t", "Run test suite"),
    ("q", "Run quality gate (format + lint + type + tests)"),
    ("h", "Handoff -- write session summary doc [AI]"),
    ("du", "Docker Compose up"),
    ("dd", "Docker Compose down"),
    ("m", "Run database migrations (Alembic)"),
    ("e", "Show environment / API key status"),
    ("sh", "Show venv activate command"),
    ("x", "Exit"),
]


def print_menu(
    resume: tuple[str, str, str] | None,
    api_ok: bool,
    all_wt: list[WorkplanTracking],
) -> None:
    _h1("FXLab Build Menu")

    # Show active workplan + spec prominently at the top
    active = resolve_active_workplan(all_wt)
    sel = load_active_selection()
    if active:
        print(f"  Workplan: {C_BOLD}{C_CYAN}{active.workplan_name}{C_RESET}", end="")
        if active.progress:
            print(f"  |  milestone {C_BOLD}{active.progress.active_milestone}{C_RESET}", end="")
        print()
        if sel and sel.spec_path:
            print(f"  Spec:     {C_DIM}{sel.spec_path.relative_to(PROJECT_ROOT)}{C_RESET}")
        else:
            print(f"  Spec:     {C_DIM}(none -- use [w] to set){C_RESET}")
        # Show distilled file status
        dp = distilled_file_path(active.workplan_name)
        if dp.exists():
            sections = list(_DISTIL_SECTION_RE.finditer(dp.read_text()))
            print(
                f"  Context:  {C_GREEN}{dp.name}  ({len(sections)} milestones distilled){C_RESET}"
            )
        else:
            print(f"  Context:  {C_YELLOW}not distilled yet -- run [d]{C_RESET}")
    elif all_wt:
        print(f"  {C_YELLOW}No workplan selected -- use [w] to choose one{C_RESET}")
    else:
        print(
            f"  {C_YELLOW}No tracking files -- use [w] to select a workplan from User Spec/{C_RESET}"
        )
    print()

    api_tag = f" {C_GREEN}[API OK]{C_RESET}" if api_ok else f" {C_RED}[API KEY MISSING]{C_RESET}"
    for key, label in MENU_ITEMS:
        prefix = f"  {C_BOLD}[{key:>2s}]{C_RESET}"
        if key == "w":
            if sel:
                wp_short = sel.workplan_path.name if sel.workplan_path else sel.workplan_stem
                spec_short = sel.spec_path.name if sel.spec_path else "no spec"
                hint = f"{wp_short} / {spec_short}"
            else:
                hint = "none selected"
            print(f"{prefix}  {label}  {C_DIM}({hint}){C_RESET}")
        elif "[AI]" in label:
            clean = label.replace("[AI]", "").rstrip()
            print(f"{prefix}  {clean}{api_tag}")
        elif key == "r":
            if resume:
                _, milestone, detail = resume
                hint = f"  {C_GREEN}<- {milestone}: {detail[:42]}{C_RESET}"
                print(f"{prefix}  {label}{hint}")
            else:
                print(f"{prefix}  {label}  {C_DIM}(nothing in progress){C_RESET}")
        else:
            print(f"{prefix}  {label}")
    print()


def handle_choice(
    choice: str,
    resume: tuple[str, str, str] | None,
    all_wt: list[WorkplanTracking],
    api_ok: bool,
) -> bool:
    """Return True to keep looping, False to exit."""
    c = choice.strip().lower()

    def _need_api() -> bool:
        if not api_ok:
            _err("ANTHROPIC_API_KEY is not set or invalid.")
            _err("Add it to .env at the project root and restart build.py.")
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
        if _need_api():
            action_agentic_build(all_wt)
    elif c == "c":
        if _need_api():
            action_ai_brief(all_wt)
    elif c == "p":
        action_show_progress(all_wt)
    elif c == "i":
        action_show_issues(all_wt)
    elif c == "l":
        action_show_lessons(all_wt)
    elif c == "b":
        action_bootstrap()
    elif c == "t":
        action_run_tests()
    elif c == "q":
        action_quality_gate(all_wt=all_wt)
    elif c == "h":
        action_handoff(all_wt, api_ok)
    elif c == "du":
        action_docker_up()
    elif c == "dd":
        action_docker_down()
    elif c == "m":
        action_run_migrations()
    elif c == "e":
        action_show_env()
    elif c == "sh":
        action_open_shell()
    elif c == "x":
        print(f"\n{C_DIM}Goodbye.{C_RESET}\n")
        return False
    else:
        _warn(f"Unknown choice: '{c}'")

    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FXLab build menu -- venv, tracking, and agentic dev tasks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--no-brief", action="store_true", help="Skip the AI session brief at startup."
    )
    parser.add_argument(
        "--run", metavar="CHOICE", help="Run one menu action non-interactively (e.g. --run t)."
    )
    args = parser.parse_args()

    # 1. Load .env and validate API key
    _h2("Environment")
    loaded = load_dotenv()
    if loaded:
        _ok(f".env loaded -- {len(loaded)} variable(s)")
        if "ANTHROPIC_API_KEY" in loaded:
            _info("ANTHROPIC_API_KEY found in .env")
    elif ENV_FILE.exists():
        _warn(".env found but no parseable KEY=VALUE lines")
    else:
        _warn(".env not found at project root -- create one with ANTHROPIC_API_KEY=sk-ant-...")

    api_ok, api_msg = validate_api_key()
    if api_ok:
        _ok(f"Anthropic API key: {api_msg}")
    else:
        _warn(f"Anthropic API key: {api_msg}")
        _warn("AI features disabled until a valid key is present in .env")

    # 2. Ensure venv
    ensure_venv()

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
        print_menu(resume, api_ok, all_wt)
        try:
            choice = input(f"{C_BOLD}Choice:{C_RESET} ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            print(f"{C_DIM}Interrupted.{C_RESET}")
            break
        if not handle_choice(choice, resume, all_wt, api_ok):
            break
        # Refresh state each loop iteration
        all_wt = discover_tracking()
        resume = find_resume(all_wt)


if __name__ == "__main__":
    main()

"""M0 Bootstrap acceptance tests.

These verify the repo skeleton meets M0 acceptance criteria:
- Required directories exist
- Required tracking files exist with correct headers
- Fixture CSV files exist and are non-empty
- API health endpoint is importable and returns expected shape
- libs/contracts package is importable with no circular imports
"""
from pathlib import Path
import csv
import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


def test_service_directories_exist():
    """All required service directories from the workplan exist."""
    services = [
        "api", "auth", "orchestrator", "scheduler",
        "market_data_ingest", "feed_verification", "feed_parity",
        "artifact_registry", "alerting", "observability",
    ]
    for svc in services:
        assert (PROJECT_ROOT / "services" / svc).is_dir(), \
            f"services/{svc}/ directory missing"


def test_lib_directories_exist():
    """All required lib directories exist."""
    libs = [
        "contracts", "db", "authz", "storage", "feeds", "datasets",
        "audit", "jobs", "quality", "parity", "telemetry", "utils",
    ]
    for lib in libs:
        assert (PROJECT_ROOT / "libs" / lib).is_dir(), \
            f"libs/{lib}/ directory missing"


def test_infra_directories_exist():
    """Infra directories exist."""
    for d in ["compose", "docker", "migrations", "observability"]:
        assert (PROJECT_ROOT / "infra" / d).is_dir(), \
            f"infra/{d}/ directory missing"


def test_tracking_files_exist():
    """All tracking files are present with correct headers."""
    tracking = PROJECT_ROOT / "docs" / "workplan-tracking"
    stem = "FXLab_Phase_1_workplan_v3"

    for ext in (".progress", ".issues", ".lessons-learned"):
        p = tracking / f"{stem}{ext}"
        assert p.exists(), f"Missing tracking file: {p.name}"
        content = p.read_text()
        assert f"# Workplan: {stem}.md" in content, \
            f"Header 'Workplan:' missing in {p.name}"

    assert (tracking / "SHARED_LESSONS.md").exists(), \
        "SHARED_LESSONS.md missing"
    assert (tracking / ".active_workplan").exists(), \
        ".active_workplan missing"


def test_active_workplan_is_valid_json():
    """The .active_workplan file is valid JSON with required keys.

    We only validate structure here — not the specific workplan stem — so
    the file continues to pass as the project advances through phases.
    """
    import json
    p = PROJECT_ROOT / "docs" / "workplan-tracking" / ".active_workplan"
    data = json.loads(p.read_text())
    assert "workplan_stem" in data, ".active_workplan must have 'workplan_stem' key"
    assert "workplan_path" in data, ".active_workplan must have 'workplan_path' key"
    # Stem must be a non-empty string that looks like a workplan identifier
    assert isinstance(data["workplan_stem"], str) and data["workplan_stem"].startswith("FXLab_"), (
        f"workplan_stem '{data['workplan_stem']}' must start with 'FXLab_'"
    )
    # Path must point to an existing .md file under User Spec/
    wp_path = PROJECT_ROOT / data["workplan_path"]
    assert wp_path.exists(), (
        f"workplan_path '{data['workplan_path']}' does not exist on disk — "
        "run [w] in build.py to re-select the workplan"
    )


def test_fixture_csvs_exist_and_nonempty():
    """All six fixture CSV files exist and contain data rows."""
    fixtures = PROJECT_ROOT / "tests" / "fixtures"
    expected = [
        "clean_ohlcv.csv",
        "gapped_ohlcv.csv",
        "malformed_ohlcv.csv",
        "parity_left.csv",
        "parity_right_mismatch.csv",
        "parity_right_clean.csv",
    ]
    for fname in expected:
        p = fixtures / fname
        assert p.exists(), f"Fixture missing: {fname}"
        with open(p) as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) > 0, f"Fixture is empty: {fname}"


def test_fixture_csv_headers():
    """Fixture CSVs have the canonical bar schema headers."""
    expected_headers = {
        "canonical_symbol", "source_symbol", "venue", "asset_class",
        "timeframe", "ts", "open", "high", "low", "close", "volume",
    }
    p = PROJECT_ROOT / "tests" / "fixtures" / "clean_ohlcv.csv"
    with open(p) as fh:
        reader = csv.DictReader(fh)
        actual = set(reader.fieldnames or [])
    assert expected_headers <= actual, \
        f"Missing headers: {expected_headers - actual}"


def test_gapped_fixture_has_fewer_rows_than_clean():
    """Gapped fixture has fewer rows than clean (gaps were removed)."""
    def count(fname: str) -> int:
        p = PROJECT_ROOT / "tests" / "fixtures" / fname
        with open(p) as fh:
            return sum(1 for _ in csv.DictReader(fh))

    assert count("gapped_ohlcv.csv") < count("clean_ohlcv.csv"), \
        "gapped_ohlcv should have fewer rows than clean_ohlcv"


def test_malformed_fixture_has_expected_anomalies():
    """Malformed fixture contains high < low, negative volume, empty timestamp."""
    p = PROJECT_ROOT / "tests" / "fixtures" / "malformed_ohlcv.csv"
    with open(p) as fh:
        rows = list(csv.DictReader(fh))

    has_inverted_hl  = any(
        float(r["high"]) < float(r["low"]) for r in rows if r["high"] and r["low"]
    )
    has_negative_vol = any(
        float(r["volume"]) < 0 for r in rows if r["volume"]
    )
    has_null_ts      = any(r["ts"] == "" for r in rows)

    assert has_inverted_hl,  "No high < low anomaly found in malformed fixture"
    assert has_negative_vol, "No negative volume found in malformed fixture"
    assert has_null_ts,      "No null timestamp found in malformed fixture"


def test_parity_mismatch_differs_from_left():
    """Parity mismatch fixture differs from left in at least one close price."""
    def load(fname: str) -> list[dict]:
        p = PROJECT_ROOT / "tests" / "fixtures" / fname
        with open(p) as fh:
            return list(csv.DictReader(fh))

    left     = load("parity_left.csv")
    mismatch = load("parity_right_mismatch.csv")
    diffs = sum(
        1 for l, m in zip(left, mismatch)
        if l["close"] != m["close"]
    )
    assert diffs > 0, "parity_right_mismatch should differ from parity_left"


def test_contracts_importable():
    """libs.contracts can be imported without errors."""
    from libs.contracts import enums, base, errors  # noqa: F401
    assert hasattr(enums, "FeedLifecycleStatus")
    assert hasattr(base, "APIResponse")
    assert hasattr(errors, "NotFoundError")


def test_api_health_route_importable():
    """The API main module can be imported and health route exists."""
    from services.api.main import app
    routes = {r.path for r in app.routes}
    assert "/health" in routes
    assert "/health/dependencies" in routes

"""
Shared pytest fixtures for all test modules.

Responsibilities:
- Provide cross-cutting fixtures used by unit, integration, and acceptance tests.
- All fixtures here are available in every test file without explicit import.

Does NOT:
- Contain business logic.
- Perform real I/O against live services.

Fixtures provided:
- correlation_id: fresh ULID string per test
- auth_headers: dict with Authorization Bearer TEST_TOKEN header
- mock_logger: structlog-compatible mock
- mock_metadata_db: mock database connection
- mock_artifact_storage: mock ArtifactStorage implementation
- project_root: Path to the repository root
- test_data_dir: Path to tests/fixtures/data/
- fixture_csv_dir: alias for test_data_dir
- mock_env: monkeypatched environment variables for test isolation
- sample_strategy_code: string containing a minimal strategy definition
"""

import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import ulid

# ---------------------------------------------------------------------------
# sys.path bootstrap — ensures 'libs' and 'services' are importable
# without requiring an editable install.  This is the only appropriate place
# for this manipulation; all other modules must NOT mutate sys.path.
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Core test-infrastructure fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def ensure_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ensure ENVIRONMENT=test is set for every test so that JWT auth
    accepts the TEST_TOKEN bypass.  Autouse guarantees no test
    accidentally runs with a production-like environment.

    Args:
        monkeypatch: pytest's built-in monkeypatch fixture.
    """
    monkeypatch.setenv("ENVIRONMENT", "test")


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """
    Return HTTP headers containing the TEST_TOKEN for authenticated requests.

    Use this fixture when calling protected endpoints via TestClient:

        response = client.get("/some-protected-route", headers=auth_headers)

    Returns:
        Dict with Authorization: Bearer TEST_TOKEN.
    """
    return {"Authorization": "Bearer TEST_TOKEN"}


@pytest.fixture
def correlation_id() -> str:
    """
    Generate a unique correlation ID for request tracing.

    Returns:
        Fresh ULID string, unique per test invocation.
    """
    return str(ulid.ULID())


@pytest.fixture
def mock_logger() -> MagicMock:
    """
    Provide a mock structured logger compatible with structlog's API.

    The mock's bind() method returns itself so that chained calls such as
    `logger.bind(key=value).info(...)` work without raising AttributeError.

    Returns:
        MagicMock preconfigured to behave like a structlog BoundLogger.
    """
    logger = MagicMock()
    logger.bind.return_value = logger
    return logger


@pytest.fixture
def mock_metadata_db() -> MagicMock:
    """
    Provide a mock metadata database connection.

    Returns:
        MagicMock with execute/commit/rollback stubbed to return None.
    """
    db = MagicMock()
    db.execute.return_value = MagicMock()
    db.commit.return_value = None
    db.rollback.return_value = None
    return db


@pytest.fixture
def mock_artifact_storage() -> MagicMock:
    """
    Provide a mock ArtifactStorage implementation.

    Stubs every method on the ArtifactStorage interface with safe defaults
    so tests can override only what they need.

    Returns:
        MagicMock with all ArtifactStorage methods pre-configured.
    """
    storage = MagicMock()
    storage.initialize.return_value = None
    storage.is_initialized.return_value = False
    storage.health_check.return_value = True
    storage.put.return_value = "artifacts/default.bin"
    storage.get.return_value = b"default content"
    storage.get_with_metadata.return_value = (b"default content", {})
    storage.list.return_value = []
    storage.delete.return_value = None
    return storage


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root() -> Path:
    """
    Return the repository root directory.

    Returns:
        Absolute Path to the project root (parent of the tests/ directory).
    """
    return _PROJECT_ROOT


@pytest.fixture
def test_data_dir(project_root: Path) -> Path:
    """
    Return the test fixture data directory, creating it if absent.

    Args:
        project_root: Injected project_root fixture.

    Returns:
        Path to tests/fixtures/data/.
    """
    data_dir = project_root / "tests" / "fixtures" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def fixture_csv_dir(project_root: Path) -> Path:
    """
    Return the CSV fixture directory (alias for test_data_dir).

    Args:
        project_root: Injected project_root fixture.

    Returns:
        Path to tests/fixtures/data/.
    """
    csv_dir = project_root / "tests" / "fixtures" / "data"
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir


@pytest.fixture
def frontend_root(project_root: Path) -> Path:
    """
    Return the frontend source directory.

    Args:
        project_root: Injected project_root fixture.

    Returns:
        Path to frontend/.
    """
    return project_root / "frontend"


@pytest.fixture
def backend_root(project_root: Path) -> Path:
    """
    Return the backend services directory.

    Args:
        project_root: Injected project_root fixture.

    Returns:
        Path to services/.
    """
    return project_root / "services"


# ---------------------------------------------------------------------------
# Environment / config fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> dict:
    """
    Monkeypatch a safe set of environment variables for test isolation.

    Prevents tests from accidentally reading production credentials or
    connecting to real infrastructure.

    Args:
        monkeypatch: pytest's built-in monkeypatch fixture.

    Returns:
        Dict of the env vars that were set.
    """
    test_env = {
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "DEBUG",
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "fxlab_test",
        "DB_USER": "test",
        "DB_PASSWORD": "test",
        "REDIS_HOST": "localhost",
        "REDIS_PORT": "6379",
        "MINIO_HOST": "localhost",
        "MINIO_PORT": "9000",
        "MINIO_ACCESS_KEY": "minioadmin",
        "MINIO_SECRET_KEY": "minioadmin",
    }
    for key, value in test_env.items():
        monkeypatch.setenv(key, value)
    return test_env


# ---------------------------------------------------------------------------
# Domain fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_strategy_code() -> str:
    """
    Return a minimal, syntactically valid strategy source string.

    Returns:
        Python source code string for use in strategy compilation tests.
    """
    return (
        "def initialize(context):\n"
        '    context.symbol = "EURUSD"\n'
        '    context.period = "1h"\n'
        "\n"
        "def handle_data(context, data):\n"
        '    price = data.current(context.symbol, "close")\n'
        "    if price > context.get('last_price', 0):\n"
        "        context.order(context.symbol, 100)\n"
        "    context.last_price = price\n"
    )


# ---------------------------------------------------------------------------
# Docker-compose fixtures (acceptance / integration only)
# ---------------------------------------------------------------------------


@pytest.fixture
def docker_compose_file(project_root: Path) -> Path:
    """
    Return the path to the project's docker-compose.yml.

    Args:
        project_root: Injected project_root fixture.

    Returns:
        Path to docker-compose.yml.
    """
    return project_root / "docker-compose.yml"


@pytest.fixture
def api_base_url() -> str:
    """
    Return the base URL for the API service under docker-compose.

    Returns:
        http://localhost:8000
    """
    return "http://localhost:8000"


@pytest.fixture
def web_base_url() -> str:
    """
    Return the base URL for the web service under docker-compose.

    Returns:
        http://localhost:3000
    """
    return "http://localhost:3000"


@pytest.fixture
def health_check_timeout() -> int:
    """
    Return the default timeout (seconds) for health check retry loops.

    Returns:
        30
    """
    return 30


@pytest.fixture
def health_check_interval() -> int:
    """
    Return the default interval (seconds) between health check retries.

    Returns:
        1
    """
    return 1


# ---------------------------------------------------------------------------
# SQLite schema synchronization — ensures file-based test DB has all columns
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _ensure_sqlite_schema() -> Generator[None, None, None]:
    """
    Ensure the file-based SQLite test database has up-to-date schema.

    When the ORM models gain new columns (e.g. row_version), SQLAlchemy's
    ``create_all()`` only creates missing *tables* — it does NOT add missing
    columns to existing tables. This leaves a stale ``fxlab_test.db`` file
    that triggers ``OperationalError: no such column`` at query time.

    Fix: before the first test runs, drop all tables and recreate them from
    the current ORM metadata. This is safe because the file-based SQLite DB
    is for testing only — it has no production data to preserve.

    Only applies when the engine URL starts with ``sqlite:///`` (file-based).
    In-memory SQLite (``sqlite://``) and PostgreSQL are unaffected.

    Yields:
        None — schema sync runs once per pytest session as setup.
    """
    try:
        from services.api.db import Base, engine

        db_url = str(engine.url)
        if db_url.startswith("sqlite") and ":memory:" not in db_url:
            # Drop and recreate all tables to pick up schema changes.
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)
    except Exception:
        pass  # If db module fails to import, skip — tests will fail naturally
    yield


# ---------------------------------------------------------------------------
# pytest configuration hooks
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> Generator[None, None, None]:
    """
    Reset the rate-limiter sliding-window store before and after every test.

    The rate limiter uses a module-level singleton (_window) whose internal
    call-count store persists across tests within a pytest session.  Without
    this fixture, tests that exercise governance endpoints accumulate counts
    against the 20-req/min limit, causing subsequent tests from the same
    synthetic IP (127.0.0.1) to receive unexpected 429 responses.

    This fixture is autouse=True so it applies to every test automatically —
    no test needs to request it explicitly.

    Yields:
        None — runs setup, yields control to the test, then runs teardown.
    """
    try:
        from services.api.middleware.rate_limit import _window

        _window._store.clear()
    except Exception:
        pass  # Middleware not yet imported — safe to ignore
    yield
    try:
        from services.api.middleware.rate_limit import _window

        _window._store.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_fastapi_dependency_overrides() -> Generator[None, None, None]:
    """
    Clear FastAPI dependency_overrides after every test.

    Multiple route test modules override ``get_current_user`` or other
    FastAPI dependencies on the shared ``app`` singleton but fail to
    clean them up.  This leaves stale dependency overrides that leak
    into later test modules causing spurious auth failures (e.g., a
    viewer-scoped user override from indicator_routes polluting
    kill_switch_routes which expects TEST_TOKEN bypass).

    Clearing the dict on teardown is safe: each test that needs overrides
    re-applies them in its own setup/fixture.

    Yields:
        None — runs the test, then clears dependency_overrides.
    """
    yield
    try:
        from services.api.main import app

        if app.dependency_overrides:
            app.dependency_overrides.clear()
    except Exception:
        pass  # App not imported yet — nothing to clean


def pytest_configure(config: pytest.Config) -> None:
    """
    Register custom markers to avoid --strict-markers warnings.

    Args:
        config: pytest Config object injected by the framework.
    """
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring Docker"
    )
    config.addinivalue_line("markers", "unit: mark test as unit test (no external dependencies)")

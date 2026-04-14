"""
M0 Backend API Importability Tests

These tests verify Phase 1/2 endpoints and Phase 3 API stubs are importable.
All tests must FAIL until the backend structure is properly set up.
"""

import pytest
from fastapi.testclient import TestClient


def test_ac9_phase1_health_endpoint_returns_success():
    """AC9: Phase 1 /health endpoint returns success: true (importability check)."""
    # Import the FastAPI app
    try:
        from services.api.main import app
    except ImportError as e:
        pytest.fail(f"Cannot import services.api.main: {e}")

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200, f"Health endpoint returned {response.status_code}"
    data = response.json()
    assert "status" in data, "Health response missing 'status' field"
    assert data["status"] == "ok", f"Health endpoint status is {data['status']}, expected 'ok'"


def test_ac10_phase2_strategies_route_is_importable():
    """AC10: Phase 2 services/api/routes/strategies.py is importable without errors."""
    try:
        from services.api.routes import strategies
    except ImportError as e:
        pytest.fail(f"Cannot import services.api.routes.strategies: {e}")
    except Exception as e:
        pytest.fail(f"Error importing services.api.routes.strategies: {e}")

    # Verify it has a router object (standard FastAPI pattern)
    assert hasattr(strategies, "router"), "strategies module missing 'router' attribute"


def test_ac11_charts_route_stub_exists():
    """AC11: services/api/routes/charts.py stub exists (M23/M24 will implement it)."""
    try:
        from services.api.routes import charts
    except ImportError as e:
        pytest.fail(f"Cannot import services.api.routes.charts: {e}")
    except Exception as e:
        pytest.fail(f"Error importing services.api.routes.charts: {e}")

    # Verify it has a router object
    assert hasattr(charts, "router"), "charts module missing 'router' attribute"

    # Verify the router is a FastAPI APIRouter
    from fastapi import APIRouter

    assert isinstance(charts.router, APIRouter), "charts.router is not a FastAPI APIRouter instance"


def test_ac12_governance_route_stub_exists():
    """AC12: services/api/routes/governance.py stub exists."""
    try:
        from services.api.routes import governance
    except ImportError as e:
        pytest.fail(f"Cannot import services.api.routes.governance: {e}")
    except Exception as e:
        pytest.fail(f"Error importing services.api.routes.governance: {e}")

    # Verify it has a router object
    assert hasattr(governance, "router"), "governance module missing 'router' attribute"

    # Verify the router is a FastAPI APIRouter
    from fastapi import APIRouter

    assert isinstance(governance.router, APIRouter), (
        "governance.router is not a FastAPI APIRouter instance"
    )


def test_ac13_queues_route_stub_exists():
    """AC13: services/api/routes/queues.py stub exists."""
    try:
        from services.api.routes import queues
    except ImportError as e:
        pytest.fail(f"Cannot import services.api.routes.queues: {e}")
    except Exception as e:
        pytest.fail(f"Error importing services.api.routes.queues: {e}")

    # Verify it has a router object
    assert hasattr(queues, "router"), "queues module missing 'router' attribute"

    # Verify the router is a FastAPI APIRouter
    from fastapi import APIRouter

    assert isinstance(queues.router, APIRouter), "queues.router is not a FastAPI APIRouter instance"


def test_ac14_feed_health_route_stub_exists():
    """AC14: services/api/routes/feed_health.py stub exists."""
    try:
        from services.api.routes import feed_health
    except ImportError as e:
        pytest.fail(f"Cannot import services.api.routes.feed_health: {e}")
    except Exception as e:
        pytest.fail(f"Error importing services.api.routes.feed_health: {e}")

    # Verify it has a router object
    assert hasattr(feed_health, "router"), "feed_health module missing 'router' attribute"

    # Verify the router is a FastAPI APIRouter
    from fastapi import APIRouter

    assert isinstance(feed_health.router, APIRouter), (
        "feed_health.router is not a FastAPI APIRouter instance"
    )

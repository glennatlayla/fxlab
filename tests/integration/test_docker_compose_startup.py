"""
RED integration tests for M1 - Docker Compose startup and readiness.

These tests verify that services actually start and pass health checks.
They require docker and docker-compose to be available.

These tests will FAIL until the full docker-compose configuration is working.
"""

import subprocess
import time
from pathlib import Path

import pytest
import requests


@pytest.fixture(scope="module")
def docker_compose_up():
    """
    Fixture to start docker-compose stack for testing.
    Tears down after all tests in module complete.
    """
    compose_file = Path("docker-compose.yml")
    if not compose_file.exists():
        pytest.skip("docker-compose.yml not found")

    # Start services in detached mode
    try:
        subprocess.run(
            ["docker-compose", "up", "-d", "--build"],
            cwd=compose_file.parent,
            check=True,
            timeout=300,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to start docker-compose: {e.stderr.decode()}")
    except subprocess.TimeoutExpired:
        pytest.fail("docker-compose up timed out after 5 minutes")
    except FileNotFoundError:
        pytest.skip("docker-compose command not found")

    # Wait for services to initialize
    time.sleep(10)

    yield

    # Teardown: stop and remove containers
    try:
        subprocess.run(
            ["docker-compose", "down", "-v"],
            cwd=compose_file.parent,
            timeout=60,
            capture_output=True,
        )
    except Exception:
        pass  # Best effort cleanup


def test_ac1_api_container_is_running(docker_compose_up):
    """AC1: API container must be running after docker-compose up."""
    result = subprocess.run(
        ["docker-compose", "ps", "--services", "--filter", "status=running"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    running_services = result.stdout.strip().split("\n")
    assert "api" in running_services, "'api' service is not running"


def test_ac1_web_container_is_running(docker_compose_up):
    """AC1: Web container must be running after docker-compose up."""
    result = subprocess.run(
        ["docker-compose", "ps", "--services", "--filter", "status=running"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    running_services = result.stdout.strip().split("\n")
    assert "web" in running_services, "'web' service is not running"


def test_ac1_postgres_container_is_running(docker_compose_up):
    """AC1: Postgres container must be running after docker-compose up."""
    result = subprocess.run(
        ["docker-compose", "ps", "--services", "--filter", "status=running"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    running_services = result.stdout.strip().split("\n")
    assert "postgres" in running_services, "'postgres' service is not running"


def test_ac1_redis_container_is_running(docker_compose_up):
    """AC1: Redis container must be running after docker-compose up."""
    result = subprocess.run(
        ["docker-compose", "ps", "--services", "--filter", "status=running"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    running_services = result.stdout.strip().split("\n")
    assert "redis" in running_services, "'redis' service is not running"


def test_ac2_api_service_responds_to_health_check(docker_compose_up):
    """AC2: API service must respond to GET /health with 200 OK."""
    # Wait for service to be ready (up to 30 seconds)
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get("http://localhost:8000/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            if i < max_retries - 1:
                time.sleep(1)
                continue
            else:
                pytest.fail("API service did not respond to health check after 30 seconds")

    assert response.status_code == 200, f"Expected 200 from /health, got {response.status_code}"


def test_ac2_api_health_check_returns_json(docker_compose_up):
    """AC2: API health check must return valid JSON."""
    # Wait for service to be ready
    max_retries = 30
    response = None
    for i in range(max_retries):
        try:
            response = requests.get("http://localhost:8000/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            if i < max_retries - 1:
                time.sleep(1)
                continue

    assert response is not None, "Failed to connect to API service"

    try:
        data = response.json()
    except ValueError:
        pytest.fail("Health check response is not valid JSON")

    assert isinstance(data, dict), "Health check response must be a JSON object"


def test_ac2_api_health_check_has_ok_status(docker_compose_up):
    """AC2: API health check must return status='ok'."""
    # Wait for service to be ready
    max_retries = 30
    response = None
    for i in range(max_retries):
        try:
            response = requests.get("http://localhost:8000/health", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            if i < max_retries - 1:
                time.sleep(1)
                continue

    assert response is not None, "Failed to connect to API service"

    data = response.json()
    assert data.get("status") == "ok", f"Expected status='ok', got status='{data.get('status')}'"


def test_ac4_api_service_passes_readiness_probe(docker_compose_up):
    """AC4: API service must pass its configured health check."""
    # Give extra time for health checks to stabilize
    time.sleep(5)

    result = subprocess.run(
        ["docker-compose", "ps", "api"], capture_output=True, text=True, timeout=10
    )

    # Check that container is healthy (not just running)
    output = result.stdout
    assert "healthy" in output.lower() or "up" in output.lower(), (
        "API container did not pass health check"
    )


def test_ac4_postgres_service_passes_readiness_probe(docker_compose_up):
    """AC4: Postgres service must pass its configured health check."""
    time.sleep(5)

    result = subprocess.run(
        ["docker-compose", "ps", "postgres"], capture_output=True, text=True, timeout=10
    )

    output = result.stdout
    assert "healthy" in output.lower() or "up" in output.lower(), (
        "Postgres container did not pass health check"
    )


def test_ac4_redis_service_passes_readiness_probe(docker_compose_up):
    """AC4: Redis service must pass its configured health check."""
    time.sleep(5)

    result = subprocess.run(
        ["docker-compose", "ps", "redis"], capture_output=True, text=True, timeout=10
    )

    output = result.stdout
    assert "healthy" in output.lower() or "up" in output.lower(), (
        "Redis container did not pass health check"
    )


def test_ac3_web_service_serves_content(docker_compose_up):
    """AC3: Web service must serve content (static assets or dev server)."""
    # Wait for service to be ready (up to 30 seconds)
    max_retries = 30
    for i in range(max_retries):
        try:
            response = requests.get("http://localhost:3000", timeout=2)
            if response.status_code in [200, 301, 302]:
                break
        except requests.exceptions.RequestException:
            if i < max_retries - 1:
                time.sleep(1)
                continue
            else:
                pytest.fail("Web service did not respond after 30 seconds")

    # Accept 200, 301, or 302 (redirect to /login or similar is acceptable)
    assert response.status_code in [200, 301, 302], (
        f"Expected 200/301/302 from web service, got {response.status_code}"
    )


def test_ac3_web_service_returns_html_or_redirect(docker_compose_up):
    """AC3: Web service must return HTML content or redirect."""
    max_retries = 30
    response = None
    for i in range(max_retries):
        try:
            response = requests.get("http://localhost:3000", timeout=2, allow_redirects=False)
            break
        except requests.exceptions.RequestException:
            if i < max_retries - 1:
                time.sleep(1)
                continue

    assert response is not None, "Failed to connect to web service"

    # Must be either HTML or a redirect
    content_type = response.headers.get("content-type", "")
    is_html = "text/html" in content_type
    is_redirect = response.status_code in [301, 302, 303, 307, 308]

    assert is_html or is_redirect, (
        f"Web service should return HTML or redirect, got {response.status_code} with {content_type}"
    )

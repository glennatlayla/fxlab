"""
RED integration tests for M1 - Docker Compose service orchestration.

These tests verify:
- Docker Compose configuration exists and is valid
- Required services (api, web, postgres, redis) are defined
- Services have health checks configured
- Services have restart policies configured
- Environment-based configuration is present

These tests require docker-compose to be installed and runnable.
They must FAIL until docker-compose.yml is properly configured.
"""

import subprocess
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def docker_compose_file():
    """Fixture to locate docker-compose.yml."""
    compose_file = Path("docker-compose.yml")
    if not compose_file.exists():
        pytest.fail("docker-compose.yml does not exist in project root")
    return compose_file


@pytest.fixture
def compose_config(docker_compose_file):
    """Parse and return docker-compose.yml configuration."""
    with open(docker_compose_file) as f:
        config = yaml.safe_load(f)
    return config


def test_ac1_docker_compose_file_exists():
    """AC1: docker-compose.yml must exist in project root."""
    compose_file = Path("docker-compose.yml")
    assert compose_file.exists(), "docker-compose.yml not found in project root"


def test_ac1_docker_compose_is_valid_yaml(docker_compose_file):
    """AC1: docker-compose.yml must be valid YAML."""
    try:
        with open(docker_compose_file) as f:
            yaml.safe_load(f)
    except yaml.YAMLError as e:
        pytest.fail(f"docker-compose.yml is not valid YAML: {e}")


def test_ac1_api_service_defined(compose_config):
    """AC1: 'api' service must be defined in docker-compose.yml."""
    assert "services" in compose_config, "No 'services' section in docker-compose.yml"
    assert "api" in compose_config["services"], "'api' service not defined"


def test_ac1_web_service_defined(compose_config):
    """AC1: 'web' service must be defined in docker-compose.yml."""
    assert "services" in compose_config, "No 'services' section in docker-compose.yml"
    assert "web" in compose_config["services"], "'web' service not defined"


def test_ac1_postgres_service_defined(compose_config):
    """AC1: 'postgres' service must be defined in docker-compose.yml."""
    assert "services" in compose_config, "No 'services' section in docker-compose.yml"
    assert "postgres" in compose_config["services"], "'postgres' service not defined"


def test_ac1_redis_service_defined(compose_config):
    """AC1: 'redis' service must be defined in docker-compose.yml."""
    assert "services" in compose_config, "No 'services' section in docker-compose.yml"
    assert "redis" in compose_config["services"], "'redis' service not defined"


def test_ac2_api_service_has_healthcheck(compose_config):
    """AC2: 'api' service must have a healthcheck configuration."""
    api_service = compose_config["services"]["api"]
    assert "healthcheck" in api_service, "'api' service missing healthcheck"


def test_ac2_api_healthcheck_has_test(compose_config):
    """AC2: 'api' healthcheck must define a test command."""
    api_healthcheck = compose_config["services"]["api"]["healthcheck"]
    assert "test" in api_healthcheck, "'api' healthcheck missing 'test' field"


def test_ac2_api_healthcheck_uses_health_endpoint(compose_config):
    """AC2: 'api' healthcheck should test the /health endpoint."""
    api_healthcheck = compose_config["services"]["api"]["healthcheck"]
    test_cmd = " ".join(api_healthcheck["test"])
    assert "/health" in test_cmd, "'api' healthcheck should test /health endpoint"


def test_ac2_web_service_has_healthcheck(compose_config):
    """AC2: 'web' service must have a healthcheck configuration."""
    web_service = compose_config["services"]["web"]
    assert "healthcheck" in web_service, "'web' service missing healthcheck"


def test_ac2_postgres_service_has_healthcheck(compose_config):
    """AC2: 'postgres' service must have a healthcheck configuration."""
    postgres_service = compose_config["services"]["postgres"]
    assert "healthcheck" in postgres_service, "'postgres' service missing healthcheck"


def test_ac2_redis_service_has_healthcheck(compose_config):
    """AC2: 'redis' service must have a healthcheck configuration."""
    redis_service = compose_config["services"]["redis"]
    assert "healthcheck" in redis_service, "'redis' service missing healthcheck"


def test_ac4_api_service_has_restart_policy(compose_config):
    """AC4: 'api' service must have restart policy configured."""
    api_service = compose_config["services"]["api"]
    assert "restart" in api_service, "'api' service missing restart policy"


def test_ac4_api_restart_policy_is_on_failure(compose_config):
    """AC4: 'api' service restart policy should be 'on-failure' or 'unless-stopped'.

    `on-failure:N` (e.g. `on-failure:3`) is also accepted — it's the same
    policy with a max retry count appended, which the M-prep #2 production
    hardening (commit be19729 / be6632b) introduced explicitly to cap
    crashloop blast radius.
    """
    api_service = compose_config["services"]["api"]
    restart_policy = api_service.get("restart", "")
    accepted_prefixes = ("on-failure", "unless-stopped", "always")
    assert any(
        restart_policy == p or restart_policy.startswith(f"{p}:") for p in accepted_prefixes
    ), (
        f"'api' restart policy is '{restart_policy}', expected one of "
        f"{accepted_prefixes} (with optional ':N' max-retry suffix)"
    )


def test_ac4_web_service_has_restart_policy(compose_config):
    """AC4: 'web' service must have restart policy configured."""
    web_service = compose_config["services"]["web"]
    assert "restart" in web_service, "'web' service missing restart policy"


def test_ac4_postgres_service_has_restart_policy(compose_config):
    """AC4: 'postgres' service must have restart policy configured."""
    postgres_service = compose_config["services"]["postgres"]
    assert "restart" in postgres_service, "'postgres' service missing restart policy"


def test_ac4_redis_service_has_restart_policy(compose_config):
    """AC4: 'redis' service must have restart policy configured."""
    redis_service = compose_config["services"]["redis"]
    assert "restart" in redis_service, "'redis' service missing restart policy"


def test_ac1_api_service_exposes_port(compose_config):
    """AC1: 'api' service must expose a port for external access."""
    api_service = compose_config["services"]["api"]
    assert "ports" in api_service, "'api' service must expose ports"
    assert len(api_service["ports"]) > 0, "'api' service ports list is empty"


def test_ac1_web_service_exposes_port(compose_config):
    """AC1: 'web' service must expose a port for external access."""
    web_service = compose_config["services"]["web"]
    assert "ports" in web_service, "'web' service must expose ports"
    assert len(web_service["ports"]) > 0, "'web' service ports list is empty"


def test_ac1_api_service_has_environment_config(compose_config):
    """AC1: 'api' service must support environment-based configuration."""
    api_service = compose_config["services"]["api"]
    # Must have either 'environment' or 'env_file'
    has_env = "environment" in api_service or "env_file" in api_service
    assert has_env, "'api' service must have environment or env_file configuration"


def test_ac1_api_service_has_database_connection_env(compose_config):
    """AC1: 'api' service environment must include DATABASE_URL or similar."""
    api_service = compose_config["services"]["api"]

    env_dict = {}
    if "environment" in api_service:
        env_list = api_service["environment"]
        if isinstance(env_list, dict):
            env_dict = env_list
        elif isinstance(env_list, list):
            for item in env_list:
                if "=" in item:
                    key, val = item.split("=", 1)
                    env_dict[key] = val

    # Check for common database environment variable names
    db_env_keys = ["DATABASE_URL", "DB_URL", "POSTGRES_URL", "DATABASE_DSN"]
    has_db_env = any(key in env_dict for key in db_env_keys)

    assert has_db_env or "env_file" in api_service, (
        "'api' service must configure database connection via environment"
    )


def test_ac1_api_service_has_redis_connection_env(compose_config):
    """AC1: 'api' service environment must include REDIS_URL or similar."""
    api_service = compose_config["services"]["api"]

    env_dict = {}
    if "environment" in api_service:
        env_list = api_service["environment"]
        if isinstance(env_list, dict):
            env_dict = env_list
        elif isinstance(env_list, list):
            for item in env_list:
                if "=" in item:
                    key, val = item.split("=", 1)
                    env_dict[key] = val

    # Check for common Redis environment variable names
    redis_env_keys = ["REDIS_URL", "REDIS_HOST", "CACHE_URL"]
    has_redis_env = any(key in env_dict for key in redis_env_keys)

    assert has_redis_env or "env_file" in api_service, (
        "'api' service must configure Redis connection via environment"
    )


def test_ac1_compose_config_validates_with_docker_compose(docker_compose_file):
    """AC1: docker-compose.yml must pass 'docker-compose config' validation."""
    try:
        result = subprocess.run(
            ["docker-compose", "config"],
            cwd=docker_compose_file.parent,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"docker-compose config validation failed: {result.stderr}"
    except FileNotFoundError:
        pytest.skip("docker-compose command not found")
    except subprocess.TimeoutExpired:
        pytest.fail("docker-compose config command timed out")


def test_ac2_healthcheck_intervals_configured(compose_config):
    """AC2: Health checks must have interval and timeout configured."""
    services_with_healthchecks = ["api", "web", "postgres", "redis"]

    for service_name in services_with_healthchecks:
        service = compose_config["services"][service_name]
        healthcheck = service.get("healthcheck", {})

        assert "interval" in healthcheck, f"'{service_name}' healthcheck missing 'interval'"
        assert "timeout" in healthcheck, f"'{service_name}' healthcheck missing 'timeout'"


def test_ac2_healthcheck_retries_configured(compose_config):
    """AC2: Health checks must have retries configured."""
    services_with_healthchecks = ["api", "web", "postgres", "redis"]

    for service_name in services_with_healthchecks:
        service = compose_config["services"][service_name]
        healthcheck = service.get("healthcheck", {})

        assert "retries" in healthcheck, f"'{service_name}' healthcheck missing 'retries'"


def test_ac4_services_have_depends_on_with_conditions(compose_config):
    """AC4: Services must use depends_on with service_healthy conditions."""
    api_service = compose_config["services"]["api"]

    assert "depends_on" in api_service, "'api' service must depend on postgres and redis"

    depends_on = api_service["depends_on"]

    # Check if postgres is a dependency
    if isinstance(depends_on, list):
        assert "postgres" in depends_on, "'api' must depend on 'postgres'"
    elif isinstance(depends_on, dict):
        assert "postgres" in depends_on, "'api' must depend on 'postgres'"
        # Check for service_healthy condition
        postgres_dep = depends_on["postgres"]
        if isinstance(postgres_dep, dict):
            assert "condition" in postgres_dep, "'postgres' dependency should have a condition"
            assert postgres_dep["condition"] == "service_healthy", (
                "'postgres' dependency should wait for service_healthy"
            )

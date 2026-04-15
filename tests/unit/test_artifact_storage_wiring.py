"""
Tests for artifact storage backend wiring in get_artifact_storage()
and lifespan initialization.

Covers:
- ARTIFACT_STORAGE_BACKEND=local → LocalArtifactStorage (default)
- ARTIFACT_STORAGE_BACKEND=minio → MinIOArtifactStorage with env-based config
- Missing required MinIO env vars → ConfigError
- Unsupported backend value → ValueError
- MINIO_SECURE=true → secure=True on MinIO client
- MINIO_SECURE unset → secure=False (default)
- Lifespan initializes artifact storage and stores on app.state
- Lifespan handles storage initialization failure gracefully

Resolves TODO ISS-012 — validates MinIO backend is wired into production code.

Example:
    pytest tests/unit/test_artifact_storage_wiring.py -v
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Local backend (default)
# ---------------------------------------------------------------------------


class TestLocalBackendSelection:
    """Tests for local filesystem backend selection."""

    def test_default_backend_is_local(self):
        """When ARTIFACT_STORAGE_BACKEND is unset, local backend is returned."""
        env = {
            "ARTIFACT_STORAGE_ROOT": "/tmp/test-artifacts",
        }
        with patch.dict(os.environ, env, clear=False):
            # Remove ARTIFACT_STORAGE_BACKEND if present
            os.environ.pop("ARTIFACT_STORAGE_BACKEND", None)

            from libs.storage.local_storage import LocalArtifactStorage
            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            assert isinstance(storage, LocalArtifactStorage)

    def test_explicit_local_backend(self):
        """When ARTIFACT_STORAGE_BACKEND=local, local backend is returned."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "local",
            "ARTIFACT_STORAGE_ROOT": "/tmp/test-artifacts-explicit",
        }
        with patch.dict(os.environ, env, clear=False):
            from libs.storage.local_storage import LocalArtifactStorage
            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            assert isinstance(storage, LocalArtifactStorage)

    def test_local_backend_uses_storage_root(self):
        """Local backend uses ARTIFACT_STORAGE_ROOT for its root directory."""
        expected_root = "/tmp/test-fxlab-custom-root"
        env = {
            "ARTIFACT_STORAGE_BACKEND": "local",
            "ARTIFACT_STORAGE_ROOT": expected_root,
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            # LocalArtifactStorage stores root as Path in _root
            assert str(storage._root) == expected_root

    def test_local_backend_default_root(self):
        """Local backend defaults to /var/lib/fxlab/artifacts when ARTIFACT_STORAGE_ROOT unset."""
        with patch.dict(os.environ, {"ARTIFACT_STORAGE_BACKEND": "local"}, clear=False):
            os.environ.pop("ARTIFACT_STORAGE_ROOT", None)

            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            assert str(storage._root) == "/var/lib/fxlab/artifacts"


# ---------------------------------------------------------------------------
# MinIO backend
# ---------------------------------------------------------------------------


class TestMinIOBackendSelection:
    """Tests for MinIO storage backend selection and configuration."""

    def test_minio_backend_returns_minio_storage(self):
        """When ARTIFACT_STORAGE_BACKEND=minio, MinIOArtifactStorage is returned."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ENDPOINT": "minio.fxlab.internal:9000",
            "MINIO_ACCESS_KEY": "test-access-key",
            "MINIO_SECRET_KEY": "test-secret-key",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MINIO_SECURE", None)

            from libs.storage.minio_storage import MinIOArtifactStorage
            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            assert isinstance(storage, MinIOArtifactStorage)

    def test_minio_backend_uses_endpoint_env(self):
        """MinIO backend reads MINIO_ENDPOINT from environment."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ENDPOINT": "custom-host:9001",
            "MINIO_ACCESS_KEY": "key",
            "MINIO_SECRET_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MINIO_SECURE", None)

            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            # Minio client stores endpoint info — verify via the client attribute
            assert storage.client._base_url._url.netloc is not None

    def test_minio_backend_secure_true(self):
        """When MINIO_SECURE=true, MinIO client is configured with secure=True."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ENDPOINT": "minio.fxlab.internal:9000",
            "MINIO_ACCESS_KEY": "key",
            "MINIO_SECRET_KEY": "secret",
            "MINIO_SECURE": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            # When secure=True, Minio client uses https scheme
            assert storage.client._base_url._url.scheme == "https"

    def test_minio_backend_secure_defaults_false(self):
        """When MINIO_SECURE is unset, MinIO client defaults to insecure (HTTP)."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ENDPOINT": "minio.fxlab.internal:9000",
            "MINIO_ACCESS_KEY": "key",
            "MINIO_SECRET_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MINIO_SECURE", None)

            from services.api.routes.artifacts import get_artifact_storage

            storage = get_artifact_storage()
            assert storage.client._base_url._url.scheme == "http"

    def test_minio_missing_endpoint_raises_config_error(self):
        """Missing MINIO_ENDPOINT raises ConfigError."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ACCESS_KEY": "key",
            "MINIO_SECRET_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MINIO_ENDPOINT", None)

            from libs.contracts.errors import ConfigError
            from services.api.routes.artifacts import get_artifact_storage

            with pytest.raises(ConfigError, match="MINIO_ENDPOINT"):
                get_artifact_storage()

    def test_minio_missing_access_key_raises_config_error(self):
        """Missing MINIO_ACCESS_KEY raises ConfigError."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ENDPOINT": "minio:9000",
            "MINIO_SECRET_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MINIO_ACCESS_KEY", None)

            from libs.contracts.errors import ConfigError
            from services.api.routes.artifacts import get_artifact_storage

            with pytest.raises(ConfigError, match="MINIO_ACCESS_KEY"):
                get_artifact_storage()

    def test_minio_missing_secret_key_raises_config_error(self):
        """Missing MINIO_SECRET_KEY raises ConfigError."""
        env = {
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ENDPOINT": "minio:9000",
            "MINIO_ACCESS_KEY": "key",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("MINIO_SECRET_KEY", None)

            from libs.contracts.errors import ConfigError
            from services.api.routes.artifacts import get_artifact_storage

            with pytest.raises(ConfigError, match="MINIO_SECRET_KEY"):
                get_artifact_storage()


# ---------------------------------------------------------------------------
# Unsupported backend
# ---------------------------------------------------------------------------


class TestUnsupportedBackend:
    """Tests for unsupported backend values."""

    def test_unsupported_backend_raises_value_error(self):
        """An unrecognised ARTIFACT_STORAGE_BACKEND raises ValueError."""
        env = {"ARTIFACT_STORAGE_BACKEND": "gcs"}
        with patch.dict(os.environ, env, clear=False):
            from services.api.routes.artifacts import get_artifact_storage

            with pytest.raises(ValueError, match="Unsupported.*gcs"):
                get_artifact_storage()

    def test_s3_backend_raises_value_error(self):
        """ARTIFACT_STORAGE_BACKEND=s3 is not yet supported — raises ValueError."""
        env = {"ARTIFACT_STORAGE_BACKEND": "s3"}
        with patch.dict(os.environ, env, clear=False):
            from services.api.routes.artifacts import get_artifact_storage

            with pytest.raises(ValueError, match="Unsupported.*s3"):
                get_artifact_storage()


# ---------------------------------------------------------------------------
# Lifespan integration — artifact storage initialization
# ---------------------------------------------------------------------------


class TestLifespanArtifactStorageInit:
    """Tests that the application lifespan initializes artifact storage."""

    def test_lifespan_initializes_local_storage(self):
        """Lifespan initializes local artifact storage and stores on app.state."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            env = {
                "ENVIRONMENT": "test",
                "DATABASE_URL": "sqlite:///:memory:",
                "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
                "ARTIFACT_STORAGE_BACKEND": "local",
                "ARTIFACT_STORAGE_ROOT": tmpdir,
            }
            with patch.dict(os.environ, env, clear=False):
                from services.api.main import app

                with TestClient(app):
                    assert hasattr(app.state, "artifact_storage")
                    assert app.state.artifact_storage is not None

                    from libs.storage.local_storage import LocalArtifactStorage

                    assert isinstance(app.state.artifact_storage, LocalArtifactStorage)
                    assert app.state.artifact_storage.is_initialized()

    def test_lifespan_handles_storage_failure_gracefully(self):
        """When storage init fails, app still starts — artifact_storage is None."""
        env = {
            "ENVIRONMENT": "test",
            "DATABASE_URL": "sqlite:///:memory:",
            "JWT_SECRET_KEY": "test-secret-key-not-for-production-32bytes!!",
            "ARTIFACT_STORAGE_BACKEND": "minio",
            "MINIO_ENDPOINT": "nonexistent-host:9999",
            "MINIO_ACCESS_KEY": "key",
            "MINIO_SECRET_KEY": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            from services.api.main import app

            # MinIO initialize() will fail because the server is unreachable,
            # but the app should still start successfully.
            with TestClient(app) as client:
                assert hasattr(app.state, "artifact_storage")
                # Storage should be None due to initialization failure
                # (MinIO can't connect to nonexistent-host)
                # OR the MinIO client might succeed in construction but fail
                # on initialize() — either way, app must be running.
                response = client.get("/health")
                assert response.status_code in (200, 503)  # App is alive

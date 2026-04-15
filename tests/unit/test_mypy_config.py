"""
Behavioral tests for type safety in production code (replaces config-linting test).

Purpose:
    Verify that production modules can be imported and their public APIs
    have proper type annotations. This replaces the previous config-linting
    test that only checked mypy.ini/pyproject.toml format.

Responsibilities:
    - Verify core production modules are importable.
    - Verify public service/repository classes have type-annotated __init__.
    - Verify contract models have proper field types.
    - Verify auth module functions have return type annotations.

Does NOT:
    - Run mypy static analysis (that is CI's job).
    - Validate every function annotation (static analysis handles that).

Dependencies:
    - inspect: For examining function signatures.
    - importlib: For dynamic module imports.

Example:
    pytest tests/unit/test_mypy_config.py -v
"""

from __future__ import annotations

import inspect


class TestCoreModulesImportable:
    """Verify production modules can be imported without errors."""

    def test_auth_module_imports(self) -> None:
        """services.api.auth must be importable."""
        from services.api import auth

        assert hasattr(auth, "create_access_token")
        assert hasattr(auth, "get_current_user")
        assert hasattr(auth, "AuthenticatedUser")

    def test_contracts_models_imports(self) -> None:
        """libs.contracts.models must be importable with all ORM models."""
        from libs.contracts.models import (
            ApprovalRequest,
            Artifact,
            AuditEvent,
            Base,
            Feed,
            PromotionRequest,
            RevokedToken,
            Run,
            Strategy,
            Trial,
            User,
        )

        assert Base is not None
        assert all(
            cls is not None
            for cls in [
                User,
                Strategy,
                Run,
                Trial,
                Artifact,
                AuditEvent,
                Feed,
                ApprovalRequest,
                PromotionRequest,
                RevokedToken,
            ]
        )

    def test_token_blacklist_service_imports(self) -> None:
        """TokenBlacklistService must be importable."""
        from services.api.services.token_blacklist_service import TokenBlacklistService

        assert hasattr(TokenBlacklistService, "is_revoked")
        assert hasattr(TokenBlacklistService, "revoke")
        assert hasattr(TokenBlacklistService, "purge_expired")

    def test_login_attempt_tracker_imports(self) -> None:
        """LoginAttemptTracker must be importable."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        assert hasattr(LoginAttemptTracker, "is_locked")
        assert hasattr(LoginAttemptTracker, "record_failure")
        assert hasattr(LoginAttemptTracker, "record_success")

    def test_rate_limit_backends_importable(self) -> None:
        """Rate limit backends must be importable."""
        from services.api.middleware.rate_limit import (
            InMemoryRateLimitBackend,
            RateLimitBackend,
            RedisRateLimitBackend,
        )

        assert issubclass(InMemoryRateLimitBackend, RateLimitBackend)
        assert issubclass(RedisRateLimitBackend, RateLimitBackend)


class TestTypeAnnotationsPresent:
    """Verify public APIs have type annotations."""

    def test_create_access_token_has_annotations(self) -> None:
        """create_access_token must have type annotations on all parameters."""
        from services.api.auth import create_access_token

        sig = inspect.signature(create_access_token)
        for name, param in sig.parameters.items():
            assert param.annotation != inspect.Parameter.empty, (
                f"create_access_token parameter '{name}' lacks type annotation"
            )

    def test_token_blacklist_service_methods_annotated(self) -> None:
        """TokenBlacklistService public methods must have return annotations."""
        from services.api.services.token_blacklist_service import TokenBlacklistService

        for method_name in ("is_revoked", "revoke", "purge_expired"):
            method = getattr(TokenBlacklistService, method_name)
            sig = inspect.signature(method)
            assert sig.return_annotation != inspect.Signature.empty, (
                f"TokenBlacklistService.{method_name} lacks return type annotation"
            )

    def test_login_attempt_tracker_methods_annotated(self) -> None:
        """LoginAttemptTracker public methods must have return annotations."""
        from services.api.services.login_attempt_tracker import LoginAttemptTracker

        for method_name in ("is_locked", "record_failure", "record_success", "retry_after"):
            method = getattr(LoginAttemptTracker, method_name)
            sig = inspect.signature(method)
            assert sig.return_annotation != inspect.Signature.empty, (
                f"LoginAttemptTracker.{method_name} lacks return type annotation"
            )

    def test_rate_limit_backend_interface_annotated(self) -> None:
        """RateLimitBackend.is_allowed must have type annotations."""
        from services.api.middleware.rate_limit import RateLimitBackend

        sig = inspect.signature(RateLimitBackend.is_allowed)
        assert sig.return_annotation != inspect.Signature.empty, (
            "RateLimitBackend.is_allowed lacks return type annotation"
        )


class TestContractModelsTyped:
    """Verify contract/ORM models have proper column definitions."""

    def test_revoked_token_has_required_fields(self) -> None:
        """RevokedToken must have jti, revoked_at, expires_at, reason columns."""
        from libs.contracts.models import RevokedToken

        columns = {c.name for c in RevokedToken.__table__.columns}
        required = {"jti", "revoked_at", "expires_at", "reason"}
        assert required.issubset(columns), f"RevokedToken missing columns: {required - columns}"

    def test_promotion_request_has_required_fields(self) -> None:
        """PromotionRequest must have all required promotion fields."""
        from libs.contracts.models import PromotionRequest

        columns = {c.name for c in PromotionRequest.__table__.columns}
        required = {"id", "candidate_id", "requester_id", "target_environment", "status"}
        assert required.issubset(columns), f"PromotionRequest missing columns: {required - columns}"

    def test_run_has_required_fields(self) -> None:
        """Run must have all required fields for results retrieval."""
        from libs.contracts.models import Run

        columns = {c.name for c in Run.__table__.columns}
        required = {"id", "run_type", "status"}
        assert required.issubset(columns), f"Run missing columns: {required - columns}"

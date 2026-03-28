"""
Configuration service interface.

All Phase 3 services must implement environment-based configuration
with validation and debug introspection.
"""

from abc import ABC, abstractmethod
from typing import Any, Protocol

from libs.contracts.phase3.runtime import ServiceConfiguration


class ConfigurationService(Protocol):
    """
    Protocol for service configuration providers.

    Configuration must be loaded from environment variables with validation
    and defaults. Services must expose their active configuration for
    debugging and audit purposes.
    """

    @abstractmethod
    def get_configuration(self) -> ServiceConfiguration:
        """
        Retrieve active service configuration.

        Sensitive values (passwords, API keys) must be redacted before
        returning to clients.

        Returns:
            ServiceConfiguration with all active settings
        """
        ...

    @abstractmethod
    def validate_configuration(self) -> list[str]:
        """
        Validate current configuration for completeness and correctness.

        Returns:
            List of validation error messages (empty if valid)
        """
        ...

    @abstractmethod
    def get_environment_value(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a single environment variable value.

        Args:
            key: Environment variable name
            default: Default value if not set

        Returns:
            Environment variable value or default
        """
        ...

    @abstractmethod
    def is_production(self) -> bool:
        """
        Check if service is running in production mode.

        Returns:
            True if environment is PRODUCTION
        """
        ...

    @abstractmethod
    def is_development(self) -> bool:
        """
        Check if service is running in development mode.

        Returns:
            True if environment is DEVELOPMENT
        """
        ...

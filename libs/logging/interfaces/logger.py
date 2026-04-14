"""Structured logging interface with correlation ID support."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class LogLevel(str, Enum):
    """Log severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class StructuredLogger(ABC):
    """Abstract interface for structured logging with correlation tracking.

    All log entries must include correlation IDs and structured context.
    """

    @abstractmethod
    def log(
        self,
        level: LogLevel,
        message: str,
        correlation_id: str,
        **context: Any,
    ) -> None:
        """Emit a structured log entry.

        Args:
            level: Log severity level.
            message: Human-readable message.
            correlation_id: Request/operation correlation ID.
            **context: Additional structured context fields.
        """
        ...

    @abstractmethod
    def debug(self, message: str, correlation_id: str, **context: Any) -> None:
        """Log debug-level message."""
        ...

    @abstractmethod
    def info(self, message: str, correlation_id: str, **context: Any) -> None:
        """Log info-level message."""
        ...

    @abstractmethod
    def warning(self, message: str, correlation_id: str, **context: Any) -> None:
        """Log warning-level message."""
        ...

    @abstractmethod
    def error(
        self,
        message: str,
        correlation_id: str,
        error: Exception | None = None,
        **context: Any,
    ) -> None:
        """Log error-level message with optional exception.

        Args:
            message: Error description.
            correlation_id: Request/operation correlation ID.
            error: Optional exception to include in context.
            **context: Additional structured context fields.
        """
        ...

    @abstractmethod
    def critical(
        self,
        message: str,
        correlation_id: str,
        error: Exception | None = None,
        **context: Any,
    ) -> None:
        """Log critical-level message with optional exception."""
        ...

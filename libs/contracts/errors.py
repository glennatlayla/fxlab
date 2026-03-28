"""Typed exceptions for FXLab."""


class FXLabError(Exception):
    """Base exception for all FXLab errors."""
    pass


class NotFoundError(FXLabError):
    """Resource not found."""
    pass


class ValidationError(FXLabError):
    """Validation failed."""
    pass

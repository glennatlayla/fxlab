"""
Deprecated — use services.api.auth instead.

This module previously provided a header-trust authentication pattern
(X-User-ID header). All authentication is now handled by JWT middleware
in services.api.auth (M14-T2).

Kept as a thin re-export so any overlooked imports fail loudly with a
deprecation warning rather than silently breaking.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "services.api.dependencies is deprecated. "
    "Import get_current_user from services.api.auth instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backward compatibility — will be removed in Phase 4.
from services.api.auth import get_current_user  # noqa: F401

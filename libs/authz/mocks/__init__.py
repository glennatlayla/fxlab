"""
Mocks package for authz.

In-memory fakes for unit-testing the authz subsystem.
Concrete implementations must never be imported here.
"""

from libs.authz.mocks.mock_rbac import MockRBACService

__all__ = ["MockRBACService"]

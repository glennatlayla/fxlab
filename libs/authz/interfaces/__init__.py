"""
Interfaces package for authz.

Abstract ports (ABCs / Protocols) for the authz subsystem.
Concrete implementations must never be imported here.
"""

from libs.authz.interfaces.rbac import ROLE_PERMISSIONS, Permission, RBACInterface, Role

__all__ = ["Permission", "RBACInterface", "Role", "ROLE_PERMISSIONS"]

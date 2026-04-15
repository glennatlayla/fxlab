/**
 * AuthGuard — route-level authentication gate.
 *
 * Purpose:
 *   Wrap protected routes to redirect unauthenticated users to the login
 *   page and block users who lack a required scope with a 403 message.
 *
 * Props:
 *   requiredScope — optional RBAC scope string. When set, the user must
 *     hold this scope in their JWT claims; otherwise a 403 view renders.
 *   children — the protected page content.
 *
 * Example:
 *   <Route element={<AuthGuard requiredScope="feeds:read"><FeedsPage /></AuthGuard>} />
 */

import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";

interface AuthGuardProps {
  children: ReactNode;
  /** If set, user must hold this scope to access the route. */
  requiredScope?: string;
}

export function AuthGuard({ children, requiredScope }: AuthGuardProps) {
  const { isAuthenticated, isLoading, hasScope } = useAuth();
  const location = useLocation();

  // While auth state is being determined, show nothing (prevents flash).
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-brand-500 border-t-transparent" />
      </div>
    );
  }

  // Not authenticated → redirect to login, preserving the intended destination.
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // Authenticated but missing required scope → 403 view.
  if (requiredScope && !hasScope(requiredScope)) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4">
        <div className="text-6xl text-surface-300">403</div>
        <h1 className="text-xl font-semibold text-surface-700">Access Denied</h1>
        <p className="max-w-md text-center text-surface-500">
          You do not have the <code className="kbd">{requiredScope}</code> permission required to
          access this page. Contact your administrator to request access.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}

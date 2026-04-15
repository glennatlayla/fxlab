/**
 * AdminLayout — admin panel layout with sidebar navigation.
 *
 * Purpose:
 *   Provide a consistent layout for admin pages with a sidebar containing
 *   navigation to Users and Secrets management. Enforces admin:manage scope.
 *
 * Responsibilities:
 *   - Render sidebar with admin navigation links.
 *   - Highlight active route.
 *   - Enforce admin:manage scope; show access denied if missing.
 *   - Render children (outlet) in main content area.
 *
 * Does NOT:
 *   - Contain business logic or data fetching.
 *
 * Dependencies:
 *   - useAuth from @/auth/useAuth.
 *   - useLocation from react-router-dom (for active link detection).
 *
 * Example:
 *   <AdminLayout>
 *     <Outlet /> (Child routes render here)
 *   </AdminLayout>
 */

import { ReactNode } from "react";
import { useAuth } from "@/auth/useAuth";
import { Link, useLocation } from "react-router-dom";

interface AdminLayoutProps {
  /** Child content (Outlet from router). */
  children: ReactNode;
}

/**
 * AdminLayout component.
 *
 * Returns:
 *   JSX element containing the admin layout with sidebar and content area.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  const { hasScope } = useAuth();
  const location = useLocation();

  // Check admin scope
  if (!hasScope("admin:manage")) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4">
        <div className="text-6xl text-surface-300">403</div>
        <h1 className="text-xl font-semibold text-surface-700">Access Denied</h1>
        <p className="max-w-md text-center text-surface-500">
          You do not have the <code className="kbd">admin:manage</code> permission required to
          access the admin panel. Contact your administrator to request access.
        </p>
      </div>
    );
  }

  const isActive = (path: string): boolean => location.pathname === path;

  return (
    <div className="flex gap-6" data-testid="admin-layout">
      {/* Sidebar */}
      <nav
        className="w-48 space-y-2 rounded-lg border border-surface-200 bg-white p-4"
        data-testid="admin-sidebar"
      >
        <h2 className="text-sm font-semibold uppercase text-surface-600">Admin Panel</h2>
        <ul className="space-y-2 border-t border-surface-200 pt-4">
          <li>
            <Link
              to="/admin/users"
              data-testid="admin-nav-users"
              className={`block rounded px-3 py-2 text-sm transition-colors ${
                isActive("/admin/users")
                  ? "bg-blue-100 font-semibold text-blue-700"
                  : "text-surface-700 hover:bg-surface-50"
              }`}
            >
              Users
            </Link>
          </li>
          <li>
            <Link
              to="/admin/secrets"
              data-testid="admin-nav-secrets"
              className={`block rounded px-3 py-2 text-sm transition-colors ${
                isActive("/admin/secrets")
                  ? "bg-blue-100 font-semibold text-blue-700"
                  : "text-surface-700 hover:bg-surface-50"
              }`}
            >
              Secrets
            </Link>
          </li>
        </ul>
      </nav>

      {/* Content area */}
      <div className="flex-1" data-testid="admin-content">
        {children}
      </div>
    </div>
  );
}

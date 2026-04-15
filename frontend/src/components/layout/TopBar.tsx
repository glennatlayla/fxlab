/**
 * TopBar component — top navigation bar with breadcrumbs and user menu.
 *
 * Purpose:
 *   Display the current page title/breadcrumbs, user identity, and a
 *   logout button in the application header.
 *   Responsive: spans full width on mobile, offset by sidebar on lg+.
 *
 * Responsibilities:
 *   - Show breadcrumbs for current page.
 *   - Display user identity and role badge.
 *   - Provide logout button.
 *   - Adjust left margin based on sidebar visibility.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Handle authentication (useAuth hook delegates to context).
 *
 * Example:
 *   <TopBar />
 *   In AppShell above main content area.
 */

import { LogOut, User } from "lucide-react";
import { useAuth } from "@/auth/useAuth";
import { Breadcrumbs } from "./Breadcrumbs";

export function TopBar() {
  const { user, logout } = useAuth();

  return (
    <header className="fixed left-0 right-0 top-0 z-20 flex h-topbar items-center justify-between border-b border-surface-200 bg-white px-4 lg:left-sidebar lg:px-6">
      <Breadcrumbs />

      <div className="flex items-center gap-3">
        {user && (
          <div className="hidden items-center gap-2 text-sm text-surface-600 sm:flex">
            <User className="h-4 w-4" />
            <span>{user.email}</span>
            <span className="rounded bg-surface-100 px-1.5 py-0.5 text-2xs font-medium text-surface-500">
              {user.role}
            </span>
          </div>
        )}
        <button
          onClick={logout}
          title="Sign out"
          className="rounded-md p-1.5 text-surface-400 hover:bg-surface-100 hover:text-surface-600"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}

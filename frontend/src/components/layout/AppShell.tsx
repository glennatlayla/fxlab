/**
 * AppShell — authenticated layout wrapper.
 *
 * Purpose:
 *   Compose Sidebar + TopBar + content area into the main application
 *   layout. Used as the element for all authenticated routes in the router.
 *   Responsive layout: hides sidebar and shows BottomTabBar on mobile,
 *   shows sidebar on desktop (lg+).
 *
 * Responsibilities:
 *   - Render main application frame with responsive layout.
 *   - Sidebar hidden on mobile (hidden lg:block).
 *   - BottomTabBar shown only on mobile (lg:hidden).
 *   - Adjust main content margins and padding for mobile vs desktop.
 *   - The Outlet renders the matched child route page component.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Handle routing (Router and Outlet delegate to children).
 *
 * Example:
 *   <AppShell />
 *   Wrapped in AuthGuard by the router.
 */

import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { BottomTabBar } from "./BottomTabBar";

export function AppShell() {
  return (
    <div className="min-h-screen bg-surface-50">
      {/* Sidebar: hidden on mobile, visible on lg+ screens */}
      <div className="hidden lg:block">
        <Sidebar />
      </div>

      {/* TopBar: spans full width on mobile, constrained on lg+ */}
      <TopBar />

      {/* BottomTabBar: only visible on mobile (lg:hidden) */}
      <BottomTabBar />

      {/* Main content: adjust margins and padding for responsive layout */}
      <main className="ml-0 mt-topbar p-4 pb-16 lg:ml-sidebar lg:p-6 lg:pb-0">
        <Outlet />
      </main>
    </div>
  );
}

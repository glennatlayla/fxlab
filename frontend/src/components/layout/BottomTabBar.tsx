/**
 * BottomTabBar — mobile navigation component.
 *
 * Purpose:
 *   Provide a mobile-friendly bottom tab navigation bar with five key sections:
 *   Home (Dashboard), Runs, Emergency Controls, Alerts, and a "More" menu for
 *   additional navigation items not in the tab bar.
 *
 * Responsibilities:
 *   - Render fixed bottom navigation visible only on mobile (lg:hidden).
 *   - Show active tab highlighted in brand color.
 *   - Emergency tab always highlighted in danger red to draw attention.
 *   - Include safe area padding for notch-aware devices (iPhone, etc.).
 *   - Each tab is a NavLink for proper routing integration.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Make API calls.
 *   - Show/hide based on user scopes (that's handled by route guards).
 *
 * Example:
 *   <BottomTabBar />
 *   In AppShell with lg:hidden class to hide on desktop.
 */

import { NavLink } from "react-router-dom";
import { LayoutDashboard, Play, ShieldAlert, Bell, MoreHorizontal } from "lucide-react";
import { clsx } from "clsx";

interface TabItem {
  label: string;
  to: string;
  icon: React.ElementType;
  isEmergency?: boolean;
}

const TABS: TabItem[] = [
  { label: "Home", to: "/", icon: LayoutDashboard },
  { label: "Runs", to: "/runs", icon: Play },
  { label: "Emergency", to: "/emergency", icon: ShieldAlert, isEmergency: true },
  { label: "Alerts", to: "/alerts", icon: Bell },
  { label: "More", to: "/more", icon: MoreHorizontal },
];

export function BottomTabBar() {
  return (
    <nav
      className={clsx(
        "fixed bottom-0 left-0 right-0 z-30 flex h-16 items-center justify-around",
        "border-t border-surface-200 bg-white",
        "pb-[env(safe-area-inset-bottom)]",
        "lg:hidden", // Hidden on desktop (lg+)
      )}
      role="navigation"
      aria-label="Mobile navigation"
    >
      {TABS.map((tab) => {
        const Icon = tab.icon;
        return (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            className={({ isActive }) =>
              clsx(
                "flex flex-col items-center justify-center gap-0.5 px-2 py-1.5 text-2xs",
                "transition-colors",
                // Emergency tab always red, other tabs respond to active state
                tab.isEmergency
                  ? "text-danger-500"
                  : isActive
                    ? "font-medium text-brand-600"
                    : "text-surface-400",
              )
            }
            title={tab.label}
          >
            <Icon className="h-5 w-5 flex-shrink-0" />
            <span>{tab.label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}

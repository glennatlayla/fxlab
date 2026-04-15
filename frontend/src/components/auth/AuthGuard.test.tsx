/**
 * Permissions smoke tests for AuthGuard — M31 permissions hardening.
 *
 * Covers:
 *   - Unauthenticated user redirects to /login
 *   - Authenticated user with no scopes sees 403 on all protected routes
 *   - Authenticated user with specific scope sees the protected content
 *   - Loading state renders spinner (no flash of content)
 *   - 403 view includes the missing scope name for admin visibility
 *   - No action buttons visible in 403 view (graceful handling)
 *
 * Per M31 spec: "no-scope user sees only login; researcher role sees only
 * researcher surfaces; action buttons outside scope are absent from DOM"
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { AuthGuard } from "./AuthGuard";

// Mock useAuth to control auth state
const mockUseAuth = vi.fn();
vi.mock("@/auth/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));

function renderGuarded(scope?: string, locationPath = "/protected") {
  return render(
    <MemoryRouter initialEntries={[locationPath]}>
      <Routes>
        <Route
          path="/protected"
          element={
            <AuthGuard requiredScope={scope}>
              <div data-testid="protected-content">Secret content</div>
            </AuthGuard>
          }
        />
        <Route path="/login" element={<div data-testid="login-page">Login</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthGuard — permissions smoke tests", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("redirects unauthenticated user to /login", () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: false,
      hasScope: () => false,
    });

    renderGuarded("view_feeds");
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
  });

  it("renders 403 when authenticated user lacks the required scope", () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasScope: () => false,
    });

    renderGuarded("view_feeds");
    expect(screen.getByText("403")).toBeInTheDocument();
    expect(screen.getByText("Access Denied")).toBeInTheDocument();
    // Missing scope name is displayed for administrator visibility
    expect(screen.getByText("view_feeds")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
  });

  it("renders protected content when user has the required scope", () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasScope: (s: string) => s === "view_feeds",
    });

    renderGuarded("view_feeds");
    expect(screen.getByTestId("protected-content")).toBeInTheDocument();
    expect(screen.queryByText("403")).not.toBeInTheDocument();
  });

  it("renders loading spinner while auth is determining (no content flash)", () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: false,
      isLoading: true,
      hasScope: () => false,
    });

    renderGuarded("view_feeds");
    // Content should not be visible while loading
    expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
    expect(screen.queryByText("403")).not.toBeInTheDocument();
  });

  it("renders content without scope check when requiredScope is not set", () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasScope: () => false,
    });

    renderGuarded(undefined);
    expect(screen.getByTestId("protected-content")).toBeInTheDocument();
  });

  it("403 view has no action buttons (graceful handling)", () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasScope: () => false,
    });

    renderGuarded("approve_promotion");
    expect(screen.getByText("403")).toBeInTheDocument();
    // No action buttons should exist in the 403 view
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  // Smoke test for all route scopes used in the application
  const ROUTE_SCOPES = [
    "create_strategy",
    "view_runs",
    "view_feeds",
    "approve_promotion",
    "manage_overrides",
    "view_audit",
    "export_data",
  ];

  it.each(ROUTE_SCOPES)("blocks no-scope user from %s-protected route with 403", (scope) => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      hasScope: () => false,
    });

    renderGuarded(scope);
    expect(screen.getByText("403")).toBeInTheDocument();
    expect(screen.getByText(scope)).toBeInTheDocument();
    expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
  });
});

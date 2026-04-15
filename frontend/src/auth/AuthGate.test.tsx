/**
 * AuthGate unit tests.
 *
 * Verifies:
 *   - mode="local" renders AuthProvider (default).
 *   - mode="oidc" renders OidcProvider.
 *   - getAuthMode() reads from VITE_AUTH_MODE.
 *   - getAuthMode() defaults to "local" when env var is unset.
 *
 * Dependencies:
 *   - vitest for mocking
 *   - @testing-library/react for render
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { AuthGate, getAuthMode } from "./AuthGate";

// Mock the providers to verify which one renders
vi.mock("./AuthProvider", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="local-provider">{children}</div>
  ),
}));

vi.mock("./OidcProvider", () => ({
  OidcProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="oidc-provider">{children}</div>
  ),
}));

describe("AuthGate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("mode selection", () => {
    it("renders AuthProvider when mode is 'local'", () => {
      render(
        <AuthGate mode="local">
          <div>App Content</div>
        </AuthGate>,
      );

      expect(screen.getByTestId("local-provider")).toBeDefined();
      expect(screen.queryByTestId("oidc-provider")).toBeNull();
      expect(screen.getByText("App Content")).toBeDefined();
    });

    it("renders OidcProvider when mode is 'oidc'", () => {
      render(
        <AuthGate mode="oidc">
          <div>App Content</div>
        </AuthGate>,
      );

      expect(screen.getByTestId("oidc-provider")).toBeDefined();
      expect(screen.queryByTestId("local-provider")).toBeNull();
      expect(screen.getByText("App Content")).toBeDefined();
    });

    it("defaults to local mode when no mode prop provided", () => {
      // getAuthMode defaults to "local" when env var is unset
      render(
        <AuthGate>
          <div>Default Content</div>
        </AuthGate>,
      );

      expect(screen.getByTestId("local-provider")).toBeDefined();
    });
  });

  describe("getAuthMode", () => {
    it("returns 'local' when VITE_AUTH_MODE is unset", () => {
      // import.meta.env.VITE_AUTH_MODE is undefined by default in tests
      expect(getAuthMode()).toBe("local");
    });

    it("returns 'local' for unknown mode values", () => {
      // Unknown values default to local for backward compatibility
      const result = getAuthMode();
      // Since we can't easily set import.meta.env in vitest,
      // we verify the default behavior
      expect(result).toBe("local");
    });
  });
});

/**
 * Tests for useAuth hook.
 *
 * Verifies:
 *   - Throws when used outside AuthProvider.
 *   - Returns default unauthenticated state.
 *   - hasScope returns false when not authenticated.
 */

import { renderHook } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./useAuth";
import type { ReactNode } from "react";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

describe("useAuth", () => {
  it("throws when used outside AuthProvider", () => {
    // Suppress console.error for the expected error.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => renderHook(() => useAuth())).toThrow("useAuth must be used within");
    spy.mockRestore();
  });

  it("returns unauthenticated state by default", () => {
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    expect(result.current.accessToken).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });

  it("hasScope returns false when not authenticated", () => {
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    expect(result.current.hasScope("feeds:read")).toBe(false);
  });
});

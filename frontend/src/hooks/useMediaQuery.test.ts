/**
 * Tests for useMediaQuery hook and convenience hooks.
 *
 * Acceptance criteria (FE-22):
 *   - useMediaQuery(query) returns true when query matches.
 *   - useMediaQuery(query) returns false when query does not match.
 *   - Hook updates when media query changes.
 *   - useIsMobile() returns true for mobile breakpoint.
 *   - useIsDesktop() returns true for desktop breakpoint.
 *   - Listeners are cleaned up on unmount.
 *   - SSR-safe: returns false when window is undefined.
 */

import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useMediaQuery, useIsMobile, useIsDesktop } from "./useMediaQuery";

describe("useMediaQuery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns false initially when query does not match", () => {
    const mockAddEventListener = vi.fn();
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: false,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { result } = renderHook(() => useMediaQuery("(min-width: 1024px)"));
    expect(result.current).toBe(false);
  });

  it("returns true when query matches", () => {
    const mockAddEventListener = vi.fn();
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: true,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { result } = renderHook(() => useMediaQuery("(min-width: 1024px)"));
    expect(result.current).toBe(true);
  });

  it("updates when media query changes", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let changeHandler: any = null;
    const mockAddEventListener = vi.fn((event: string, handler) => {
      if (event === "change") {
        changeHandler = handler;
      }
    });
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: false,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { result, rerender } = renderHook(() => useMediaQuery("(min-width: 1024px)"));
    expect(result.current).toBe(false);

    // Simulate media query change
    if (changeHandler) {
      changeHandler({
        matches: true,
        media: "(min-width: 1024px)",
      } as MediaQueryListEvent);
    }

    rerender();
    expect(result.current).toBe(true);
  });

  it("removes listener on unmount", () => {
    const mockAddEventListener = vi.fn();
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: false,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { unmount } = renderHook(() => useMediaQuery("(min-width: 1024px)"));
    expect(mockAddEventListener).toHaveBeenCalledWith("change", expect.any(Function));

    unmount();
    expect(mockRemoveEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  });

  it("handles different queries independently", () => {
    const queries: Record<string, boolean> = {
      "(min-width: 1024px)": false,
      "(max-width: 1023px)": true,
    };

    window.matchMedia = vi.fn(
      (query: string) =>
        ({
          matches: queries[query],
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        }) as unknown as MediaQueryList,
    );

    const { result: result1 } = renderHook(() => useMediaQuery("(min-width: 1024px)"));
    const { result: result2 } = renderHook(() => useMediaQuery("(max-width: 1023px)"));

    expect(result1.current).toBe(false);
    expect(result2.current).toBe(true);
  });
});

describe("useIsMobile", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns true when viewport is mobile (max-width: 1023px)", () => {
    const mockAddEventListener = vi.fn();
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: true,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(true);
  });

  it("returns false when viewport is desktop (min-width: 1024px)", () => {
    const mockAddEventListener = vi.fn();
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: false,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { result } = renderHook(() => useIsMobile());
    expect(result.current).toBe(false);
  });
});

describe("useIsDesktop", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns true when viewport is desktop (min-width: 1024px)", () => {
    const mockAddEventListener = vi.fn();
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: true,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(true);
  });

  it("returns false when viewport is mobile (max-width: 1023px)", () => {
    const mockAddEventListener = vi.fn();
    const mockRemoveEventListener = vi.fn();

    window.matchMedia = vi.fn(
      () =>
        ({
          matches: false,
          addEventListener: mockAddEventListener,
          removeEventListener: mockRemoveEventListener,
        }) as unknown as MediaQueryList,
    );

    const { result } = renderHook(() => useIsDesktop());
    expect(result.current).toBe(false);
  });
});

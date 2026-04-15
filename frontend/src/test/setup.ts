/**
 * Vitest global test setup.
 *
 * Responsibilities:
 * - Extend expect with jest-dom matchers (toBeInTheDocument, toHaveClass, etc.).
 * - Clean up after each test to prevent state leakage.
 *
 * Does NOT:
 * - Configure MSW handlers (each test file sets up its own server).
 * - Initialize React Router or auth (test wrappers handle that).
 */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Polyfill ResizeObserver for jsdom (required by Recharts ResponsiveContainer).
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// Automatically unmount React trees after each test.
afterEach(() => {
  cleanup();
});

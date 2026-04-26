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

// Polyfill Blob.text() / File.text() for jsdom. The Strategy Studio
// ImportIrPanel calls ``selectedFile.text()`` to read the staged file
// before POSTing to /strategies/validate-ir, but the bundled jsdom
// version ships Blob/File without the spec-required ``text()`` method.
// Browsers (Chrome/Firefox/Safari) all implement it natively, so the
// production code is correct — the polyfill exists purely so the
// component test surface mirrors browser behaviour.
if (typeof Blob.prototype.text !== "function") {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (Blob.prototype as any).text = function text(this: Blob): Promise<string> {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error ?? new Error("FileReader failed"));
      reader.onload = () => resolve(String(reader.result ?? ""));
      reader.readAsText(this);
    });
  };
}

// Automatically unmount React trees after each test.
afterEach(() => {
  cleanup();
});

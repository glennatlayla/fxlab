/**
 * Unit tests for the RFC 4122 v4 UUID helper (Tranche F — 2026-04-24).
 *
 * Context
 * -------
 * The 2026-04-24 minitux login failure showed:
 *
 *     Login error: crypto.randomUUID is not a function.
 *
 * `crypto.randomUUID()` is exposed only in **secure contexts** — HTTPS
 * or localhost. On a plain `http://192.168.1.5` LAN origin the browser
 * deliberately omits it, so anything that called it directly crashed
 * the login path.
 *
 * The fix: `randomUUID()` in this module prefers the native call when
 * the browser exposes it, and otherwise falls back to `crypto.getRandom
 * Values()` (which IS available in non-secure contexts) to build an
 * RFC 4122 v4 UUID byte-for-byte correctly.
 *
 * These tests exercise both branches. vitest's `vi.stubGlobal` lets us
 * synthesize a `crypto` object that matches the browser's non-secure-
 * context shape (no `randomUUID`, but `getRandomValues` present).
 */

import { describe, expect, it, afterEach, vi } from "vitest";
import { randomUUID } from "./uuid";

const UUID_V4_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("randomUUID", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a canonical UUID v4 string", () => {
    const id = randomUUID();
    expect(id).toMatch(UUID_V4_RE);
  });

  it("returns a different value on successive calls", () => {
    const a = randomUUID();
    const b = randomUUID();
    expect(a).not.toEqual(b);
  });

  it("delegates to crypto.randomUUID when available (secure context)", () => {
    const fake = "11111111-2222-4333-8444-555555555555";
    const stub = vi.fn(() => fake);
    vi.stubGlobal("crypto", {
      randomUUID: stub,
      getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
    });
    expect(randomUUID()).toEqual(fake);
    expect(stub).toHaveBeenCalledOnce();
  });

  it("falls back to crypto.getRandomValues when randomUUID is absent (non-secure HTTP LAN)", () => {
    // Build a synthetic crypto object that matches a browser's
    // non-secure-context shape: getRandomValues present, randomUUID
    // undefined. Exactly the shape the 2026-04-24 minitux browser saw.
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", {
      getRandomValues: real.getRandomValues.bind(real),
      // randomUUID intentionally omitted
    });
    // @ts-expect-error — stubbed crypto deliberately lacks randomUUID.
    expect(crypto.randomUUID).toBeUndefined();
    const id = randomUUID();
    expect(id).toMatch(UUID_V4_RE);
  });

  it("fallback sets the version nibble to 4", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
    });
    // Character at index 14 (0-based) is the version nibble.
    const id = randomUUID();
    expect(id.charAt(14)).toEqual("4");
  });

  it("fallback sets the variant nibble to RFC 4122 (8, 9, a, or b)", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
    });
    const id = randomUUID();
    expect(["8", "9", "a", "b"]).toContain(id.charAt(19));
  });

  it("fallback produces well-distributed output", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
    });
    const ids = new Set<string>();
    for (let i = 0; i < 1000; i++) {
      ids.add(randomUUID());
    }
    // With 122 bits of entropy the collision probability over 1000
    // draws is ~10^-33. Any collision in this loop indicates a
    // broken generator (e.g. non-random fallback / constant bytes).
    expect(ids.size).toEqual(1000);
  });
});

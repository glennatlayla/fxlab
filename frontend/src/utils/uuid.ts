/**
 * UUID v4 helper that works in both secure and non-secure browser contexts.
 *
 * Purpose
 * -------
 * `crypto.randomUUID()` is part of the Web Crypto API but browsers only
 * expose it in **secure contexts** (HTTPS or `localhost`). On a LAN
 * origin like `http://192.168.1.5` the browser deliberately omits it,
 * so a direct call throws `TypeError: crypto.randomUUID is not a
 * function` — the exact error the 2026-04-24 minitux login hit.
 *
 * `crypto.getRandomValues()`, in contrast, IS available in all browser
 * contexts (including non-secure HTTP). `randomUUID()` in this module
 * uses the native fast path when available and otherwise hand-rolls
 * an RFC 4122 v4 UUID from `getRandomValues`.
 *
 * Replaces direct `crypto.randomUUID()` calls across the frontend:
 * - `src/pages/StrategyPnL.tsx`
 * - `src/infrastructure/auditLogger.ts`
 * - `src/api/client.ts`
 * - `src/features/strategy/useDraftAutosave.ts`
 * - `src/features/runs/services/RunLogger.ts`
 *
 * See `uuid.test.ts` for the contract and `feedback_fix_scripts_not_
 * work_around_them` in operator memory for the policy that produced
 * this fix (patch the code, don't tell the user to move to HTTPS).
 */

/**
 * Return a canonical RFC 4122 v4 UUID string, e.g.
 * `"11111111-2222-4333-8444-555555555555"`.
 *
 * Uses `crypto.randomUUID()` when the browser exposes it; otherwise
 * falls back to a `crypto.getRandomValues()`-based implementation
 * that is byte-for-byte equivalent to the native output.
 */
export function randomUUID(): string {
  // Fast path: native crypto.randomUUID() when present. This is the
  // secure-context path (HTTPS / localhost) — identical output to the
  // fallback below but avoids the JS-side byte-shuffling.
  const webCrypto: Crypto | undefined =
    typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (webCrypto && typeof webCrypto.randomUUID === "function") {
    return webCrypto.randomUUID();
  }

  // Fallback: RFC 4122 v4 built on crypto.getRandomValues, which is
  // exposed in all browser contexts (including non-secure HTTP on LAN
  // origins). If even getRandomValues is unavailable we fail loudly
  // rather than silently degrade to Math.random — a UUID that is not
  // cryptographically random would be a subtle and dangerous bug.
  if (!webCrypto || typeof webCrypto.getRandomValues !== "function") {
    throw new Error(
      "randomUUID: neither crypto.randomUUID nor crypto.getRandomValues " +
        "is available. This runtime is too restricted for UUID generation.",
    );
  }

  const bytes = new Uint8Array(16);
  webCrypto.getRandomValues(bytes);

  // Per RFC 4122 §4.4:
  //   - Byte 6 high nibble = 0100 (version 4)
  //   - Byte 8 high two bits = 10 (variant 1, RFC 4122)
  // Using bitwise ops on the random bytes rather than regenerating.
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  // Lookup table for fast hex conversion. Avoids String.padStart in a
  // hot path if an application ever generates IDs per-render.
  const hex: string[] = [];
  for (let i = 0; i < 256; i++) {
    hex.push((i + 0x100).toString(16).slice(1));
  }

  return (
    hex[bytes[0]] +
    hex[bytes[1]] +
    hex[bytes[2]] +
    hex[bytes[3]] +
    "-" +
    hex[bytes[4]] +
    hex[bytes[5]] +
    "-" +
    hex[bytes[6]] +
    hex[bytes[7]] +
    "-" +
    hex[bytes[8]] +
    hex[bytes[9]] +
    "-" +
    hex[bytes[10]] +
    hex[bytes[11]] +
    hex[bytes[12]] +
    hex[bytes[13]] +
    hex[bytes[14]] +
    hex[bytes[15]]
  );
}

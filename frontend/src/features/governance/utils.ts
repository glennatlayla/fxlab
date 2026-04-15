/**
 * Governance feature shared utilities.
 *
 * Purpose:
 *   Common utility functions shared across governance components.
 *   Extracted to avoid duplication per CLAUDE.md DRY principle.
 *
 * Does NOT:
 *   - Contain component logic, rendering, or state.
 *   - Import React or any UI dependencies.
 *
 * Dependencies:
 *   - None (pure functions).
 */

/**
 * Sanitize a URL for safe rendering in an anchor tag.
 *
 * Only allows http: and https: protocols. Blocks javascript:, data:,
 * ftp:, blob:, and any other non-web protocols to prevent XSS injection.
 *
 * Args:
 *   url: The URL string to sanitize.
 *
 * Returns:
 *   The original URL if safe, or null if the URL uses a disallowed protocol.
 *
 * Example:
 *   sanitizeUrl("https://jira.example.com/FX-123") → "https://jira.example.com/FX-123"
 *   sanitizeUrl("javascript:alert(1)")             → null
 */
export function sanitizeUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      return url;
    }
    return null;
  } catch {
    return null;
  }
}

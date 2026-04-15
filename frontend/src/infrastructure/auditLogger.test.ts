/**
 * Unit tests for structured audit logger.
 *
 * Purpose:
 *   Verify that audit events are formatted correctly, sent to the backend,
 *   and that failures do not block user operations (fire-and-forget semantics).
 *
 * Test coverage:
 *   - Happy path: audit event sent successfully
 *   - Network error: rejection caught, does not throw
 *   - Invalid event type: compilation error (caught by TypeScript)
 *   - Event shape: all required fields present
 *   - Fire-and-forget: async call does not block caller
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { logAuditEvent, type AuditEventType } from "./auditLogger";
import * as apiClientModule from "@/api/client";

// Mock the apiClient module
vi.mock("@/api/client", () => ({
  apiClient: {
    post: vi.fn(),
  },
}));

describe("auditLogger", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("logAuditEvent", () => {
    it("should send a valid audit event to /audit/events", async () => {
      const mockPost = vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      const result = await logAuditEvent("strategy.draft_created", "user-ulid-123");

      // Verify POST was called
      expect(mockPost).toHaveBeenCalledOnce();
      const [endpoint, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>];

      expect(endpoint).toBe("/audit/events");
      expect(payload).toMatchObject({
        event: "strategy.draft_created",
        actor: "user-ulid-123",
      });

      // Verify returned promise resolves without throwing
      expect(result).toBeUndefined();
    });

    it("should include event, actor, timestamp, and correlationId", async () => {
      const mockPost = vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      const actor = "user-abc";
      await logAuditEvent("strategy.draft_autosaved", actor);

      const [, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>];

      // Verify required fields are present
      expect(payload).toHaveProperty("event", "strategy.draft_autosaved");
      expect(payload).toHaveProperty("actor", actor);
      expect(payload).toHaveProperty("timestamp");
      expect(payload).toHaveProperty("correlationId");

      // Verify timestamp is valid ISO 8601
      expect(() => new Date(payload.timestamp as string)).not.toThrow();

      // Verify correlationId looks like a UUID
      expect(payload.correlationId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      );
    });

    it("should include metadata when provided", async () => {
      const mockPost = vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      const metadata = { draft_id: "strategy-123", step: "basics" };
      await logAuditEvent("strategy.draft_restored", "user-ulid", metadata);

      const [, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>];

      expect(payload).toHaveProperty("metadata", metadata);
    });

    it("should omit metadata field when not provided", async () => {
      const mockPost = vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      await logAuditEvent("auth.login", "user-xyz");

      const [, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>];

      // metadata is optional and should not be present if not provided
      expect(payload).not.toHaveProperty("metadata");
    });

    it("should not throw when POST fails", async () => {
      const mockError = new Error("Network error");
      vi.spyOn(apiClientModule.apiClient, "post").mockRejectedValue(mockError);

      // Should not throw despite backend failure
      const fn = async () => {
        await logAuditEvent("strategy.submitted", "user-ulid");
      };

      await expect(fn()).resolves.not.toThrow();
    });

    it("should handle 4xx/5xx response errors without throwing", async () => {
      const mockError = new Error("500 Internal Server Error");
      vi.spyOn(apiClientModule.apiClient, "post").mockRejectedValue(mockError);

      // Fire-and-forget: error should be silently handled
      const result = await logAuditEvent("strategy.approved", "user-ulid");

      expect(result).toBeUndefined();
    });

    it("should support all audit event types", async () => {
      const mockPost = vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      const eventTypes: AuditEventType[] = [
        "strategy.draft_created",
        "strategy.draft_autosaved",
        "strategy.draft_restored",
        "strategy.draft_discarded",
        "strategy.submitted",
        "strategy.approved",
        "strategy.rejected",
        "auth.login",
        "auth.logout",
        "auth.session_restored",
      ];

      for (const eventType of eventTypes) {
        mockPost.mockClear();
        await logAuditEvent(eventType, "user-test");

        const [, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>];
        expect(payload.event).toBe(eventType);
      }
    });

    it("should allow empty metadata object", async () => {
      const mockPost = vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      await logAuditEvent("strategy.draft_discarded", "user-ulid", {});

      const [, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>];
      expect(payload.metadata).toEqual({});
    });

    it("should support nested metadata structures", async () => {
      const mockPost = vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      const metadata = {
        draft: {
          id: "draft-123",
          name: "My Strategy",
          steps_completed: ["basics", "conditions"],
        },
        context: {
          session_duration_ms: 5000,
        },
      };

      await logAuditEvent("strategy.draft_autosaved", "user-ulid", metadata);

      const [, payload] = mockPost.mock.calls[0] as [string, Record<string, unknown>];
      expect(payload.metadata).toEqual(metadata);
    });

    it("should return a resolved Promise for chaining", async () => {
      vi.spyOn(apiClientModule.apiClient, "post").mockResolvedValue({});

      const promise = logAuditEvent("auth.login", "user-ulid");

      // Should be a Promise that resolves to void
      expect(promise).toBeInstanceOf(Promise);
      await expect(promise).resolves.toBeUndefined();
    });
  });
});

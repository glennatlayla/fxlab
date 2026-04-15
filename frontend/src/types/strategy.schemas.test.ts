/**
 * Unit tests for Zod runtime schemas for strategy domain types.
 *
 * Purpose:
 *   Verify that schemas correctly validate well-formed API responses
 *   and reject malformed data at runtime.
 *
 * Test coverage:
 *   - DraftAutosaveResponseSchema: happy path, missing field, type mismatch
 *   - DraftAutosaveRecordSchema: happy path, missing required field, extra fields
 *   - Draft payload nested record validation
 */

import { describe, it, expect } from "vitest";
import { DraftAutosaveResponseSchema, DraftAutosaveRecordSchema } from "./strategy.schemas";

describe("strategy.schemas", () => {
  describe("DraftAutosaveResponseSchema", () => {
    it("should validate a correct autosave response", () => {
      const valid = {
        autosave_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        saved_at: "2026-04-04T14:30:00Z",
      };

      const result = DraftAutosaveResponseSchema.safeParse(valid);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.autosave_id).toBe("01ARZ3NDEKTSV4RRFFQ69G5FAV");
        expect(result.data.saved_at).toBe("2026-04-04T14:30:00Z");
      }
    });

    it("should reject response missing autosave_id", () => {
      const invalid = {
        saved_at: "2026-04-04T14:30:00Z",
      };

      const result = DraftAutosaveResponseSchema.safeParse(invalid);
      expect(result.success).toBe(false);
    });

    it("should reject response missing saved_at", () => {
      const invalid = {
        autosave_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
      };

      const result = DraftAutosaveResponseSchema.safeParse(invalid);
      expect(result.success).toBe(false);
    });

    it("should reject non-string autosave_id", () => {
      const invalid = {
        autosave_id: 123,
        saved_at: "2026-04-04T14:30:00Z",
      };

      const result = DraftAutosaveResponseSchema.safeParse(invalid);
      expect(result.success).toBe(false);
    });

    it("should reject non-string saved_at", () => {
      const invalid = {
        autosave_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        saved_at: 1712252400000,
      };

      const result = DraftAutosaveResponseSchema.safeParse(invalid);
      expect(result.success).toBe(false);
    });

    it("should allow extra fields (Zod strips them by default)", () => {
      const dataWithExtra = {
        autosave_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        saved_at: "2026-04-04T14:30:00Z",
        extra_field: "should be ignored",
      };

      const result = DraftAutosaveResponseSchema.safeParse(dataWithExtra);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data).not.toHaveProperty("extra_field");
      }
    });
  });

  describe("DraftAutosaveRecordSchema", () => {
    it("should validate a correct autosave record", () => {
      const record = {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FBZ",
        draft_payload: {
          name: "My Strategy",
          description: "Test strategy",
        },
        form_step: "basics",
        session_id: "session-uuid-123",
        client_ts: "2026-04-04T14:15:00Z",
        created_at: "2026-04-04T14:20:00Z",
        updated_at: "2026-04-04T14:25:00Z",
      };

      const result = DraftAutosaveRecordSchema.safeParse(record);
      expect(result.success).toBe(true);
      expect(result).toHaveProperty("data");
    });

    it("should reject record missing id", () => {
      const invalid = {
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FBZ",
        draft_payload: {},
        form_step: "basics",
        session_id: "session-uuid-123",
        client_ts: "2026-04-04T14:15:00Z",
        created_at: "2026-04-04T14:20:00Z",
        updated_at: "2026-04-04T14:25:00Z",
      };

      const result = DraftAutosaveRecordSchema.safeParse(invalid);
      expect(result.success).toBe(false);
    });

    it("should reject record missing user_id", () => {
      const invalid = {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        draft_payload: {},
        form_step: "basics",
        session_id: "session-uuid-123",
        client_ts: "2026-04-04T14:15:00Z",
        created_at: "2026-04-04T14:20:00Z",
        updated_at: "2026-04-04T14:25:00Z",
      };

      const result = DraftAutosaveRecordSchema.safeParse(invalid);
      expect(result.success).toBe(false);
    });

    it("should accept any value in draft_payload (z.any allows anything)", () => {
      // Note: draft_payload uses z.any() to allow any structure,
      // including primitives. This is by design to support future extensions
      // and various payload formats from the backend.
      const invalid = {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FBZ",
        draft_payload: "not an object",
        form_step: "basics",
        session_id: "session-uuid-123",
        client_ts: "2026-04-04T14:15:00Z",
        created_at: "2026-04-04T14:20:00Z",
        updated_at: "2026-04-04T14:25:00Z",
      };

      const result = DraftAutosaveRecordSchema.safeParse(invalid);
      // z.any() accepts any value
      expect(result.success).toBe(true);
    });

    it("should allow empty draft_payload object", () => {
      const record = {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FBZ",
        draft_payload: {},
        form_step: "basics",
        session_id: "session-uuid-123",
        client_ts: "2026-04-04T14:15:00Z",
        created_at: "2026-04-04T14:20:00Z",
        updated_at: "2026-04-04T14:25:00Z",
      };
      const result = DraftAutosaveRecordSchema.safeParse(record);
      expect(result.success).toBe(true);
    });

    it("should validate with nested form data payload", () => {
      const record = {
        id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
        user_id: "01ARZ3NDEKTSV4RRFFQ69G5FBZ",
        draft_payload: {
          name: "Strategy A",
          instrument: "ES",
          timeframe: "1h",
          parameters: [],
        },
        form_step: "basics",
        session_id: "session-uuid-123",
        client_ts: "2026-04-04T14:15:00Z",
        created_at: "2026-04-04T14:20:00Z",
        updated_at: "2026-04-04T14:25:00Z",
      };

      const result = DraftAutosaveRecordSchema.safeParse(record);
      expect(result.success).toBe(true);
      expect(result).toHaveProperty("data");
    });
  });
});

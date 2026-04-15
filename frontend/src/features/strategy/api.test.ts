/**
 * Tests for strategyApi service.
 *
 * Verifies:
 *   - saveAutosave sends POST to /strategies/draft/autosave
 *   - getLatestAutosave sends GET with user_id param
 *   - getLatestAutosave returns null on 204
 *   - deleteAutosave sends DELETE to correct URL
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { strategyApi } from "./api";
import { apiClient } from "@/api/client";
import type {
  DraftAutosavePayload,
  DraftAutosaveResponse,
  DraftAutosaveRecord,
} from "@/types/strategy";

// Mock the apiClient
vi.mock("@/api/client");

// Create individual mocks for each HTTP method with proper typing.
// This ensures vi.mockResolvedValue() and vi.mockRejectedValue() are available.
const mockPost = vi.fn();
const mockGet = vi.fn();
const mockDelete = vi.fn();

// Wire the mocks onto the mocked apiClient module.
// After vi.mock(), apiClient's methods are stubs; we replace them with our vi.fn() instances.
// vi.fn() doesn't match Axios method signatures; double-cast required for mock wiring
const mockedClient = vi.mocked(apiClient) as unknown as Record<string, unknown>;
mockedClient.post = mockPost;
mockedClient.get = mockGet;
mockedClient.delete = mockDelete;

/**
 * Build a typed mock AxiosResponse. Avoids `as any` on the config field
 * while keeping test bodies concise.
 */
function mockAxiosResponse<T>(data: T, status = 200): AxiosResponse<T> {
  return {
    data,
    status,
    statusText: status === 204 ? "No Content" : "OK",
    headers: {},
    config: { headers: {} } as InternalAxiosRequestConfig,
  };
}

describe("strategyApi", () => {
  const mockUser = {
    userId: "user-123",
    email: "test@example.com",
    displayName: "Test User",
  };

  const mockFormData = {
    name: "Test Strategy",
    description: "A test strategy",
    instrument: "ES",
  };

  const mockPayload: DraftAutosavePayload = {
    user_id: mockUser.userId,
    draft_payload: mockFormData,
    form_step: "basics",
    client_ts: new Date().toISOString(),
    session_id: "session-123",
  };

  const mockAutosaveResponse: DraftAutosaveResponse = {
    autosave_id: "autosave-456",
    saved_at: new Date().toISOString(),
  };

  const mockAutosaveRecord: DraftAutosaveRecord = {
    id: "autosave-456",
    user_id: mockUser.userId,
    draft_payload: mockFormData,
    form_step: "basics",
    session_id: "session-123",
    client_ts: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("saveAutosave", () => {
    it("sends POST to /strategies/draft/autosave", async () => {
      mockPost.mockResolvedValue(mockAxiosResponse(mockAutosaveResponse));

      const result = await strategyApi.saveAutosave(mockPayload);

      expect(mockPost).toHaveBeenCalledWith("/strategies/draft/autosave", mockPayload);
      expect(result).toEqual(mockAutosaveResponse);
    });

    it("returns the response data", async () => {
      mockPost.mockResolvedValue(mockAxiosResponse(mockAutosaveResponse));

      const result = await strategyApi.saveAutosave(mockPayload);

      expect(result.autosave_id).toBe("autosave-456");
      expect(result.saved_at).toBe(mockAutosaveResponse.saved_at);
    });

    it("throws on network error", async () => {
      const networkError = new Error("Network failed");
      mockPost.mockRejectedValue(networkError);

      await expect(strategyApi.saveAutosave(mockPayload)).rejects.toThrow("Network failed");
    });

    it("throws on 422 validation error", async () => {
      const validationError = new Error("Validation failed");
      mockPost.mockRejectedValue(validationError);

      await expect(strategyApi.saveAutosave(mockPayload)).rejects.toThrow("Validation failed");
    });

    it("passes payload with all required fields", async () => {
      mockPost.mockResolvedValue(mockAxiosResponse(mockAutosaveResponse));

      const payload: DraftAutosavePayload = {
        user_id: "user-456",
        draft_payload: {
          name: "Strategy 2",
          description: "Another test",
          instrument: "NQ",
        },
        form_step: "risk",
        client_ts: "2026-04-04T12:00:00Z",
        session_id: "session-456",
      };

      await strategyApi.saveAutosave(payload);

      expect(mockPost).toHaveBeenCalledWith("/strategies/draft/autosave", payload);
    });
  });

  describe("getLatestAutosave", () => {
    it("sends GET with user_id param", async () => {
      mockGet.mockResolvedValue(mockAxiosResponse(mockAutosaveRecord));

      await strategyApi.getLatestAutosave(mockUser.userId);

      expect(mockGet).toHaveBeenCalledWith("/strategies/draft/autosave/latest", {
        params: { user_id: mockUser.userId },
      });
    });

    it("returns the autosave record when found", async () => {
      mockGet.mockResolvedValue(mockAxiosResponse(mockAutosaveRecord));

      const result = await strategyApi.getLatestAutosave(mockUser.userId);

      expect(result).toEqual(mockAutosaveRecord);
      expect(result?.id).toBe("autosave-456");
      expect(result?.draft_payload).toEqual(mockFormData);
    });

    it("returns null on 204 No Content", async () => {
      mockGet.mockResolvedValue(mockAxiosResponse(null, 204));

      const result = await strategyApi.getLatestAutosave(mockUser.userId);

      expect(result).toBeNull();
    });

    it("throws on network error", async () => {
      const networkError = new Error("Network failed");
      mockGet.mockRejectedValue(networkError);

      await expect(strategyApi.getLatestAutosave(mockUser.userId)).rejects.toThrow(
        "Network failed",
      );
    });

    it("throws on 404 Not Found", async () => {
      const notFoundError = new Error("Not found");
      mockGet.mockRejectedValue(notFoundError);

      await expect(strategyApi.getLatestAutosave(mockUser.userId)).rejects.toThrow("Not found");
    });

    it("handles different user IDs correctly", async () => {
      mockGet.mockResolvedValue(mockAxiosResponse(mockAutosaveRecord));

      const userId = "different-user-789";
      await strategyApi.getLatestAutosave(userId);

      expect(mockGet).toHaveBeenCalledWith("/strategies/draft/autosave/latest", {
        params: { user_id: userId },
      });
    });

    it("returns null when response status is 204 regardless of data", async () => {
      // Even if somehow data is provided with 204, return null
      mockGet.mockResolvedValue(mockAxiosResponse(mockAutosaveRecord, 204));

      const result = await strategyApi.getLatestAutosave(mockUser.userId);

      expect(result).toBeNull();
    });
  });

  describe("deleteAutosave", () => {
    it("sends DELETE to correct URL", async () => {
      mockDelete.mockResolvedValue(mockAxiosResponse(undefined, 204));

      await strategyApi.deleteAutosave("autosave-456");

      expect(mockDelete).toHaveBeenCalledWith("/strategies/draft/autosave/autosave-456");
    });

    it("uses the provided autosave ID in the URL", async () => {
      mockDelete.mockResolvedValue(mockAxiosResponse(undefined, 204));

      const autosaveId = "custom-autosave-id";
      await strategyApi.deleteAutosave(autosaveId);

      expect(mockDelete).toHaveBeenCalledWith("/strategies/draft/autosave/custom-autosave-id");
    });

    it("returns undefined on success", async () => {
      mockDelete.mockResolvedValue(mockAxiosResponse(undefined, 204));

      const result = await strategyApi.deleteAutosave("autosave-456");

      expect(result).toBeUndefined();
    });

    it("throws on 404 Not Found", async () => {
      const notFoundError = new Error("Not found");
      mockDelete.mockRejectedValue(notFoundError);

      await expect(strategyApi.deleteAutosave("nonexistent-id")).rejects.toThrow("Not found");
    });

    it("throws on network error", async () => {
      const networkError = new Error("Network failed");
      mockDelete.mockRejectedValue(networkError);

      await expect(strategyApi.deleteAutosave("autosave-456")).rejects.toThrow("Network failed");
    });

    it("throws on 500 server error", async () => {
      const serverError = new Error("Server error");
      mockDelete.mockRejectedValue(serverError);

      await expect(strategyApi.deleteAutosave("autosave-456")).rejects.toThrow("Server error");
    });

    it("constructs URL with correct format for ULID autosave IDs", async () => {
      mockDelete.mockResolvedValue(mockAxiosResponse(undefined, 204));

      const ulidId = "01ARZ3NDEKTSV4RRFFQ69G5FAV";
      await strategyApi.deleteAutosave(ulidId);

      expect(mockDelete).toHaveBeenCalledWith(`/strategies/draft/autosave/${ulidId}`);
    });
  });

  describe("error handling", () => {
    it("propagates AxiosError from apiClient for all methods", async () => {
      const axiosError = new Error("Axios error");
      mockPost.mockRejectedValue(axiosError);

      await expect(strategyApi.saveAutosave(mockPayload)).rejects.toThrow("Axios error");
    });

    it("does not catch or wrap errors", async () => {
      const originalError = new Error("Original error");
      mockDelete.mockRejectedValue(originalError);

      await expect(strategyApi.deleteAutosave("autosave-456")).rejects.toBe(originalError);
    });
  });
});

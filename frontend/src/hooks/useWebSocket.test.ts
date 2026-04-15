/**
 * Unit tests for useWebSocket hook (M7 — Real-Time Position Dashboard).
 *
 * Verifies:
 *   - Initial state is "disconnected" when disabled.
 *   - Connects when token is provided and enabled.
 *   - Calls onMessage when JSON message received.
 *   - Updates lastMessage on message receipt.
 *   - Connection status transitions: connecting → connected.
 *   - Does not connect when token is null.
 *   - sendMessage sends data over the WebSocket.
 *   - Cleans up on unmount.
 *
 * Dependencies:
 *   - vitest for mocking
 *   - @testing-library/react for renderHook
 *   - Mock WebSocket class
 */

import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useWebSocket } from "./useWebSocket";

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

type WsHandler = ((event: { data: string }) => void) | null;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  readyState: number = 0; // CONNECTING
  onopen: (() => void) | null = null;
  onmessage: WsHandler = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number; reason: string }) => void) | null = null;
  sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close(code?: number, reason?: string) {
    this.readyState = 3; // CLOSED
    this.onclose?.({ code: code ?? 1000, reason: reason ?? "" });
  }

  // Test helpers
  simulateOpen() {
    this.readyState = 1; // OPEN
    this.onopen?.();
  }

  simulateMessage(data: Record<string, unknown>) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  simulateClose(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code, reason: "" });
  }

  simulateError() {
    this.onerror?.();
  }

  static OPEN = 1;
  static CLOSED = 3;
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

const originalWebSocket = globalThis.WebSocket;

beforeEach(() => {
  MockWebSocket.instances = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).WebSocket = MockWebSocket;
  vi.useFakeTimers();
});

afterEach(() => {
  (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket = originalWebSocket;
  vi.useRealTimers();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useWebSocket", () => {
  describe("initial state", () => {
    it("starts disconnected when disabled", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          enabled: false,
        }),
      );

      expect(result.current.status).toBe("disconnected");
      expect(result.current.lastMessage).toBeNull();
      expect(result.current.reconnectAttempts).toBe(0);
    });

    it("does not connect when token is null", () => {
      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: null,
        }),
      );

      expect(MockWebSocket.instances).toHaveLength(0);
    });
  });

  describe("connection lifecycle", () => {
    it("creates WebSocket with token in URL", () => {
      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "my-jwt-token",
        }),
      );

      expect(MockWebSocket.instances).toHaveLength(1);
      expect(MockWebSocket.instances[0].url).toContain("token=my-jwt-token");
    });

    it("transitions to connected on open", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      act(() => {
        MockWebSocket.instances[0].simulateOpen();
      });

      expect(result.current.status).toBe("connected");
    });

    it("calls onStatusChange callback", () => {
      const onStatusChange = vi.fn();

      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          onStatusChange,
        }),
      );

      act(() => {
        MockWebSocket.instances[0].simulateOpen();
      });

      expect(onStatusChange).toHaveBeenCalledWith("connecting");
      expect(onStatusChange).toHaveBeenCalledWith("connected");
    });

    it("cleans up on unmount", () => {
      const { unmount } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      unmount();

      expect(ws.readyState).toBe(3); // CLOSED
    });
  });

  describe("message handling", () => {
    it("parses JSON messages and updates lastMessage", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        ws.simulateMessage({ msg_type: "position_update", data: "test" });
      });

      expect(result.current.lastMessage).toEqual({
        msg_type: "position_update",
        data: "test",
      });
    });

    it("calls onMessage callback with parsed data", () => {
      const onMessage = vi.fn();

      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          onMessage,
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        ws.simulateMessage({ msg_type: "heartbeat" });
      });

      expect(onMessage).toHaveBeenCalledWith({ msg_type: "heartbeat" });
    });
  });

  describe("sendMessage", () => {
    it("sends data when connected", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        result.current.sendMessage("ping");
      });

      expect(ws.sentMessages).toContain("ping");
    });
  });

  describe("auto-reconnect", () => {
    it("attempts reconnect on unexpected close", () => {
      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          baseDelay: 1000,
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      // Simulate unexpected close
      act(() => {
        ws.simulateClose(1006);
      });

      // Advance timer past first reconnect delay (1000ms base + up to 500ms jitter)
      act(() => {
        vi.advanceTimersByTime(1600);
      });

      // A new WebSocket should have been created
      expect(MockWebSocket.instances.length).toBeGreaterThan(1);
    });

    it("does not reconnect on auth failure (4008)", () => {
      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        ws.simulateClose(4008);
      });

      act(() => {
        vi.advanceTimersByTime(5000);
      });

      // Should not have created a new WebSocket
      expect(MockWebSocket.instances).toHaveLength(1);
    });

    it("does not reconnect on normal close (1000)", () => {
      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        ws.simulateClose(1000);
      });

      act(() => {
        vi.advanceTimersByTime(5000);
      });

      expect(MockWebSocket.instances).toHaveLength(1);
    });

    it("resets reconnect attempts on manual reconnect", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        ws.simulateClose(1006);
      });

      act(() => {
        result.current.reconnect();
      });

      expect(result.current.reconnectAttempts).toBe(0);
    });

    it("includes jitter in exponential backoff", () => {
      vi.spyOn(global.Math, "random").mockReturnValue(0.5); // 50% for consistent jitter

      renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          baseDelay: 1000,
          maxDelay: 30000,
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        ws.simulateClose(1006);
      });

      // First reconnect should be: 1000 * 2^0 + (0.5 * 500) = 1000 + 250 = 1250ms
      act(() => {
        vi.advanceTimersByTime(1250);
      });

      // Should have reconnected
      expect(MockWebSocket.instances.length).toBeGreaterThan(1);
    });
  });

  describe("mobile lifecycle - visibility changes", () => {
    it("pauses connection on page visibility hidden when pauseOnHidden is true", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          pauseOnHidden: true,
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      expect(result.current.isConnected).toBe(true);

      // Simulate page becoming hidden
      act(() => {
        Object.defineProperty(document, "hidden", {
          configurable: true,
          value: true,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // Connection should be closed
      expect(ws.readyState).toBe(3); // CLOSED
      expect(result.current.status).toBe("disconnected");
    });

    it("resumes connection on page visibility visible when pauseOnHidden is true", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          pauseOnHidden: true,
        }),
      );

      const ws1 = MockWebSocket.instances[0];
      act(() => {
        ws1.simulateOpen();
      });

      // Hide page
      act(() => {
        Object.defineProperty(document, "hidden", {
          configurable: true,
          value: true,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      const initialCount = MockWebSocket.instances.length;

      // Show page
      act(() => {
        Object.defineProperty(document, "hidden", {
          configurable: true,
          value: false,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // Should attempt to reconnect
      expect(result.current.reconnectAttempts).toBe(0); // Reset on visibility change
      expect(MockWebSocket.instances.length).toBeGreaterThan(initialCount);
    });

    it("does not pause on visibility change when pauseOnHidden is false", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          pauseOnHidden: false,
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      const initialReadyState = ws.readyState;

      // Simulate page becoming hidden
      act(() => {
        Object.defineProperty(document, "hidden", {
          configurable: true,
          value: true,
        });
        document.dispatchEvent(new Event("visibilitychange"));
      });

      // Connection should still be open
      expect(ws.readyState).toBe(initialReadyState);
      expect(result.current.isConnected).toBe(true);
    });
  });

  describe("mobile lifecycle - network changes", () => {
    it("reconnects immediately when network comes back online", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws1 = MockWebSocket.instances[0];
      act(() => {
        ws1.simulateOpen();
      });

      act(() => {
        ws1.simulateClose(1006);
      });

      act(() => {
        vi.advanceTimersByTime(100); // Advance a bit
      });

      const countBeforeOnline = MockWebSocket.instances.length;

      // Simulate network coming back online
      act(() => {
        window.dispatchEvent(new Event("online"));
      });

      // Should have attempted to reconnect
      expect(result.current.reconnectAttempts).toBe(0); // Reset on online event
      expect(MockWebSocket.instances.length).toBeGreaterThan(countBeforeOnline);
    });

    it("closes connection and stops reconnecting when offline", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          baseDelay: 1000,
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      expect(result.current.isConnected).toBe(true);

      // Simulate network going offline
      act(() => {
        window.dispatchEvent(new Event("offline"));
      });

      // Connection should be closed
      expect(ws.readyState).toBe(3); // CLOSED
      expect(result.current.isConnected).toBe(false);

      const countAfterOffline = MockWebSocket.instances.length;

      // Advance timer — no new connection should attempt
      act(() => {
        vi.advanceTimersByTime(5000);
      });

      // No new WebSocket should have been created
      expect(MockWebSocket.instances.length).toBe(countAfterOffline);
    });
  });

  describe("derived state flags", () => {
    it("isConnected is true when status is connected", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      expect(result.current.isConnected).toBe(true);
    });

    it("isConnected is false when disconnected", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      expect(result.current.isConnected).toBe(false);
    });

    it("isReconnecting is true when reconnecting", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      act(() => {
        ws.simulateClose(1006);
      });

      expect(result.current.isReconnecting).toBe(true);
    });

    it("isReconnecting is false when connected or never tried", () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
        }),
      );

      const ws = MockWebSocket.instances[0];
      act(() => {
        ws.simulateOpen();
      });

      expect(result.current.isReconnecting).toBe(false);
    });
  });
});

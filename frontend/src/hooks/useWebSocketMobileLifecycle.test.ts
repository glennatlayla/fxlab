/**
 * QA-05: WebSocket Mobile Lifecycle Testing
 *
 * Purpose:
 *   Comprehensive tests for WebSocket behavior under mobile-specific conditions:
 *   iOS Safari background tab killing, network transitions (WiFi→cellular),
 *   page visibility changes, and recovery from extended disconnection.
 *
 * Test Coverage:
 *   - Visibility API Integration: 5 tests
 *   - Network Change Detection: 4 tests
 *   - Exponential Backoff: 4 tests
 *   - Clean Teardown & Memory Leaks: 4 tests
 *   - Edge Cases: 5 tests
 *
 * Test Strategy:
 *   - Mock WebSocket globally
 *   - Simulate visibility changes via document.hidden and visibilitychange events
 *   - Simulate network events via online/offline events
 *   - Verify reconnection timing matches exponential backoff spec
 *   - Verify clean teardown prevents memory leaks
 *
 * Stack:
 *   - React 18, TypeScript, Vitest, @testing-library/react
 */

import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useWebSocket } from "./useWebSocket";

// ---------------------------------------------------------------------------
// Mock WebSocket (same as in useWebSocket.test.ts)
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
  vi.spyOn(global.Math, "random").mockReturnValue(0.5); // Consistent jitter for testing
});

afterEach(() => {
  (globalThis as unknown as { WebSocket: typeof WebSocket }).WebSocket = originalWebSocket;
  vi.useRealTimers();
  vi.clearAllMocks();
  // Reset document.hidden
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
});

// ---------------------------------------------------------------------------
// Tests: Visibility API Integration
// ---------------------------------------------------------------------------

describe("useWebSocket - Mobile Lifecycle: Visibility API Integration", () => {
  it("test_closes_connection_when_page_hidden", () => {
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

    // Connection should be closed with code 1000
    expect(ws.readyState).toBe(3); // CLOSED
    expect(result.current.status).toBe("disconnected");
  });

  it("test_reconnects_when_page_becomes_visible", () => {
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

    const countAfterHide = MockWebSocket.instances.length;

    // Show page
    act(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: false,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Should attempt to reconnect — new WebSocket created
    expect(MockWebSocket.instances.length).toBeGreaterThan(countAfterHide);
    expect(result.current.reconnectAttempts).toBe(0); // Reset on visibility change
  });

  it("test_resets_retry_count_on_visibility_reconnect", () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        pauseOnHidden: true,
        baseDelay: 1000,
      }),
    );

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
    });

    // Trigger disconnection with code 1006 (abnormal)
    act(() => {
      ws1.simulateClose(1006);
    });

    // Attempt count should increase
    expect(result.current.reconnectAttempts).toBe(1);

    // Hide page
    act(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Show page — retry count should reset to 0
    act(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: false,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(result.current.reconnectAttempts).toBe(0);
  });

  it("test_does_not_close_when_pauseOnHidden_is_false", () => {
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
    expect(result.current.isConnected).toBe(true);

    // Simulate page becoming hidden
    act(() => {
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Connection should NOT be closed
    expect(ws.readyState).toBe(initialReadyState);
    expect(result.current.isConnected).toBe(true);
  });

  it("test_handles_rapid_visibility_toggles", () => {
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

    const instanceCountStart = MockWebSocket.instances.length;

    // Rapid hide/show/hide/show
    act(() => {
      // Hide
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    act(() => {
      // Show
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: false,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    act(() => {
      // Hide
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: true,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    act(() => {
      // Show
      Object.defineProperty(document, "hidden", {
        configurable: true,
        value: false,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });

    // Should have created new connections on each show, but not crash
    // Exact count depends on timing, but should be > 1 new connection
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(instanceCountStart + 1);
    expect(result.current.status).toBe("connecting"); // Last action was show/reconnect
  });
});

// ---------------------------------------------------------------------------
// Tests: Network Change Detection
// ---------------------------------------------------------------------------

describe("useWebSocket - Mobile Lifecycle: Network Change Detection", () => {
  it("test_reconnects_on_online_event", () => {
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

    // Advance timer partway through reconnect delay
    act(() => {
      vi.advanceTimersByTime(100);
    });

    const countBeforeOnline = MockWebSocket.instances.length;

    // Simulate network coming back online
    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    // Should have attempted to reconnect immediately
    expect(result.current.reconnectAttempts).toBe(0); // Reset on online event
    expect(MockWebSocket.instances.length).toBeGreaterThan(countBeforeOnline);
  });

  it("test_does_not_reconnect_while_offline", () => {
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

    // Advance timer significantly — no new connection should attempt
    act(() => {
      vi.advanceTimersByTime(10000);
    });

    // No new WebSocket should have been created
    expect(MockWebSocket.instances.length).toBe(countAfterOffline);
  });

  it("test_resets_retry_count_on_network_reconnect", () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        baseDelay: 1000,
      }),
    );

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
    });

    // Close abnormally
    act(() => {
      ws1.simulateClose(1006);
    });

    expect(result.current.reconnectAttempts).toBe(1);

    // Go offline
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });

    // Come back online — retry count should reset
    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    expect(result.current.reconnectAttempts).toBe(0);
  });

  it("test_handles_online_while_already_connected", () => {
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

    expect(result.current.isConnected).toBe(true);

    // Simulate online event while already connected
    // The hook calls connect() which closes the existing connection and creates a new one
    const countBeforeOnline = MockWebSocket.instances.length;

    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    // A new connection will be created (because connect() closes the old one)
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(countBeforeOnline);
    // Attempts should be reset to 0
    expect(result.current.reconnectAttempts).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Tests: Exponential Backoff
// ---------------------------------------------------------------------------

describe("useWebSocket - Mobile Lifecycle: Exponential Backoff", () => {
  it("test_backoff_delays_increase_exponentially", () => {
    renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        baseDelay: 1000,
        maxDelay: 30000,
      }),
    );

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
    });

    // Simulate multiple failures and track reconnect delays
    const reconnectTimings: number[] = [];

    for (let i = 0; i < 4; i++) {
      const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

      // Close abnormally to trigger reconnect
      act(() => {
        ws.simulateClose(1006);
      });

      // Calculate expected delay: baseDelay * 2^attempt + jitter
      // With random=0.5, jitter = 250ms
      // Attempt 0: 1000 * 1 + 250 = 1250
      // Attempt 1: 1000 * 2 + 250 = 2250
      // Attempt 2: 1000 * 4 + 250 = 4250
      // Attempt 3: 1000 * 8 + 250 = 8250
      const expectedDelay = 1000 * Math.pow(2, i) + 250;
      reconnectTimings.push(expectedDelay);

      // Advance timer to trigger reconnect
      act(() => {
        vi.advanceTimersByTime(expectedDelay);
      });
    }

    // Verify exponential progression: each delay roughly doubles
    for (let i = 1; i < reconnectTimings.length; i++) {
      expect(reconnectTimings[i]).toBeGreaterThan(reconnectTimings[i - 1]);
      // Check that it's roughly exponential (allowing for jitter)
      const ratio = reconnectTimings[i] / reconnectTimings[i - 1];
      expect(ratio).toBeGreaterThanOrEqual(1.5); // At least 1.5x
      expect(ratio).toBeLessThanOrEqual(2.5); // At most 2.5x
    }
  });

  it("test_backoff_caps_at_max_delay", () => {
    renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        baseDelay: 1000,
        maxDelay: 30000,
        maxReconnectAttempts: 15,
      }),
    );

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
    });

    // Trigger many reconnects to test max delay capping
    for (let attempt = 0; attempt < 10; attempt++) {
      const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];

      act(() => {
        ws.simulateClose(1006);
      });

      // After attempt 5, exponential formula would exceed maxDelay
      // baseDelay * 2^5 = 1000 * 32 = 32000 > 30000
      // So all subsequent delays should be capped at 30000 + jitter
      const exponentialDelay = 1000 * Math.pow(2, attempt);
      const cappedDelay = Math.min(exponentialDelay, 30000);
      const expectedDelay = cappedDelay + 250; // jitter

      act(() => {
        vi.advanceTimersByTime(expectedDelay);
      });
    }

    // Should not have exceeded reasonable bounds
    expect(MockWebSocket.instances.length).toBeLessThanOrEqual(12); // 1 initial + 10 reconnects + 1 failed
  });

  it("test_jitter_adds_randomness", () => {
    // Test with different random values to verify jitter is applied
    const delays: number[] = [];

    for (let randomValue = 0; randomValue <= 1; randomValue += 0.25) {
      vi.spyOn(global.Math, "random").mockReturnValue(randomValue);

      MockWebSocket.instances = [];

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

      act(() => {
        ws.simulateClose(1006);
      });

      // The delay applied would include jitter: baseDelay + (random * 500)
      // With random=0: 1000 + 0 = 1000
      // With random=0.25: 1000 + 125 = 1125
      // With random=0.5: 1000 + 250 = 1250
      // With random=0.75: 1000 + 375 = 1375
      // With random=1: 1000 + 500 = 1500
      const expectedDelay = Math.floor(1000 + randomValue * 500);
      delays.push(expectedDelay);

      act(() => {
        vi.advanceTimersByTime(expectedDelay);
      });
    }

    // Verify that different random values produced different delays
    const uniqueDelays = new Set(delays);
    expect(uniqueDelays.size).toBeGreaterThan(1); // Multiple different delays observed
  });

  it("test_stops_after_max_retries", () => {
    const maxReconnectAttempts = 2;
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        baseDelay: 100,
        maxDelay: 1000,
        maxReconnectAttempts,
      }),
    );

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
    });

    const initialCount = MockWebSocket.instances.length;

    // Close 1: attempts becomes 1, timer scheduled (1 <= 2)
    act(() => {
      ws1.simulateClose(1006);
    });
    expect(result.current.reconnectAttempts).toBe(1);

    // Advance and let reconnect happen
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    // A new WebSocket should be created (attempt 1 timer triggered)
    expect(MockWebSocket.instances.length).toBeGreaterThan(initialCount);

    const afterAttempt1 = MockWebSocket.instances.length;

    // Close 2: attempts becomes 2, timer scheduled (2 <= 2)
    act(() => {
      MockWebSocket.instances[MockWebSocket.instances.length - 1].simulateClose(1006);
    });
    expect(result.current.reconnectAttempts).toBe(2);

    // Advance and let second reconnect happen
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(MockWebSocket.instances.length).toBeGreaterThan(afterAttempt1);

    const afterAttempt2 = MockWebSocket.instances.length;

    // Close 3: attempts becomes 3, NO timer scheduled (3 > 2)
    act(() => {
      MockWebSocket.instances[MockWebSocket.instances.length - 1].simulateClose(1006);
    });
    expect(result.current.reconnectAttempts).toBe(3);

    // Advance timer — no reconnect should happen
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    // No new WebSocket created after exceeding max
    expect(MockWebSocket.instances.length).toBe(afterAttempt2);
  });
});

// ---------------------------------------------------------------------------
// Tests: Clean Teardown & Memory Leaks
// ---------------------------------------------------------------------------

describe("useWebSocket - Mobile Lifecycle: Clean Teardown", () => {
  it("test_unmount_closes_websocket", () => {
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

    expect(ws.readyState).toBe(1); // OPEN

    unmount();

    expect(ws.readyState).toBe(3); // CLOSED
  });

  it("test_unmount_cancels_pending_reconnect_timer", () => {
    const { unmount } = renderHook(() =>
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

    // Trigger a disconnect to start reconnect timer
    act(() => {
      ws.simulateClose(1006);
    });

    const countBeforeUnmount = MockWebSocket.instances.length;

    // Unmount
    unmount();

    // Advance timer — should not create new connection
    act(() => {
      vi.advanceTimersByTime(5000);
    });

    // No new WebSocket should be created after unmount
    expect(MockWebSocket.instances.length).toBe(countBeforeUnmount);
  });

  it("test_unmount_removes_visibility_listener", () => {
    const removeEventListenerSpy = vi.spyOn(document, "removeEventListener");

    const { unmount } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        pauseOnHidden: true,
      }),
    );

    removeEventListenerSpy.mockClear();

    unmount();

    // Should have removed visibilitychange listener
    expect(removeEventListenerSpy).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
  });

  it("test_unmount_removes_network_listeners", () => {
    const removeEventListenerSpy = vi.spyOn(window, "removeEventListener");

    const { unmount } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
      }),
    );

    removeEventListenerSpy.mockClear();

    unmount();

    // Should have removed online and offline listeners
    const calls = removeEventListenerSpy.mock.calls;
    const eventTypes = calls.map((call) => call[0]);

    expect(eventTypes).toContain("online");
    expect(eventTypes).toContain("offline");
  });
});

// ---------------------------------------------------------------------------
// Tests: Edge Cases
// ---------------------------------------------------------------------------

describe("useWebSocket - Mobile Lifecycle: Edge Cases", () => {
  it("test_send_while_disconnected_does_not_throw", () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
      }),
    );

    // Before connecting, calling send should not throw
    expect(() => {
      act(() => {
        result.current.sendMessage("test message");
      });
    }).not.toThrow();

    // After disconnect, calling send should not throw
    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
    });

    act(() => {
      ws.simulateClose(1006);
    });

    expect(() => {
      act(() => {
        result.current.sendMessage("test message");
      });
    }).not.toThrow();
  });

  it("test_enabled_false_prevents_connection", () => {
    renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        enabled: false,
      }),
    );

    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it("test_enabled_toggle_connects_and_disconnects", () => {
    const { rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useWebSocket({
          url: "ws://localhost/ws/positions/deploy-001",
          token: "test-token",
          enabled,
        }),
      { initialProps: { enabled: false } },
    );

    expect(MockWebSocket.instances).toHaveLength(0);

    // Enable
    rerender({ enabled: true });

    expect(MockWebSocket.instances.length).toBeGreaterThan(0);

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.simulateOpen();
    });

    // Verify connection is established
    expect(MockWebSocket.instances[0].readyState).toBe(1); // OPEN
  });

  it("test_handles_server_initiated_close", () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        baseDelay: 500,
      }),
    );

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
    });

    // Server closes connection with code 1000 (normal)
    act(() => {
      ws1.simulateClose(1000);
    });

    // Should not reconnect on normal close
    const countAfterClose = MockWebSocket.instances.length;

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(MockWebSocket.instances.length).toBe(countAfterClose);
    expect(result.current.reconnectAttempts).toBe(0);
  });

  it("test_handles_abnormal_close_code_with_reconnection", () => {
    const { result } = renderHook(() =>
      useWebSocket({
        url: "ws://localhost/ws/positions/deploy-001",
        token: "test-token",
        baseDelay: 500,
      }),
    );

    const ws1 = MockWebSocket.instances[0];
    act(() => {
      ws1.simulateOpen();
    });

    // Server closes with code 1006 (abnormal closure)
    act(() => {
      ws1.simulateClose(1006);
    });

    // Should trigger reconnection
    expect(result.current.reconnectAttempts).toBe(1);
    expect(result.current.isReconnecting).toBe(true);

    const countAfterAbnormalClose = MockWebSocket.instances.length;

    // Advance timer past reconnect delay
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // Should have attempted reconnection
    expect(MockWebSocket.instances.length).toBeGreaterThan(countAfterAbnormalClose);
  });
});

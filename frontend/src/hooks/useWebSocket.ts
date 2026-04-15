/**
 * Reusable WebSocket hook with auto-reconnect, exponential backoff, and mobile lifecycle awareness.
 *
 * Responsibilities:
 * - Establish and maintain a WebSocket connection.
 * - Auto-reconnect with exponential backoff and jitter on disconnection.
 * - Track connection state (connecting, connected, disconnected, error).
 * - Parse incoming JSON messages and dispatch to callbacks.
 * - Pause/resume connections on visibility change (mobile Safari optimization).
 * - Detect network changes (online/offline) and reconnect on recovery.
 * - Provide connection status and retry information for the UI.
 *
 * Does NOT:
 * - Handle authentication (caller provides token in URL).
 * - Contain business logic or domain-specific parsing.
 * - Persist state across page reloads.
 *
 * Dependencies:
 * - React: useState, useEffect, useRef, useCallback.
 * - Browser APIs: WebSocket, Visibility API, window.online/offline events.
 *
 * Mobile Lifecycle Behavior:
 * - On page visibility hidden (iOS Safari): Closes connection gracefully with code 1000.
 * - On page visibility visible: Reconnects immediately and resets retry count.
 * - On window.online event: Reconnects immediately and resets retry count.
 * - On window.offline event: Skips reconnection attempts until network recovers.
 *
 * Example:
 *   const { status, lastMessage, sendMessage, isConnected } = useWebSocket({
 *     url: "ws://localhost:8000/ws/positions/deploy-001",
 *     token: accessToken,
 *     onMessage: (data) => console.log(data),
 *     pauseOnHidden: true,  // iOS Safari optimization
 *   });
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** WebSocket connection states. */
export type WsStatus = "connecting" | "connected" | "disconnected" | "error";

/** Options for the useWebSocket hook. */
export interface UseWebSocketOptions {
  /** Full WebSocket URL (without token — appended automatically). */
  url: string;
  /** JWT token for authentication. */
  token: string | null;
  /** Callback when a JSON message is received. */
  onMessage?: (data: Record<string, unknown>) => void;
  /** Callback when connection status changes. */
  onStatusChange?: (status: WsStatus) => void;
  /** Maximum reconnect attempts before giving up. Default: 10. */
  maxReconnectAttempts?: number;
  /** Base delay for exponential backoff in ms. Default: 1000. */
  baseDelay?: number;
  /** Maximum delay between reconnect attempts in ms. Default: 30000. */
  maxDelay?: number;
  /** Whether to automatically connect. Default: true. */
  enabled?: boolean;
  /** Whether to pause/resume on page visibility change (mobile optimization). Default: true. */
  pauseOnHidden?: boolean;
}

/** Return value from the useWebSocket hook. */
export interface UseWebSocketReturn {
  /** Current connection status. */
  status: WsStatus;
  /** Last received JSON message. */
  lastMessage: Record<string, unknown> | null;
  /** Send a text message over the WebSocket. */
  sendMessage: (data: string) => void;
  /** Manually reconnect. */
  reconnect: () => void;
  /** Number of reconnect attempts since last successful connection. */
  reconnectAttempts: number;
  /** Whether the WebSocket is currently connected. */
  isConnected: boolean;
  /** Whether currently attempting to reconnect. */
  isReconnecting: boolean;
}

/**
 * React hook for WebSocket connections with auto-reconnect and mobile lifecycle awareness.
 *
 * Manages the full WebSocket lifecycle: connect, receive messages,
 * handle disconnections, auto-reconnect with exponential backoff, and mobile optimizations.
 *
 * Mobile Optimizations:
 * - Pauses/resumes connection on page visibility changes (iOS Safari).
 * - Reconnects immediately when network comes back online.
 * - Uses exponential backoff with jitter to avoid thundering herd.
 *
 * @param options - Configuration for the WebSocket connection.
 * @returns Connection status, last message, control functions, and connection state flags.
 *
 * @throws Never throws. Errors are captured in state and callbacks.
 *
 * @example
 *   const { status, lastMessage, isConnected, sendMessage } = useWebSocket({
 *     url: "ws://localhost:8000/ws/positions/deploy-001",
 *     token: accessToken,
 *     onMessage: handleMessage,
 *     pauseOnHidden: true,
 *   });
 */
export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const {
    url,
    token,
    onMessage,
    onStatusChange,
    maxReconnectAttempts = 10,
    baseDelay = 1000,
    maxDelay = 30000,
    enabled = true,
    pauseOnHidden = true,
  } = options;

  const [status, setStatus] = useState<WsStatus>("disconnected");
  const [lastMessage, setLastMessage] = useState<Record<string, unknown> | null>(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onMessageRef = useRef(onMessage);
  const onStatusChangeRef = useRef(onStatusChange);
  const isOnlineRef = useRef(typeof navigator !== "undefined" ? navigator.onLine : true);
  const isConnectingRef = useRef(false);

  // Keep callback refs up to date without triggering reconnects
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    onStatusChangeRef.current = onStatusChange;
  }, [onStatusChange]);

  const updateStatus = useCallback((newStatus: WsStatus) => {
    setStatus(newStatus);
    onStatusChangeRef.current?.(newStatus);
  }, []);

  const connect = useCallback(() => {
    if (!token || !enabled || !isOnlineRef.current || isConnectingRef.current) return;

    // Guard against double-connect
    isConnectingRef.current = true;

    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    // Clear any pending reconnect timer
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    updateStatus("connecting");

    const wsUrl = `${url}?token=${encodeURIComponent(token)}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      isConnectingRef.current = false;
      updateStatus("connected");
      setReconnectAttempts(0);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as Record<string, unknown>;
        setLastMessage(data);
        onMessageRef.current?.(data);
      } catch {
        // Non-JSON messages (e.g., "pong") are ignored
      }
    };

    ws.onerror = () => {
      isConnectingRef.current = false;
      updateStatus("error");
    };

    ws.onclose = (event) => {
      isConnectingRef.current = false;
      wsRef.current = null;

      // Don't reconnect if manually closed or auth failure
      if (event.code === 4008 || event.code === 1000) {
        updateStatus("disconnected");
        return;
      }

      updateStatus("disconnected");

      // Auto-reconnect with exponential backoff + jitter
      // Only reconnect if we're online
      if (isOnlineRef.current) {
        setReconnectAttempts((prev) => {
          const nextAttempt = prev + 1;
          if (nextAttempt <= maxReconnectAttempts) {
            // Exponential backoff: base * 2^attempt, capped at maxDelay
            const exponentialDelay = baseDelay * Math.pow(2, prev);
            const cappedDelay = Math.min(exponentialDelay, maxDelay);
            // Add jitter: random value between 0 and 500ms
            const jitterMs = Math.random() * 500;
            const totalDelay = Math.floor(cappedDelay + jitterMs);
            reconnectTimerRef.current = setTimeout(connect, totalDelay);
          }
          return nextAttempt;
        });
      }
    };

    wsRef.current = ws;
  }, [url, token, enabled, maxReconnectAttempts, baseDelay, maxDelay, updateStatus]);

  const sendMessage = useCallback((data: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  const reconnect = useCallback(() => {
    setReconnectAttempts(0);
    connect();
  }, [connect]);

  // Network connectivity listener
  useEffect(() => {
    const handleOnline = () => {
      isOnlineRef.current = true;
      // Reconnect immediately when network comes back
      setReconnectAttempts(0);
      connect();
    };

    const handleOffline = () => {
      isOnlineRef.current = false;
      // Close the connection gracefully
      if (wsRef.current) {
        wsRef.current.close(1000, "Network offline");
      }
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, [connect]);

  // Page visibility listener (mobile optimization for iOS Safari)
  useEffect(() => {
    if (!pauseOnHidden) return;

    const handleVisibilityChange = () => {
      if (document.hidden) {
        // Page hidden: close connection gracefully to prevent iOS Safari from killing it ungracefully
        if (wsRef.current) {
          wsRef.current.close(1000, "Page hidden");
          wsRef.current = null;
        }
        // Cancel pending reconnect timer
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = null;
        }
        updateStatus("disconnected");
      } else {
        // Page visible: reconnect immediately and reset retry count
        setReconnectAttempts(0);
        connect();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [pauseOnHidden, connect, updateStatus]);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    if (enabled && token) {
      connect();
    }

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounting");
        wsRef.current = null;
      }
    };
  }, [connect, enabled, token]);

  const isConnected = status === "connected";
  const isReconnecting = status === "disconnected" && reconnectAttempts > 0;

  return {
    status,
    lastMessage,
    sendMessage,
    reconnect,
    reconnectAttempts,
    isConnected,
    isReconnecting,
  };
}

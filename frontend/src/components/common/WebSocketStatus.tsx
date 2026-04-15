/**
 * WebSocket connection status indicator component.
 *
 * Responsibilities:
 * - Display real-time WebSocket connection status.
 * - Show connection state: connected, reconnecting, or disconnected.
 * - Display retry attempt count when reconnecting.
 * - Provide visual feedback for users on mobile and desktop.
 *
 * Does NOT:
 * - Manage the WebSocket connection (delegated to useWebSocket hook).
 * - Contain business logic.
 * - Handle user interactions beyond display.
 *
 * Dependencies:
 * - React: React types for JSX.
 * - Tailwind CSS for styling.
 *
 * States:
 * - Connected: green dot + "Live" label.
 * - Reconnecting: amber dot + "Reconnecting..." + attempt count.
 * - Disconnected: red dot + "Disconnected" label.
 *
 * Example:
 *   <WebSocketStatus
 *     isConnected={ws.isConnected}
 *     isReconnecting={ws.isReconnecting}
 *     retryCount={ws.reconnectAttempts}
 *     className="ml-4"
 *   />
 */

import type React from "react";

/**
 * Props for the WebSocketStatus component.
 */
export interface WebSocketStatusProps {
  /** Whether the WebSocket is currently connected. */
  isConnected: boolean;
  /** Whether currently attempting to reconnect. */
  isReconnecting: boolean;
  /** Number of reconnection attempts made. */
  retryCount: number;
  /** Optional CSS class for additional styling. */
  className?: string;
}

/**
 * WebSocketStatus displays the current WebSocket connection state.
 *
 * Renders a small, unobtrusive indicator with a colored dot and label,
 * showing: Connected (green), Reconnecting (amber), or Disconnected (red).
 *
 * @param props - Component props.
 * @returns React component displaying connection status.
 *
 * @example
 *   <WebSocketStatus
 *     isConnected={true}
 *     isReconnecting={false}
 *     retryCount={0}
 *   />
 *   // Renders: 🟢 Live
 */
export function WebSocketStatus({
  isConnected,
  isReconnecting,
  retryCount,
  className = "",
}: WebSocketStatusProps): React.ReactElement {
  if (isConnected) {
    return (
      <div
        className={`inline-flex items-center gap-2 text-xs font-medium text-green-700 ${className}`}
      >
        <div className="h-2 w-2 rounded-full bg-green-500" />
        <span>Live</span>
      </div>
    );
  }

  if (isReconnecting) {
    return (
      <div
        className={`inline-flex items-center gap-2 text-xs font-medium text-amber-700 ${className}`}
      >
        <div className="h-2 w-2 animate-pulse rounded-full bg-amber-500" />
        <span>
          Reconnecting... <span className="text-amber-600">(attempt {retryCount})</span>
        </span>
      </div>
    );
  }

  // Disconnected state
  return (
    <div className={`inline-flex items-center gap-2 text-xs font-medium text-red-700 ${className}`}>
      <div className="h-2 w-2 rounded-full bg-red-500" />
      <span>Disconnected</span>
    </div>
  );
}

export default WebSocketStatus;

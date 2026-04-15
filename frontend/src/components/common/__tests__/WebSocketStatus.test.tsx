/**
 * Unit tests for WebSocketStatus component.
 *
 * Verifies:
 * - Displays green dot and "Live" when connected.
 * - Displays amber dot and "Reconnecting..." with attempt count when reconnecting.
 * - Displays red dot and "Disconnected" when disconnected.
 * - Applies custom className.
 * - Renders correct semantic HTML.
 *
 * Dependencies:
 * - vitest for testing framework.
 * - @testing-library/react for render.
 */

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { WebSocketStatus } from "../WebSocketStatus";

describe("WebSocketStatus", () => {
  describe("connected state", () => {
    it("displays green dot and Live label when connected", () => {
      render(<WebSocketStatus isConnected={true} isReconnecting={false} retryCount={0} />);

      expect(screen.getByText("Live")).toBeInTheDocument();
      const dot = screen.getByText("Live").previousElementSibling;
      expect(dot).toHaveClass("bg-green-500");
    });

    it("has green text color when connected", () => {
      const { container } = render(
        <WebSocketStatus isConnected={true} isReconnecting={false} retryCount={0} />,
      );

      const statusDiv = container.firstChild as HTMLElement;
      expect(statusDiv).toHaveClass("text-green-700");
    });
  });

  describe("reconnecting state", () => {
    it("displays amber dot and Reconnecting label with attempt count", () => {
      render(<WebSocketStatus isConnected={false} isReconnecting={true} retryCount={3} />);

      expect(screen.getByText(/Reconnecting.../i)).toBeInTheDocument();
      expect(screen.getByText(/attempt 3/i)).toBeInTheDocument();

      const dot = screen
        .getByText(/Reconnecting.../i)
        .parentElement?.querySelector(".bg-amber-500");
      expect(dot).toBeInTheDocument();
    });

    it("has amber text color when reconnecting", () => {
      const { container } = render(
        <WebSocketStatus isConnected={false} isReconnecting={true} retryCount={1} />,
      );

      const statusDiv = container.firstChild as HTMLElement;
      expect(statusDiv).toHaveClass("text-amber-700");
    });

    it("displays attempt count in subdued color", () => {
      render(<WebSocketStatus isConnected={false} isReconnecting={true} retryCount={5} />);

      const attemptSpan = screen.getByText(/attempt 5/i);
      expect(attemptSpan).toHaveClass("text-amber-600");
    });

    it("applies pulse animation to amber dot", () => {
      const { container } = render(
        <WebSocketStatus isConnected={false} isReconnecting={true} retryCount={2} />,
      );

      const dot = container.querySelector(".bg-amber-500");
      expect(dot).toHaveClass("animate-pulse");
    });
  });

  describe("disconnected state", () => {
    it("displays red dot and Disconnected label when disconnected", () => {
      render(<WebSocketStatus isConnected={false} isReconnecting={false} retryCount={0} />);

      expect(screen.getByText("Disconnected")).toBeInTheDocument();
      const dot = screen.getByText("Disconnected").previousElementSibling;
      expect(dot).toHaveClass("bg-red-500");
    });

    it("has red text color when disconnected", () => {
      const { container } = render(
        <WebSocketStatus isConnected={false} isReconnecting={false} retryCount={0} />,
      );

      const statusDiv = container.firstChild as HTMLElement;
      expect(statusDiv).toHaveClass("text-red-700");
    });
  });

  describe("styling", () => {
    it("applies custom className", () => {
      const { container } = render(
        <WebSocketStatus
          isConnected={true}
          isReconnecting={false}
          retryCount={0}
          className="absolute ml-4"
        />,
      );

      const statusDiv = container.firstChild as HTMLElement;
      expect(statusDiv).toHaveClass("ml-4");
      expect(statusDiv).toHaveClass("absolute");
    });

    it("uses inline-flex for alignment", () => {
      const { container } = render(
        <WebSocketStatus isConnected={true} isReconnecting={false} retryCount={0} />,
      );

      const statusDiv = container.firstChild as HTMLElement;
      expect(statusDiv).toHaveClass("inline-flex");
      expect(statusDiv).toHaveClass("items-center");
      expect(statusDiv).toHaveClass("gap-2");
    });

    it("renders small text (text-xs)", () => {
      const { container } = render(
        <WebSocketStatus isConnected={true} isReconnecting={false} retryCount={0} />,
      );

      const statusDiv = container.firstChild as HTMLElement;
      expect(statusDiv).toHaveClass("text-xs");
      expect(statusDiv).toHaveClass("font-medium");
    });

    it("renders dot with correct size", () => {
      const { container } = render(
        <WebSocketStatus isConnected={true} isReconnecting={false} retryCount={0} />,
      );

      const dot = container.querySelector(".h-2.w-2");
      expect(dot).toBeInTheDocument();
      expect(dot).toHaveClass("rounded-full");
    });
  });

  describe("edge cases", () => {
    it("displays attempt count 0", () => {
      render(<WebSocketStatus isConnected={false} isReconnecting={true} retryCount={0} />);

      expect(screen.getByText(/attempt 0/i)).toBeInTheDocument();
    });

    it("displays high attempt count", () => {
      render(<WebSocketStatus isConnected={false} isReconnecting={true} retryCount={99} />);

      expect(screen.getByText(/attempt 99/i)).toBeInTheDocument();
    });

    it("prioritizes connected state over reconnecting", () => {
      // In case both flags are somehow true, connected should take priority
      const { container } = render(
        <WebSocketStatus isConnected={true} isReconnecting={true} retryCount={5} />,
      );

      // Should show "Live", not "Reconnecting"
      expect(screen.getByText("Live")).toBeInTheDocument();
      expect(screen.queryByText(/Reconnecting/i)).not.toBeInTheDocument();

      const statusDiv = container.firstChild as HTMLElement;
      expect(statusDiv).toHaveClass("text-green-700");
    });
  });
});

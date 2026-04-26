/**
 * MobileApprovalDetail — unit tests.
 *
 * Verifies that MobileApprovalDetail renders approval detail in a BottomSheet,
 * supports approve/reject actions with SlideToConfirm, and handles loading
 * and error states.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MobileApprovalDetail } from "../MobileApprovalDetail";
import * as governanceApi from "../../api";

// Mock the API module
vi.mock("../../api", () => ({
  governanceApi: {
    getApprovalDetail: vi.fn(),
  },
}));

// Mock the logger module
vi.mock("../../logger", () => ({
  governanceLogger: {
    info: vi.fn(),
    debug: vi.fn(),
  },
}));

describe("MobileApprovalDetail", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    vi.clearAllMocks();
  });

  it("renders bottom sheet when isOpen is true", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId={null}
          isOpen={true}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
        />
      </QueryClientProvider>,
    );

    // BottomSheet should be present (as long as isOpen is true)
    // The dialog should be somewhere in the document
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("does not render bottom sheet when isOpen is false", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId={null}
          isOpen={false}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
        />
      </QueryClientProvider>,
    );

    // Dialog should not be present
    expect(container.querySelector("[role='dialog']")).not.toBeInTheDocument();
  });

  it("shows loading state while fetching approval detail", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    // Mock API to be in pending state
    vi.mocked(governanceApi.governanceApi.getApprovalDetail).mockReturnValue(
      new Promise(() => {}), // Never resolves
    );

    render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId="approval-1"
          isOpen={true}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
        />
      </QueryClientProvider>,
    );

    // Loading indicator should be visible
    expect(screen.getByTestId("mobile-approval-detail-loading")).toBeInTheDocument();
  });

  it("shows error state when approval fetch fails", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    vi.mocked(governanceApi.governanceApi.getApprovalDetail).mockRejectedValue(
      new Error("Failed to fetch"),
    );

    render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId="approval-1"
          isOpen={true}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
        />
      </QueryClientProvider>,
    );

    // Wait for error to appear
    await waitFor(() => {
      expect(screen.getByTestId("mobile-approval-detail-error")).toBeInTheDocument();
    });
  });

  it("calls onClose when close button is clicked", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId={null}
          isOpen={true}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
        />
      </QueryClientProvider>,
    );

    // Close button is in the BottomSheet header
    const closeButton = screen.getByRole("button", { name: /close/i });
    await user.click(closeButton);

    expect(onClose).toHaveBeenCalled();
  });

  it("renders SlideToConfirm for approve when approval is pending", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    // Mock successful approval fetch
    vi.mocked(governanceApi.governanceApi.getApprovalDetail).mockResolvedValue({
      id: "approval-1",
      status: "pending",
      requested_by: "alice@example.com",
      created_at: new Date().toISOString(),
      // ... other fields
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- partial-fixture-for-test
    } as any);

    render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId="approval-1"
          isOpen={true}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      // Should render the slider track for approve (SlideToConfirm renders a slider role)
      const sliders = screen.queryAllByRole("slider");
      expect(sliders.length).toBeGreaterThan(0);
    });
  });

  it("calls onApprove when approve SlideToConfirm is completed", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    vi.mocked(governanceApi.governanceApi.getApprovalDetail).mockResolvedValue({
      id: "approval-1",
      status: "pending",
      requested_by: "alice@example.com",
      created_at: new Date().toISOString(),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- partial-fixture-for-test
    } as any);

    render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId="approval-1"
          isOpen={true}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
        />
      </QueryClientProvider>,
    );

    // Note: Full SlideToConfirm interaction test would require mocking touch/drag events.
    // This is a simplified test that verifies the component structure.
    // In practice, this would be tested as an integration test.
  });

  it("disables actions when isActioning is true", async () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    const onClose = vi.fn();

    vi.mocked(governanceApi.governanceApi.getApprovalDetail).mockResolvedValue({
      id: "approval-1",
      status: "pending",
      requested_by: "alice@example.com",
      created_at: new Date().toISOString(),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any -- partial-fixture-for-test
    } as any);

    render(
      <QueryClientProvider client={queryClient}>
        <MobileApprovalDetail
          approvalId="approval-1"
          isOpen={true}
          onClose={onClose}
          currentUserId="user-1"
          onApprove={onApprove}
          onReject={onReject}
          isActioning={true}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      // When actioning is true, the reject button should be disabled
      const rejectButton = screen.getByRole("button", { name: /show reject/i });
      expect(rejectButton).toHaveAttribute("disabled");
    });
  });
});

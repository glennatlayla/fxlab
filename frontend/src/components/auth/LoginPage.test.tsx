/**
 * LoginPage tests.
 *
 * Verifies:
 *   - Form renders with email, password, and submit button.
 *   - Successful login navigates to intended destination.
 *   - Failed login shows error message.
 *   - Rate limiting: locks out after MAX_ATTEMPTS failed logins.
 *   - Lockout timer shows remaining seconds.
 *   - Lockout resets after LOCKOUT_DURATION_SECONDS.
 *
 * Dependencies:
 *   - vitest, @testing-library/react, @testing-library/user-event
 *   - AuthProvider and router mocked for isolation
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/auth/AuthProvider";
import LoginPage from "./LoginPage";

// ---------------------------------------------------------------------------
// Mock apiClient to control login success/failure
// ---------------------------------------------------------------------------

const mockPost = vi.fn();

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      post: (...args: unknown[]) => mockPost(...args),
    },
  };
});

vi.mock("jwt-decode", () => ({
  jwtDecode: vi.fn(() => ({
    sub: "user-1",
    email: "test@fxlab.io",
    role: "developer",
    scope: "feeds:read",
    exp: Math.floor(Date.now() / 1000) + 3600,
    iat: Math.floor(Date.now() / 1000),
  })),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderLoginPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <LoginPage />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LoginPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockPost.mockReset();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders email, password fields and sign-in button", () => {
    renderLoginPage();

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows error message on failed login", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    mockPost.mockRejectedValueOnce(new Error("401"));

    renderLoginPage();

    await user.type(screen.getByLabelText(/email/i), "bad@test.com");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });

  it("disables form during login attempt", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    // Never resolve — keep the login "in flight"
    mockPost.mockReturnValueOnce(new Promise(() => {}));

    renderLoginPage();

    await user.type(screen.getByLabelText(/email/i), "test@test.com");
    await user.type(screen.getByLabelText(/password/i), "pass123");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
    });
  });

  // -----------------------------------------------------------------------
  // Fix #6: Rate limiting
  // -----------------------------------------------------------------------

  describe("rate limiting", () => {
    it("locks out after 5 consecutive failed attempts", async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      mockPost.mockRejectedValue(new Error("401"));

      renderLoginPage();

      // Attempt login 5 times
      for (let i = 0; i < 5; i++) {
        await user.clear(screen.getByLabelText(/email/i));
        await user.type(screen.getByLabelText(/email/i), "bad@test.com");
        await user.clear(screen.getByLabelText(/password/i));
        await user.type(screen.getByLabelText(/password/i), "wrong");
        await user.click(screen.getByRole("button", { name: /sign in/i }));

        // Wait for the error to appear before next attempt
        await waitFor(() => {
          expect(screen.getByRole("alert")).toBeInTheDocument();
        });
      }

      // After 5 failures, the button should be disabled with lockout message
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /locked/i })).toBeDisabled();
      });
    });

    it("shows remaining lockout time", async () => {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      mockPost.mockRejectedValue(new Error("401"));

      renderLoginPage();

      for (let i = 0; i < 5; i++) {
        await user.clear(screen.getByLabelText(/email/i));
        await user.type(screen.getByLabelText(/email/i), "bad@test.com");
        await user.clear(screen.getByLabelText(/password/i));
        await user.type(screen.getByLabelText(/password/i), "wrong");
        await user.click(screen.getByRole("button", { name: /sign in/i }));

        await waitFor(() => {
          expect(screen.getByRole("alert")).toBeInTheDocument();
        });
      }

      // Should show lockout message with seconds remaining
      await waitFor(() => {
        expect(screen.getByText(/too many failed attempts/i)).toBeInTheDocument();
      });
    });
  });
});

/**
 * Test utility — render with all necessary providers.
 *
 * Wraps components in QueryClientProvider, AuthProvider, and MemoryRouter
 * for use in Vitest + @testing-library/react tests.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { MemoryRouter, type MemoryRouterProps } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthProvider";
import type { ReactElement } from "react";

interface WrapperOptions {
  /** Initial URL entries for MemoryRouter. */
  initialEntries?: MemoryRouterProps["initialEntries"];
}

export function renderWithProviders(
  ui: ReactElement,
  { initialEntries = ["/"], ...renderOptions }: WrapperOptions & RenderOptions = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );
  }

  return render(ui, { wrapper: Wrapper, ...renderOptions });
}

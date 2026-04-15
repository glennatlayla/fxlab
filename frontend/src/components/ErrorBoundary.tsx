/**
 * Application-level React error boundary.
 *
 * Purpose:
 *   Catch unhandled render errors in the component tree and display a
 *   recovery UI instead of a white screen. Critical for financial
 *   applications where a blank screen provides no actionable feedback.
 *
 * Responsibilities:
 *   - Catch JavaScript errors during rendering, lifecycle methods, and
 *     constructors of the entire child component tree.
 *   - Display a branded fallback UI with error details.
 *   - Provide "Try Again" to reset the boundary and re-render children.
 *   - Provide "Go to Dashboard" link as a navigation escape hatch.
 *   - Log caught errors to console for debugging.
 *   - Report errors to Sentry for monitoring and alerting.
 *
 * Does NOT:
 *   - Catch errors in event handlers (use try/catch there).
 *   - Catch errors in async code (use error states in hooks).
 *   - Handle HTTP errors (handled by apiClient interceptors).
 *
 * Dependencies:
 *   - React (class component required for getDerivedStateFromError).
 *   - Sentry: Error reporting and monitoring.
 *
 * Error conditions:
 *   - Any unhandled error thrown during render → shows fallback UI.
 *
 * Example:
 *   <ErrorBoundary>
 *     <App />
 *   </ErrorBoundary>
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { Sentry } from "@/infrastructure/sentry";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log the error for debugging
    console.error("[ErrorBoundary] Caught render error:", error, errorInfo);

    // Report to Sentry with component stack for debugging
    Sentry.captureException(error, {
      contexts: {
        react: {
          componentStack: errorInfo.componentStack,
        },
      },
    });
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div role="alert" className="flex min-h-screen items-center justify-center bg-surface-50">
        <div className="w-full max-w-md text-center">
          <div className="mb-4 text-6xl text-danger">!</div>
          <h1 className="text-xl font-semibold text-surface-900">Something went wrong</h1>
          <p className="mt-2 text-sm text-surface-500">
            An unexpected error occurred. You can try again or return to the dashboard.
          </p>

          {this.state.error && (
            <pre className="mt-4 overflow-auto rounded-md border border-surface-200 bg-surface-100 p-3 text-left font-mono text-xs text-surface-700">
              {this.state.error.message}
            </pre>
          )}

          <div className="mt-6 flex justify-center gap-3">
            <button
              type="button"
              onClick={this.handleReset}
              className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
            >
              Try Again
            </button>
            <a
              href="/"
              className="inline-flex items-center rounded-md border border-surface-300 bg-white px-4 py-2 text-sm font-medium text-surface-700 hover:bg-surface-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2"
            >
              Go to Dashboard
            </a>
          </div>
        </div>
      </div>
    );
  }
}

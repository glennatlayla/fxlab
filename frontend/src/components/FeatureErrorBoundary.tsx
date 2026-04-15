/**
 * Feature-level error boundary for page sections and features.
 *
 * Purpose:
 *   Catch and gracefully handle render errors in individual features
 *   (e.g., Strategy Studio, Approvals, Runs) without crashing the entire
 *   application. Shows inline error UI with a retry button.
 *
 * Responsibilities:
 *   - Catch JavaScript errors in child component tree.
 *   - Display an inline error card instead of full-page error.
 *   - Report error to Sentry with feature name as tag.
 *   - Provide retry button to reset the boundary.
 *   - Allow custom fallback UI via prop.
 *
 * Does NOT:
 *   - Affect other features — only wraps one section of a page.
 *   - Catch async errors (use error states in hooks).
 *   - Catch event handler errors (use try/catch there).
 *
 * Dependencies:
 *   - React (class component required for getDerivedStateFromError).
 *   - Sentry: Error reporting.
 *
 * Error conditions:
 *   - Any unhandled error thrown during render → shows fallback UI.
 *
 * Example:
 *   <FeatureErrorBoundary featureName="Strategy Studio">
 *     <StrategyStudioContent />
 *   </FeatureErrorBoundary>
 *
 *   With custom fallback:
 *   <FeatureErrorBoundary featureName="Approvals" fallback={<CustomError />}>
 *     <ApprovalsContent />
 *   </FeatureErrorBoundary>
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { Sentry } from "@/infrastructure/sentry";

interface FeatureErrorBoundaryProps {
  children: ReactNode;
  /**
   * Human-readable name of the feature (e.g., "Strategy Studio", "Approvals").
   * Sent to Sentry as a tag for filtering and alerting.
   */
  featureName: string;
  /**
   * Optional custom fallback UI. If not provided, a default inline error card is shown.
   */
  fallback?: ReactNode;
}

interface FeatureErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class FeatureErrorBoundary extends Component<
  FeatureErrorBoundaryProps,
  FeatureErrorBoundaryState
> {
  constructor(props: FeatureErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): FeatureErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log to console for local debugging
    console.error(
      `[FeatureErrorBoundary] Feature "${this.props.featureName}" failed:`,
      error,
      errorInfo,
    );

    // Report to Sentry with feature name as tag
    Sentry.captureException(error, {
      tags: {
        feature: this.props.featureName,
      },
      contexts: {
        react: {
          componentStack: errorInfo.componentStack,
        },
      },
    });
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    // If custom fallback is provided, show it
    if (this.props.fallback) {
      return this.props.fallback;
    }

    // Default inline error card
    return (
      <div
        role="alert"
        className="border-danger-200 bg-danger-50 rounded-lg border p-4 text-center"
      >
        <h3 className="text-danger-900 text-sm font-semibold">
          {this.props.featureName} failed to load
        </h3>
        <p className="text-danger-700 mt-1 text-xs">
          An unexpected error occurred in this section.
        </p>

        {this.state.error && (
          <pre className="border-danger-200 bg-danger-100 text-danger-800 mt-3 overflow-auto rounded border p-2 text-left font-mono text-xs">
            {this.state.error.message}
          </pre>
        )}

        <button
          type="button"
          onClick={this.handleRetry}
          className="bg-danger-600 hover:bg-danger-700 focus:ring-danger-500 mt-3 rounded px-3 py-1 text-xs font-medium text-white focus:outline-none focus:ring-2 focus:ring-offset-2"
        >
          Try again
        </button>
      </div>
    );
  }
}

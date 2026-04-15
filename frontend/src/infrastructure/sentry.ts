/**
 * Sentry error tracking initialization and configuration.
 *
 * Purpose:
 *   Initialize and configure Sentry for client-side error tracking,
 *   performance monitoring, and session replay.
 *
 * Responsibilities:
 *   - Initialize Sentry with environment-specific configuration.
 *   - Set appropriate sample rates for development and production.
 *   - Mask personally identifiable information (PII) before sending.
 *   - Warn in production when DSN is not provided.
 *   - Export Sentry for use in error boundaries and exception handlers.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Make API calls or perform I/O.
 *   - Store secrets in code (DSN comes from VITE_SENTRY_DSN env var).
 *
 * Dependencies:
 *   - @sentry/react: Error tracking SDK
 *   - getConfig() from @/config/env: Environment configuration
 *
 * Error conditions:
 *   - No errors raised; gracefully skips initialization if DSN is missing.
 *
 * Example:
 *   import { initSentry } from "@/infrastructure/sentry";
 *   initSentry();  // Call early in main.tsx before app renders
 */

import * as Sentry from "@sentry/react";
import { getConfig } from "@/config/env";

/**
 * Initialize Sentry error tracking with environment-specific config.
 *
 * If VITE_SENTRY_DSN is not provided:
 *   - Logs a warning if running in production.
 *   - Silently skips initialization in development.
 *
 * Integrations enabled:
 *   - Browser tracing: Captures performance metrics.
 *   - Session replay: Records user sessions on error (privacy-masked).
 *
 * Sample rates:
 *   - Development: 100% tracing, 10% session, 100% on-error replay.
 *   - Production: 20% tracing, 10% session, 100% on-error replay.
 *
 * PII masking:
 *   - Removes email and IP address from user context before sending.
 *   - Preserves user ID for identification.
 *
 * Returns:
 *   void (modifies global Sentry state).
 *
 * Example:
 *   initSentry();
 */
export function initSentry(): void {
  const config = getConfig();
  const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;

  // Skip if DSN not provided. Warn in production only.
  if (!dsn) {
    if (config.isProduction) {
      console.warn("[Sentry] VITE_SENTRY_DSN not set — error tracking disabled in production");
    }
    return;
  }

  const appVersion = import.meta.env.VITE_APP_VERSION || "0.0.0";
  const tracesSampleRate = config.isProduction ? 0.2 : 1.0;

  Sentry.init({
    dsn,
    environment: config.isProduction ? "production" : "development",
    release: `fxlab-frontend@${appVersion}`,
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],
    tracesSampleRate,
    replaysSessionSampleRate: 0.1,
    replaysOnErrorSampleRate: 1.0,

    /**
     * beforeSend hook: Mask PII before events leave the client.
     * Never send email addresses, IP addresses, or other sensitive data.
     */
    beforeSend(event) {
      if (event.user) {
        // Remove PII — keep only user ID for identification
        delete event.user.email;
        delete event.user.ip_address;
      }
      return event;
    },
  });
}

export { Sentry };

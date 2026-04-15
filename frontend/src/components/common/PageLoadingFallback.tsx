/**
 * PageLoadingFallback — loading spinner shown while a code-split page loads.
 *
 * Purpose:
 *   Provide a consistent visual feedback while lazy-loaded route components
 *   are being fetched and parsed by the browser.
 *
 * Used in:
 *   Router Suspense boundaries for all protected routes.
 *
 * Example:
 *   <Suspense fallback={<PageLoadingFallback />}>
 *     <StrategyStudio />
 *   </Suspense>
 */

export function PageLoadingFallback() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <div className="h-12 w-12 animate-spin rounded-full border-4 border-brand-500 border-t-transparent" />
        <p className="text-sm text-surface-500">Loading...</p>
      </div>
    </div>
  );
}

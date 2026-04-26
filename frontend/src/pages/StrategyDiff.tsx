/**
 * StrategyDiff — side-by-side structural diff of two saved strategies' IRs.
 *
 * Purpose:
 *   Top-level page for the route ``/strategies/diff?a={idA}&b={idB}``.
 *   Renders the parsed IR for each strategy with structural differences
 *   tinted (added → green, removed → red, changed → amber, unchanged →
 *   neutral) so operators can review a clone or a hand-edited variant
 *   without flipping between two browser tabs.
 *
 * Responsibilities:
 *   - Read ``a`` and ``b`` URL search params via ``useSearchParams``.
 *   - Validate both look like ULIDs; surface a "Pick two strategies"
 *     CTA back to ``/strategies`` if either is missing or malformed.
 *   - Fetch both strategies in parallel via :func:`fetchStrategyDiff`.
 *   - Compute the structural diff via :func:`diffIr` from
 *     ``lib/ir_diff`` (memoised on the loaded payload to avoid
 *     re-walking the IR on every render).
 *   - Render two header columns (strategy name + ID + version) plus a
 *     summary block (added / removed / changed counts) and the diff
 *     tree as a flat list of rows tinted by node kind.
 *   - Provide a "Hide unchanged" toggle (default OFF) that filters
 *     unchanged rows out of the rendered tree without re-fetching.
 *   - Provide a "Switch A↔B" button that swaps the URL params (the
 *     effect re-fetches with the new ordering).
 *   - Provide a "Pick different strategies" link to ``/strategies``.
 *
 * Does NOT:
 *   - Mutate any strategy state. Read-only page.
 *   - Compute the diff for non-IR strategies (draft_form rows do not
 *     have a parsed_ir; the page surfaces a typed warning when either
 *     side has parsed_ir === null and skips the tree section).
 *
 * Dependencies:
 *   - useAuth from @/auth/useAuth (assert authenticated session).
 *   - fetchStrategyDiff from @/api/strategy_diff (parallel orchestrator).
 *   - diffIr from @/lib/ir_diff (pure structural diff).
 *
 * Route: ``/strategies/diff`` (protected by ``strategies:write`` scope
 *   via AuthGuard at the router layer — matches the rest of the
 *   strategies surface).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";
import { GetStrategyError, type StrategyDetail } from "@/api/strategies";
import { fetchStrategyDiff, type StrategyDiffData } from "@/api/strategy_diff";
import { diffIr, type DiffNode } from "@/lib/ir_diff";

// ---------------------------------------------------------------------------
// ULID validation — mirrors RunCompare so the two pages reject the same
// set of malformed inputs without a 422 round-trip.
// ---------------------------------------------------------------------------

const ULID_REGEX = /^[0-9A-HJKMNP-TV-Z]{26}$/i;

/**
 * Return ``true`` when ``value`` looks like a 26-character Crockford
 * Base32 ULID. The backend uses the same character set; rejecting
 * client-side avoids a wasted round-trip for obviously bogus IDs.
 */
function isUlidLike(value: string | null | undefined): value is string {
  return typeof value === "string" && ULID_REGEX.test(value);
}

// ---------------------------------------------------------------------------
// Diff-row presentation helpers
// ---------------------------------------------------------------------------

/**
 * Tailwind class fragment for a diff row's background tint. The colour
 * tokens (green / red / amber / surface) match the Run Compare page so
 * the two comparison surfaces feel like one product.
 */
function rowClass(kind: DiffNode["kind"]): string {
  switch (kind) {
    case "added":
      return "border-green-200 bg-green-50";
    case "removed":
      return "border-red-200 bg-red-50";
    case "changed":
      return "border-amber-200 bg-amber-50";
    case "unchanged":
      return "border-surface-100 bg-white";
  }
}

/**
 * One-character marker so each row's kind reads at a glance even in
 * a colour-blind context. Mirrors common diff conventions (+/-/Δ/·).
 */
function kindMarker(kind: DiffNode["kind"]): string {
  switch (kind) {
    case "added":
      return "+";
    case "removed":
      return "-";
    case "changed":
      return "Δ";
    case "unchanged":
      return "·";
  }
}

/**
 * Render a value as a compact JSON snippet for the row body. Strings
 * are quoted; primitives are rendered with ``JSON.stringify`` so the
 * type is unambiguous (e.g. ``"14"`` vs ``14``). Objects / arrays are
 * stringified with two-space indent so nested IR fragments are
 * legible inside the row.
 */
function formatValue(value: unknown): string {
  if (value === undefined) return "undefined";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    // Fallback for cyclic structures — should not occur for IR rows
    // but defensive rendering avoids a crash if upstream sends one.
    return String(value);
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface StrategyHeaderPanelProps {
  side: "A" | "B";
  strategy: StrategyDetail;
}

/**
 * Compact header card showing the strategy name, ID, version, source,
 * and archive state for one side of the comparison.
 */
function StrategyHeaderPanel({ side, strategy }: StrategyHeaderPanelProps) {
  return (
    <div
      className="flex flex-col gap-1 rounded-lg border border-surface-200 bg-white p-4 shadow-sm"
      data-testid={`strategy-diff-panel-${side.toLowerCase()}`}
    >
      <p className="text-2xs font-semibold uppercase tracking-wider text-surface-400">
        Strategy {side}
      </p>
      <p className="text-base font-semibold text-surface-900">{strategy.name}</p>
      <p className="break-all font-mono text-xs text-surface-500">{strategy.id}</p>
      <p className="mt-1 text-xs text-surface-600">
        v{strategy.version} ·{" "}
        <span className="font-medium">
          {strategy.source === "ir_upload" ? "Imported IR" : "Draft form"}
        </span>
        {strategy.archived_at ? <span className="ml-2 text-amber-700">· archived</span> : null}
      </p>
    </div>
  );
}

interface DiffSummaryProps {
  nodes: DiffNode[];
}

/**
 * Counts of added / removed / changed / unchanged nodes in the diff,
 * displayed as a horizontal pill bar above the tree.
 */
function DiffSummary({ nodes }: DiffSummaryProps) {
  // Bucket the nodes by kind in a single pass so we render one number
  // per kind without re-iterating the array four times.
  const counts = useMemo(() => {
    const acc: Record<DiffNode["kind"], number> = {
      added: 0,
      removed: 0,
      changed: 0,
      unchanged: 0,
    };
    for (const n of nodes) acc[n.kind] += 1;
    return acc;
  }, [nodes]);

  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-lg border border-surface-200 bg-white p-3 text-sm"
      data-testid="strategy-diff-summary"
    >
      <span className="font-semibold text-surface-700">Summary:</span>
      <span
        className="rounded-md border border-green-200 bg-green-50 px-2 py-0.5 text-green-800"
        data-testid="strategy-diff-summary-added"
      >
        + {counts.added} added
      </span>
      <span
        className="rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-red-800"
        data-testid="strategy-diff-summary-removed"
      >
        - {counts.removed} removed
      </span>
      <span
        className="rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-amber-800"
        data-testid="strategy-diff-summary-changed"
      >
        Δ {counts.changed} changed
      </span>
      <span
        className="rounded-md border border-surface-200 bg-surface-50 px-2 py-0.5 text-surface-700"
        data-testid="strategy-diff-summary-unchanged"
      >
        · {counts.unchanged} unchanged
      </span>
    </div>
  );
}

interface DiffRowProps {
  node: DiffNode;
}

/**
 * One row in the diff tree.
 *
 * Renders the JSON-pointer path, a kind marker (+/-/Δ/·), and the
 * appropriate before/after / value snippet. The row's tint is
 * determined by the node kind; the snippet uses ``<pre>`` so JSON
 * indentation lines up across rows.
 */
function DiffRow({ node }: DiffRowProps) {
  const cls =
    "rounded-md border px-3 py-2 text-xs font-mono text-surface-800 " + rowClass(node.kind);
  const headerPath = node.path === "" ? "(root)" : node.path;

  return (
    <div className={cls} data-testid={`strategy-diff-row-${node.path}`}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">
          <span aria-hidden="true">{kindMarker(node.kind)}</span> {headerPath}
        </span>
        <span className="text-2xs uppercase tracking-wider text-surface-500">{node.kind}</span>
      </div>
      {node.kind === "changed" ? (
        <div className="mt-1 grid grid-cols-1 gap-1 md:grid-cols-2">
          <pre className="overflow-x-auto rounded bg-red-100 p-2 text-red-900">
            {formatValue(node.before)}
          </pre>
          <pre className="overflow-x-auto rounded bg-green-100 p-2 text-green-900">
            {formatValue(node.after)}
          </pre>
        </div>
      ) : (
        <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words">
          {formatValue(node.kind === "unchanged" ? node.value : node.value)}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

/**
 * Translate any error thrown by the orchestrator into a user-facing
 * string that surfaces both strategy IDs (so the operator can tell
 * which side failed). For typed :class:`GetStrategyError` we forward
 * the offending message verbatim — it already carries the offending
 * ID built by the API wrapper.
 */
function getDiffErrorMessage(err: unknown, idA: string, idB: string): string {
  if (err instanceof GetStrategyError) {
    return `${err.message} (comparing ${idA} vs ${idB}).`;
  }
  if (err instanceof Error) {
    return `Failed to compare strategies ${idA} and ${idB}: ${err.message}`;
  }
  return `Failed to compare strategies ${idA} and ${idB}.`;
}

// ---------------------------------------------------------------------------
// URL-param parsing
// ---------------------------------------------------------------------------

/**
 * Parse and validate the ``a`` / ``b`` query params.
 *
 * Returns:
 *   ``{ ok: true, a, b }`` when both params validate; otherwise
 *   ``{ ok: false, rawA, rawB }`` with whatever the URL carried so the
 *   error state can echo it back to the operator.
 */
function readUlidParams(
  search: URLSearchParams,
): { ok: true; a: string; b: string } | { ok: false; rawA: string | null; rawB: string | null } {
  const rawA = search.get("a");
  const rawB = search.get("b");
  if (isUlidLike(rawA) && isUlidLike(rawB)) {
    return { ok: true, a: rawA, b: rawB };
  }
  return { ok: false, rawA, rawB };
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function StrategyDiff() {
  const [searchParams, setSearchParams] = useSearchParams();
  // useAuth assertion: the AuthGuard wrapper has already verified the
  // session; calling useAuth here keeps the hook semantics consistent
  // with sibling pages.
  useAuth();

  const parsed = readUlidParams(searchParams);
  const idA = parsed.ok ? parsed.a : null;
  const idB = parsed.ok ? parsed.b : null;

  const [data, setData] = useState<StrategyDiffData | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(parsed.ok);
  const [error, setError] = useState<string | null>(null);

  // "Hide unchanged" toggle — default OFF so the operator's first view
  // shows the entire IR (with diff tinting) rather than an aggressively
  // pruned view that hides context.
  const [hideUnchanged, setHideUnchanged] = useState(false);

  // Fetch both strategies in parallel whenever the validated URL
  // params change. Cancellation is handled by a stale-flag rather than
  // an AbortSignal because the underlying getStrategy() wrapper does
  // not currently accept a signal — using a flag keeps the contract
  // unchanged.
  useEffect(() => {
    if (!idA || !idB) {
      setData(null);
      setIsLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    setError(null);
    setData(null);

    void (async () => {
      try {
        const result = await fetchStrategyDiff(idA, idB);
        if (cancelled) return;
        setData(result);
      } catch (err) {
        if (cancelled) return;
        setError(getDiffErrorMessage(err, idA, idB));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [idA, idB]);

  /** Swap A↔B by rewriting the URL params; the effect re-fetches. */
  const handleSwitch = useCallback(() => {
    if (!idA || !idB) return;
    setSearchParams({ a: idB, b: idA });
  }, [idA, idB, setSearchParams]);

  // Compute the diff once per loaded payload. Deferred until both
  // sides have a parsed_ir; for draft-form strategies (parsed_ir ===
  // null) we render the "incompatible source" notice instead.
  const diffNodes: DiffNode[] = useMemo(() => {
    if (!data) return [];
    const a = data.strategyA.parsed_ir;
    const b = data.strategyB.parsed_ir;
    if (a == null || b == null) return [];
    return diffIr(a, b);
  }, [data]);

  const visibleNodes = useMemo(() => {
    if (!hideUnchanged) return diffNodes;
    return diffNodes.filter((n) => n.kind !== "unchanged");
  }, [diffNodes, hideUnchanged]);

  // -------------------------------------------------------------------------
  // Empty / error state when the URL params aren't both valid ULIDs.
  // -------------------------------------------------------------------------
  if (!parsed.ok) {
    return (
      <div className="space-y-6 p-6" data-testid="strategy-diff-page">
        <header>
          <h1 className="text-2xl font-bold text-surface-900">Compare Strategies</h1>
          <p className="mt-1 text-sm text-surface-500">
            Side-by-side structural diff of two saved strategy IRs.
          </p>
        </header>
        <div
          className="rounded-lg border border-amber-200 bg-amber-50 p-4"
          role="alert"
          data-testid="strategy-diff-missing-args"
        >
          <p className="text-sm text-amber-900">
            Pick two strategies to compare. The URL must include both <code>?a=</code> and{" "}
            <code>&amp;b=</code> with valid strategy ULIDs.
          </p>
          <p className="mt-2 text-xs text-amber-800">
            <span className="font-medium">a:</span> <code>{parsed.rawA ?? "<missing>"}</code>{" "}
            <span className="ml-3 font-medium">b:</span> <code>{parsed.rawB ?? "<missing>"}</code>
          </p>
          <div className="mt-3">
            <Link
              to="/strategies"
              className="inline-flex items-center rounded-md border border-amber-300 bg-white px-3 py-1.5 text-sm font-medium text-amber-900 hover:bg-amber-100"
              data-testid="strategy-diff-pick-strategies"
            >
              Pick two strategies →
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Happy path — both IDs validated; render header + body.
  // -------------------------------------------------------------------------
  const hasIrA = data?.strategyA.parsed_ir != null;
  const hasIrB = data?.strategyB.parsed_ir != null;
  const canDiff = hasIrA && hasIrB;

  return (
    <div className="space-y-6 p-6" data-testid="strategy-diff-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Compare Strategies</h1>
          <p className="mt-1 text-sm text-surface-500">
            Strategy A: <span className="font-mono">{idA}</span> · Strategy B:{" "}
            <span className="font-mono">{idB}</span>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleSwitch}
            className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50"
            data-testid="strategy-diff-switch"
          >
            Switch A↔B
          </button>
          <Link
            to="/strategies"
            className="rounded-md border border-surface-300 bg-white px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50"
            data-testid="strategy-diff-pick-different"
          >
            Pick different strategies
          </Link>
        </div>
      </header>

      {isLoading ? (
        <div
          className="grid grid-cols-1 gap-4 md:grid-cols-2"
          data-testid="strategy-diff-loading"
          aria-busy="true"
        >
          <PanelSkeleton side="A" />
          <PanelSkeleton side="B" />
        </div>
      ) : null}

      {error && !isLoading ? (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4"
          role="alert"
          data-testid="strategy-diff-error"
        >
          <p className="text-sm text-red-700">{error}</p>
        </div>
      ) : null}

      {!isLoading && !error && data ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2" data-testid="strategy-diff-panels">
            <StrategyHeaderPanel side="A" strategy={data.strategyA} />
            <StrategyHeaderPanel side="B" strategy={data.strategyB} />
          </div>

          {canDiff ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <DiffSummary nodes={diffNodes} />
                <label className="inline-flex items-center gap-2 text-sm text-surface-700">
                  <input
                    type="checkbox"
                    data-testid="strategy-diff-hide-unchanged-toggle"
                    checked={hideUnchanged}
                    onChange={(e) => setHideUnchanged(e.target.checked)}
                    className="h-4 w-4 rounded border-surface-300 text-brand-600 focus:ring-brand-500"
                  />
                  Hide unchanged
                </label>
              </div>

              <section
                aria-label="Structural IR diff"
                className="space-y-2"
                data-testid="strategy-diff-tree"
              >
                {visibleNodes.length === 0 ? (
                  <div
                    className="rounded-md border border-surface-200 bg-surface-50 p-4 text-sm text-surface-600"
                    data-testid="strategy-diff-tree-empty"
                  >
                    {hideUnchanged
                      ? "No structural differences (try toggling 'Hide unchanged' off)."
                      : "Both IRs are empty."}
                  </div>
                ) : (
                  visibleNodes.map((node) => (
                    // The path is unique within the diff result (each
                    // walk emits at most one node per JSON pointer), so
                    // it is a stable React key.
                    <DiffRow key={node.path || "(root)"} node={node} />
                  ))
                )}
              </section>
            </>
          ) : (
            <div
              className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
              role="alert"
              data-testid="strategy-diff-no-ir"
            >
              At least one of the selected strategies has no parsed IR (draft-form rows do not
              support structural diff). Pick two ``Imported IR`` strategies to see a diff.
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

/**
 * Loading skeleton for one header panel; shown twice while the parallel
 * fetch is in flight. Matches the visual rhythm of the populated header
 * card so the layout does not jump when data arrives.
 */
function PanelSkeleton({ side }: { side: "A" | "B" }) {
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-surface-200 bg-white p-4"
      data-testid={`strategy-diff-skeleton-${side.toLowerCase()}`}
    >
      <div className="h-3 w-16 animate-pulse rounded bg-surface-200" />
      <div className="h-5 w-3/4 animate-pulse rounded bg-surface-200" />
      <div className="h-3 w-1/2 animate-pulse rounded bg-surface-200" />
      <div className="h-3 w-1/3 animate-pulse rounded bg-surface-200" />
    </div>
  );
}

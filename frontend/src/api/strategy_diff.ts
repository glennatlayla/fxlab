/**
 * API orchestrator for the side-by-side strategy IR diff view.
 *
 * Purpose:
 *   Fetch two strategies (including their parsed IRs) in parallel so
 *   the ``/strategies/diff?a={idA}&b={idB}`` page can render both panels
 *   in a single round-trip's worth of latency.
 *
 * Responsibilities:
 *   - Compose ``getStrategy(id)`` for both ``strategyIdA`` and
 *     ``strategyIdB`` via ``Promise.all`` so the slowest fetch bounds
 *     the total wait.
 *   - Surface a typed :class:`StrategyDiffData` result containing both
 *     strategies' detail records (which already include ``parsed_ir``
 *     when ``source === "ir_upload"``).
 *
 * Does NOT:
 *   - Render UI or own React state — pure orchestration.
 *   - Add new HTTP endpoints — we reuse ``GET /strategies/{id}`` from
 *     :mod:`services.api.routes.strategies`. The route already returns
 *     the parsed IR via ``services.api.services.strategy_service.
 *     get_with_parsed_ir``, so the comparison page does not need to
 *     fetch raw IR text and parse client-side.
 *   - Compute the structural diff — that lives in ``lib/ir_diff.ts``
 *     so the diff is unit-testable in isolation from the network.
 *
 * Dependencies:
 *   - getStrategy from @/api/strategies (existing M2.D2 wrapper — owns
 *     error classification via :class:`GetStrategyError`).
 *
 * Error conditions:
 *   - Any error from the underlying ``getStrategy`` call surfaces
 *     unchanged so the caller can branch on
 *     :class:`GetStrategyError` (404 strategy missing, 422 stored IR
 *     fails re-validation) and surface the offending strategy id in
 *     the banner.
 *
 * Example:
 *   const data = await fetchStrategyDiff(
 *     "01HSTRATAAAAAAAAAAAAAAAAAA",
 *     "01HSTRATBBBBBBBBBBBBBBBBBB",
 *   );
 *   // data.strategyA.parsed_ir → StrategyIR | null
 *   // data.strategyB.name      → display name for the panel header
 */

import { getStrategy, type StrategyDetail } from "@/api/strategies";

/**
 * Top-level payload returned by :func:`fetchStrategyDiff`.
 *
 * ``strategyA`` corresponds to the ``a`` URL search param; ``strategyB``
 * to ``b``. Each side carries the full :class:`StrategyDetail` record
 * so the panel header (name, version, source, archived state) and the
 * IR tree (``parsed_ir``) can render without an additional fetch.
 *
 * Attributes:
 *   strategyA: Detail record for the ``a`` strategy, including parsed_ir
 *     when ``source === "ir_upload"`` (null for draft-form strategies).
 *   strategyB: Detail record for the ``b`` strategy.
 */
export interface StrategyDiffData {
  strategyA: StrategyDetail;
  strategyB: StrategyDetail;
}

/**
 * Fetch the full diff payload for two strategies in parallel.
 *
 * Both underlying HTTP calls fire concurrently via a single
 * ``Promise.all`` so total latency is the slowest of the two, not the
 * sum. The caller is responsible for computing the diff from the
 * returned ``parsed_ir`` fields via :func:`diffIr` from ``lib/ir_diff``.
 *
 * Args:
 *   strategyIdA: ULID of the "A" side (mapped from the ``?a=`` URL param).
 *   strategyIdB: ULID of the "B" side (mapped from the ``?b=`` URL param).
 *
 * Returns:
 *   A :class:`StrategyDiffData` with both sides populated.
 *
 * Raises:
 *   Any error from the underlying API layer is re-thrown unchanged so
 *   the caller can branch on it. ``Promise.all`` rejects on the first
 *   rejection. The two ``getStrategy`` calls have no shared state, so
 *   leaking the in-flight one is harmless beyond the wasted bandwidth.
 *
 * Example:
 *   try {
 *     const data = await fetchStrategyDiff(idA, idB);
 *     setData(data);
 *   } catch (err) {
 *     if (err instanceof GetStrategyError) setError(err.detail ?? err.message);
 *   }
 */
export async function fetchStrategyDiff(
  strategyIdA: string,
  strategyIdB: string,
): Promise<StrategyDiffData> {
  const [strategyA, strategyB] = await Promise.all([
    getStrategy(strategyIdA),
    getStrategy(strategyIdB),
  ]);
  return { strategyA, strategyB };
}

/**
 * Deterministic structural diff for parsed Strategy IR documents.
 *
 * Purpose:
 *   Power the side-by-side IR comparison page (/strategies/diff?a=...&b=...)
 *   by walking two parsed IR trees in lockstep and emitting a flat list of
 *   :class:`DiffNode` records that the UI can render with green / red /
 *   yellow tinting (added / removed / changed) plus an "unchanged" base.
 *
 * Responsibilities:
 *   - Walk both trees in lexicographic key order so the output is fully
 *     deterministic across runs and across operating systems (avoids
 *     reliance on insertion order, which V8 preserves for non-numeric
 *     keys but Pydantic / JSON.stringify round-trips do not always
 *     guarantee identical orderings).
 *   - Align arrays by index — no smart heuristic. This keeps the diff
 *     predictable: an inserted element at index 0 will surface as
 *     "everything shifted by one" and is therefore deliberately noisy,
 *     which is the right outcome for a literal structural diff.
 *   - Emit JSON-pointer-style paths (RFC 6901) so paths are unambiguous
 *     even when keys contain "/" or "~".
 *   - Treat type-flips (object → array, primitive → object, null →
 *     anything non-null, etc.) as a single "changed" node at the parent
 *     path; do not recurse into the after-tree under a type-mismatched
 *     subtree, which would generate false-positive added nodes.
 *
 * Does NOT:
 *   - Perform any I/O or network access. Pure function — fully testable.
 *   - Validate that the inputs are valid IR documents. The page upstream
 *     fetches the parsed_ir from the backend; this helper accepts any
 *     JSON-shaped value so unit tests can drive it with primitives.
 *   - Render the diff. UI lives in `pages/StrategyDiff.tsx`.
 *
 * Dependencies:
 *   - None.
 *
 * Path conventions:
 *   - Root: ``""`` (empty string).
 *   - Object key: ``"/key"`` (slash-prefixed). RFC 6901 escapes apply:
 *     ``"/"`` inside a key is encoded as ``"~1"`` and ``"~"`` as ``"~0"``
 *     so the resulting path round-trips unambiguously.
 *   - Array index: ``"/0"`` (decimal index, no padding).
 *
 * Example:
 *   const nodes = diffIr(
 *     { metadata: { strategy_name: "alpha", version: "1.0.0" } },
 *     { metadata: { strategy_name: "alpha", version: "1.1.0" } },
 *   );
 *   // → [
 *   //     { kind: "unchanged", path: "/metadata/strategy_name", value: "alpha" },
 *   //     { kind: "changed",   path: "/metadata/version", before: "1.0.0", after: "1.1.0" },
 *   //   ]
 */

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/**
 * One entry in the structural diff result.
 *
 * Discriminated by ``kind``:
 *   - "unchanged" — both trees carry the same primitive at this leaf
 *     path. Containers (objects / arrays) themselves are NOT emitted as
 *     "unchanged" nodes; only leaves are. This keeps the result lean.
 *   - "added"     — the path exists only in the B-side tree.
 *   - "removed"   — the path exists only in the A-side tree.
 *   - "changed"   — both sides have a value at this path but they differ.
 *     For primitives this means a value flip. For container-vs-anything
 *     type mismatches (object → array, null → object, etc.) the entire
 *     subtree is collapsed into a single "changed" node with the full
 *     before/after values; the helper does NOT recurse past a type flip.
 */
export type DiffNode =
  | { kind: "unchanged"; path: string; value: unknown }
  | { kind: "added"; path: string; value: unknown }
  | { kind: "removed"; path: string; value: unknown }
  | { kind: "changed"; path: string; before: unknown; after: unknown };

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Tag used internally to classify a value's shape for the diff walker.
 *
 * "object" covers any non-null, non-array object (the shape Pydantic's
 * ``.model_dump()`` produces for nested models). "array" covers the
 * subset where ``Array.isArray(value) === true``. "primitive" covers
 * everything else: numbers, strings, booleans, null, undefined.
 */
type ShapeTag = "object" | "array" | "primitive";

/**
 * Classify a value into a :data:`ShapeTag`.
 *
 * Args:
 *   value: Any JSON-shaped value.
 *
 * Returns:
 *   ``"array"`` / ``"object"`` / ``"primitive"`` — the discriminator
 *   :func:`diff` uses to decide whether to recurse or emit a leaf.
 */
function shapeOf(value: unknown): ShapeTag {
  if (Array.isArray(value)) return "array";
  if (value !== null && typeof value === "object") return "object";
  return "primitive";
}

/**
 * Escape a single object key per RFC 6901 (JSON Pointer).
 *
 * The escapes are deliberately ordered: ``~`` MUST be replaced first
 * (with ``~0``) so a subsequent ``/`` → ``~1`` substitution does not
 * double-encode tildes that the second pass introduces.
 *
 * Args:
 *   key: Raw object key.
 *
 * Returns:
 *   The escaped key safe for use in a slash-delimited JSON pointer
 *   path component.
 */
function escapePointerToken(key: string): string {
  return key.replace(/~/g, "~0").replace(/\//g, "~1");
}

/**
 * Append one path component to an existing JSON-pointer path.
 *
 * The root path is the empty string; every appended component is
 * prefixed with ``"/"`` so the result is always either ``""`` (root) or
 * starts with a slash.
 *
 * Args:
 *   parent: Parent path. Use ``""`` for the root.
 *   component: Already-escaped path component (object key or array
 *     index as a string).
 *
 * Returns:
 *   The composed JSON-pointer path.
 */
function appendPath(parent: string, component: string): string {
  return `${parent}/${component}`;
}

/**
 * Compute structural equality for two values.
 *
 * Used by the leaf-comparison branch. Recursively checks deep equality
 * for objects and arrays; primitives use ``Object.is`` so ``NaN`` is
 * equal to itself (matches "stable structural equality" expectations
 * for IR comparisons that may carry NaN sentinels via JSON parse).
 *
 * Args:
 *   a: Left-hand value.
 *   b: Right-hand value.
 *
 * Returns:
 *   ``true`` iff the two values are structurally equivalent.
 */
function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  const sa = shapeOf(a);
  const sb = shapeOf(b);
  if (sa !== sb) return false;
  if (sa === "primitive") return Object.is(a, b);
  if (sa === "array") {
    const aa = a as unknown[];
    const bb = b as unknown[];
    if (aa.length !== bb.length) return false;
    for (let i = 0; i < aa.length; i++) {
      if (!deepEqual(aa[i], bb[i])) return false;
    }
    return true;
  }
  // Both are objects.
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  const ak = Object.keys(ao).sort();
  const bk = Object.keys(bo).sort();
  if (ak.length !== bk.length) return false;
  for (let i = 0; i < ak.length; i++) {
    if (ak[i] !== bk[i]) return false;
  }
  for (const k of ak) {
    if (!deepEqual(ao[k], bo[k])) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Recursive walker
// ---------------------------------------------------------------------------

/**
 * Walk the two trees in lockstep at a given path, appending diff nodes.
 *
 * This is the workhorse — public :func:`diffIr` is a thin wrapper that
 * starts the recursion at the root path.
 *
 * Args:
 *   a: Left subtree.
 *   b: Right subtree.
 *   path: Current JSON-pointer path being walked.
 *   out: Accumulator the recursion appends nodes to (mutated in place
 *     to keep allocation overhead minimal on large IRs).
 */
function walk(a: unknown, b: unknown, path: string, out: DiffNode[]): void {
  const sa = shapeOf(a);
  const sb = shapeOf(b);

  // Type flip → emit one "changed" for the whole subtree and stop.
  if (sa !== sb) {
    out.push({ kind: "changed", path, before: a, after: b });
    return;
  }

  // Both primitives — leaf-level equality decides the verdict.
  if (sa === "primitive") {
    if (deepEqual(a, b)) {
      out.push({ kind: "unchanged", path, value: a });
    } else {
      out.push({ kind: "changed", path, before: a, after: b });
    }
    return;
  }

  // Both arrays — align by index. Items unique to the longer side become
  // "added" or "removed" trailing entries; shared indices recurse.
  if (sa === "array") {
    const aa = a as unknown[];
    const bb = b as unknown[];
    const max = Math.max(aa.length, bb.length);
    for (let i = 0; i < max; i++) {
      const childPath = appendPath(path, String(i));
      if (i >= aa.length) {
        out.push({ kind: "added", path: childPath, value: bb[i] });
      } else if (i >= bb.length) {
        out.push({ kind: "removed", path: childPath, value: aa[i] });
      } else {
        walk(aa[i], bb[i], childPath, out);
      }
    }
    return;
  }

  // Both objects — walk the union of keys in lexicographic order.
  const ao = a as Record<string, unknown>;
  const bo = b as Record<string, unknown>;
  const keys = new Set<string>([...Object.keys(ao), ...Object.keys(bo)]);
  const sortedKeys = [...keys].sort();
  for (const key of sortedKeys) {
    const childPath = appendPath(path, escapePointerToken(key));
    const aHas = Object.prototype.hasOwnProperty.call(ao, key);
    const bHas = Object.prototype.hasOwnProperty.call(bo, key);
    if (!aHas && bHas) {
      out.push({ kind: "added", path: childPath, value: bo[key] });
    } else if (aHas && !bHas) {
      out.push({ kind: "removed", path: childPath, value: ao[key] });
    } else {
      walk(ao[key], bo[key], childPath, out);
    }
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Compute a deterministic structural diff between two IR-shaped values.
 *
 * Walks both trees in lexicographic key order (objects) and by index
 * (arrays), emitting one :class:`DiffNode` per leaf comparison or per
 * subtree-level type flip. Containers themselves are never emitted as
 * "unchanged" nodes — only leaves and added/removed subtrees show up
 * — which keeps the result lean enough to render in a sidebar even on
 * IRs with hundreds of indicators.
 *
 * Args:
 *   a: The "before" / left-hand value (typically the parsed IR for
 *     strategy A from the URL ``?a=`` parameter).
 *   b: The "after" / right-hand value (parsed IR for strategy B).
 *
 * Returns:
 *   A flat array of :class:`DiffNode` records. The order matches the
 *   walk: depth-first, lexicographic for objects, index-order for
 *   arrays. Callers can render the array in order, group by ``kind``
 *   for a summary block, or filter by path prefix to scope the view.
 *
 * Example:
 *   const nodes = diffIr(strategyA.parsed_ir, strategyB.parsed_ir);
 *   const summary = nodes.reduce(
 *     (acc, n) => ({ ...acc, [n.kind]: (acc[n.kind] ?? 0) + 1 }),
 *     {} as Record<DiffNode["kind"], number>,
 *   );
 */
export function diffIr(a: unknown, b: unknown): DiffNode[] {
  const out: DiffNode[] = [];
  walk(a, b, "", out);
  return out;
}

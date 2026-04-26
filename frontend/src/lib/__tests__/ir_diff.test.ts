/**
 * Tests for the deterministic IR diff helper (lib/ir_diff.ts).
 *
 * Verifies the structural diff used by the /strategies/diff page:
 *   - Identical IRs produce only "unchanged" nodes.
 *   - Adding a key in B yields an "added" node at that path.
 *   - Removing a key (in A only) yields a "removed" node.
 *   - A primitive flip yields a single "changed" node carrying before/after.
 *   - Nested object changes yield only the leaf "changed"; ancestors stay
 *     out of the result for that subtree's container (the container is
 *     itself "unchanged" as a node only when both sides are equal as a
 *     whole; otherwise we recurse — see the assertion below).
 *   - Array length changes surface trailing entries as added / removed.
 *   - Edge cases: null vs object, empty arrays, mixed type flips
 *     (object → array, primitive → object, etc.).
 *
 * Path conventions (JSON pointer-style):
 *   - Root: "" (empty string).
 *   - Object key:  "/key".
 *   - Array index: "/0".
 *   - Nested:      "/indicators/0/length".
 *   - Slashes inside keys are escaped per RFC 6901 ("/" → "~1", "~" → "~0").
 *
 * Example:
 *   npx vitest run src/lib/__tests__/ir_diff.test.ts
 */

import { describe, it, expect } from "vitest";
import { diffIr, type DiffNode } from "@/lib/ir_diff";

/**
 * Locate the first diff node at the given path. Returns `undefined` when
 * no node matches; the assertion in the calling test handles the failure.
 */
function nodeAt(nodes: DiffNode[], path: string): DiffNode | undefined {
  return nodes.find((n) => n.path === path);
}

describe("diffIr — deterministic structural diff", () => {
  it("returns all 'unchanged' nodes for two structurally-identical IRs", () => {
    const a = {
      metadata: { strategy_name: "RSI Reversal", strategy_version: "1.0.0" },
      indicators: [
        { id: "rsi_14", type: "rsi", length: 14 },
        { id: "ema_20", type: "ema", length: 20 },
      ],
      direction: "long",
    };
    // Deep copy so the helper sees distinct references but equal values.
    const b = JSON.parse(JSON.stringify(a));

    const nodes = diffIr(a, b);

    // No "added", "removed", or "changed" entries appear in the result.
    for (const n of nodes) {
      expect(n.kind).toBe("unchanged");
    }
    // Every primitive leaf shows up as an "unchanged" node, so the
    // result is non-empty for a non-trivial input.
    expect(nodes.length).toBeGreaterThan(0);
  });

  it("emits an 'added' node when B has a key A does not", () => {
    const a = { name: "alpha" };
    const b = { name: "alpha", description: "new key" };

    const nodes = diffIr(a, b);

    const added = nodeAt(nodes, "/description");
    expect(added).toBeDefined();
    expect(added?.kind).toBe("added");
    if (added && added.kind === "added") {
      expect(added.value).toBe("new key");
    }
    // The shared "name" key is unchanged.
    const name = nodeAt(nodes, "/name");
    expect(name?.kind).toBe("unchanged");
  });

  it("emits a 'removed' node when A has a key B does not", () => {
    const a = { name: "alpha", deprecated_field: "gone" };
    const b = { name: "alpha" };

    const nodes = diffIr(a, b);

    const removed = nodeAt(nodes, "/deprecated_field");
    expect(removed).toBeDefined();
    expect(removed?.kind).toBe("removed");
    if (removed && removed.kind === "removed") {
      expect(removed.value).toBe("gone");
    }
  });

  it("emits a single 'changed' node when a primitive value flips", () => {
    const a = { length: 14 };
    const b = { length: 21 };

    const nodes = diffIr(a, b);

    const changed = nodeAt(nodes, "/length");
    expect(changed).toBeDefined();
    expect(changed?.kind).toBe("changed");
    if (changed && changed.kind === "changed") {
      expect(changed.before).toBe(14);
      expect(changed.after).toBe(21);
    }
  });

  it("recurses into nested objects: only the leaf is 'changed', not ancestors", () => {
    const a = { metadata: { strategy_name: "alpha", version: "1.0.0" } };
    const b = { metadata: { strategy_name: "alpha", version: "1.1.0" } };

    const nodes = diffIr(a, b);

    // The version leaf flipped.
    const version = nodeAt(nodes, "/metadata/version");
    expect(version?.kind).toBe("changed");

    // The strategy_name leaf is unchanged.
    const name = nodeAt(nodes, "/metadata/strategy_name");
    expect(name?.kind).toBe("unchanged");

    // The /metadata container itself does NOT appear as a "changed"
    // node — the helper recurses into objects rather than emitting a
    // synthetic container-level diff. (It also does not emit an
    // "unchanged" node for the container; only leaves and added/removed
    // subtrees show up.)
    const container = nodes.find((n) => n.path === "/metadata");
    expect(container).toBeUndefined();
  });

  it("aligns arrays by index; trailing tail items are 'added' or 'removed'", () => {
    const a = { tags: ["alpha", "bravo"] };
    const b = { tags: ["alpha", "bravo", "charlie", "delta"] };

    const nodes = diffIr(a, b);

    // Shared head is unchanged.
    expect(nodeAt(nodes, "/tags/0")?.kind).toBe("unchanged");
    expect(nodeAt(nodes, "/tags/1")?.kind).toBe("unchanged");

    // Tail items added.
    const added2 = nodeAt(nodes, "/tags/2");
    const added3 = nodeAt(nodes, "/tags/3");
    expect(added2?.kind).toBe("added");
    expect(added3?.kind).toBe("added");
    if (added2 && added2.kind === "added") expect(added2.value).toBe("charlie");
    if (added3 && added3.kind === "added") expect(added3.value).toBe("delta");
  });

  it("treats array shrinkage as 'removed' for missing trailing indices", () => {
    const a = { items: [1, 2, 3, 4] };
    const b = { items: [1, 2] };

    const nodes = diffIr(a, b);

    expect(nodeAt(nodes, "/items/0")?.kind).toBe("unchanged");
    expect(nodeAt(nodes, "/items/1")?.kind).toBe("unchanged");
    const r2 = nodeAt(nodes, "/items/2");
    const r3 = nodeAt(nodes, "/items/3");
    expect(r2?.kind).toBe("removed");
    expect(r3?.kind).toBe("removed");
    if (r2 && r2.kind === "removed") expect(r2.value).toBe(3);
    if (r3 && r3.kind === "removed") expect(r3.value).toBe(4);
  });

  it("treats null vs object as a type-flip 'changed' node (no recursion)", () => {
    const a = { extras: null };
    const b = { extras: { description: "hello" } };

    const nodes = diffIr(a, b);

    const changed = nodeAt(nodes, "/extras");
    expect(changed).toBeDefined();
    expect(changed?.kind).toBe("changed");
    if (changed && changed.kind === "changed") {
      expect(changed.before).toBeNull();
      expect(changed.after).toEqual({ description: "hello" });
    }
    // Because the type flipped, the helper does not emit nested nodes
    // under /extras — the whole subtree is reported as one change.
    expect(nodes.find((n) => n.path === "/extras/description")).toBeUndefined();
  });

  it("treats object → array (or array → object) as a single 'changed' node", () => {
    const a = { payload: { key: "value" } };
    const b = { payload: ["value"] };

    const nodes = diffIr(a, b);

    const changed = nodeAt(nodes, "/payload");
    expect(changed?.kind).toBe("changed");
    // No spurious recursion under /payload after a kind mismatch.
    expect(nodes.some((n) => n.path.startsWith("/payload/"))).toBe(false);
  });

  it("walks object keys in lexicographic order so the output is deterministic", () => {
    const a = { zebra: 1, alpha: 2, mango: 3 };
    const b = { zebra: 1, alpha: 2, mango: 3 };

    const nodes = diffIr(a, b);

    // Filter to top-level keys only and check the ordering.
    const topLevelPaths = nodes.map((n) => n.path).filter((p) => p.split("/").length === 2);
    expect(topLevelPaths).toEqual(["/alpha", "/mango", "/zebra"]);
  });

  it("handles two empty objects without producing any nodes", () => {
    const nodes = diffIr({}, {});
    expect(nodes).toEqual([]);
  });

  it("handles two equal primitives at the root as one 'unchanged' node", () => {
    const nodes = diffIr(42, 42);
    expect(nodes).toEqual([{ kind: "unchanged", path: "", value: 42 }]);
  });

  it("handles two different primitives at the root as one 'changed' node", () => {
    const nodes = diffIr("alpha", "bravo");
    expect(nodes).toEqual([{ kind: "changed", path: "", before: "alpha", after: "bravo" }]);
  });

  it("escapes RFC 6901 special characters in object keys ('/' → '~1', '~' → '~0')", () => {
    const a = { "weird/key": 1, "ti~lde": 2 };
    const b = { "weird/key": 1, "ti~lde": 3 };

    const nodes = diffIr(a, b);

    // The "/" inside the key MUST be escaped or downstream consumers
    // would mis-parse the path as nested keys.
    expect(nodeAt(nodes, "/weird~1key")?.kind).toBe("unchanged");
    expect(nodeAt(nodes, "/ti~0lde")?.kind).toBe("changed");
  });
});

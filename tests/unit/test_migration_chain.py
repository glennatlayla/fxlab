"""
Unit tests for Alembic migration chain integrity.

Purpose:
    Verify that the migration revision chain is linear with no duplicate
    revisions or broken down_revision references. This prevents deployment
    failures caused by Alembic encountering branched or conflicting histories.

Responsibilities:
    - Parse all migration files and extract revision/down_revision.
    - Verify no duplicate revision IDs exist.
    - Verify the chain is linear (each down_revision is either None or a
      revision that exists in the set).
    - Verify revision filenames match their internal revision IDs.

Does NOT:
    - Run actual migrations (that is integration/CI's job).
    - Validate migration SQL correctness.

Dependencies:
    - pathlib: For migration file discovery.
    - ast: For parsing Python source to extract revision values.
    - re: For regex-based extraction fallback.

Example:
    pytest tests/unit/test_migration_chain.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _parse_revision_identifiers(filepath: Path) -> dict[str, str | None]:
    """
    Extract revision and down_revision from a migration file.

    Args:
        filepath: Path to the migration .py file.

    Returns:
        Dict with keys 'revision' and 'down_revision'.
    """
    content = filepath.read_text()

    # Match both annotated (revision: str = "...") and plain (revision = "...") formats.
    # Alembic auto-generates the annotated form; hand-written migrations may omit types.
    rev_match = re.search(
        r'^revision(?::\s*str)?\s*=\s*"([^"]+)"',
        content,
        re.MULTILINE,
    )

    # down_revision can be:
    #   - Annotated:  down_revision: Union[str, None] = "..." | None
    #   - Plain:      down_revision = "..." | None
    down_match = re.search(
        r'^down_revision(?::\s*Union\[str,\s*(?:None|Sequence\[str\])\])?\s*=\s*("([^"]+)"|None)',
        content,
        re.MULTILINE,
    )

    if not rev_match:
        raise ValueError(f"Could not find revision in {filepath.name}")

    revision = rev_match.group(1)
    down_revision: str | None = None
    if down_match and down_match.group(2):
        down_revision = down_match.group(2)

    return {"revision": revision, "down_revision": down_revision}


def _get_all_migrations() -> list[dict[str, str | None]]:
    """
    Discover and parse all migration files in the versions directory.

    Returns:
        List of dicts with 'revision', 'down_revision', and 'filename' keys.
    """
    results = []
    for filepath in sorted(MIGRATIONS_DIR.glob("*.py")):
        if filepath.name == "__pycache__":
            continue
        info = _parse_revision_identifiers(filepath)
        info["filename"] = filepath.name
        results.append(info)
    return results


class TestMigrationChainIntegrity:
    """Verify the Alembic migration chain is valid and linear."""

    def test_migrations_directory_exists(self) -> None:
        """The migrations/versions directory must exist."""
        assert MIGRATIONS_DIR.is_dir(), f"Migrations directory not found: {MIGRATIONS_DIR}"

    def test_at_least_one_migration_exists(self) -> None:
        """There must be at least one migration file."""
        migrations = _get_all_migrations()
        assert len(migrations) > 0, "No migration files found"

    def test_no_duplicate_revision_ids(self) -> None:
        """Every migration file must have a unique revision ID."""
        migrations = _get_all_migrations()
        revisions = [m["revision"] for m in migrations]
        duplicates = [r for r in revisions if revisions.count(r) > 1]
        assert len(duplicates) == 0, (
            f"Duplicate revision IDs found: {set(duplicates)}. "
            "Each migration must have a unique revision. "
            "Files: {[m['filename'] for m in migrations if m['revision'] in duplicates]}"
        )

    def test_chain_is_linear(self) -> None:
        """Each down_revision must reference an existing revision or be None (root)."""
        migrations = _get_all_migrations()
        revision_set = {m["revision"] for m in migrations}
        roots = [m for m in migrations if m["down_revision"] is None]

        # Exactly one root migration
        assert len(roots) == 1, (
            f"Expected exactly 1 root migration (down_revision=None), "
            f"found {len(roots)}: {[r['filename'] for r in roots]}"
        )

        # Every non-root down_revision must point to an existing revision
        for m in migrations:
            if m["down_revision"] is not None:
                assert m["down_revision"] in revision_set, (
                    f"Migration {m['filename']} (rev={m['revision']}) has "
                    f"down_revision={m['down_revision']} which does not exist "
                    f"in the revision set: {sorted(revision_set)}"
                )

    def test_no_branching(self) -> None:
        """No two migrations should share the same down_revision (no branches)."""
        migrations = _get_all_migrations()
        down_revisions = [m["down_revision"] for m in migrations if m["down_revision"] is not None]
        duplicates = [d for d in down_revisions if down_revisions.count(d) > 1]
        assert len(duplicates) == 0, (
            f"Branching detected: multiple migrations share down_revision "
            f"{set(duplicates)}. Alembic requires a linear chain for "
            f"non-branching migrations."
        )

    def test_revision_in_filename(self) -> None:
        """Each migration filename should contain its revision ID."""
        migrations = _get_all_migrations()
        for m in migrations:
            assert m["revision"] in m["filename"], (
                f"Migration file {m['filename']} does not contain its "
                f"revision ID '{m['revision']}' in the filename"
            )

    def test_chain_reaches_all_revisions(self) -> None:
        """Walking from the head to the root must visit every revision."""
        migrations = _get_all_migrations()
        rev_to_down = {m["revision"]: m["down_revision"] for m in migrations}
        all_revisions = set(rev_to_down.keys())

        # Find the head (a revision that no other revision points to as down_revision)
        referenced = {m["down_revision"] for m in migrations if m["down_revision"]}
        heads = all_revisions - referenced
        assert len(heads) == 1, f"Expected exactly 1 head revision, found {len(heads)}: {heads}"

        # Walk from head to root
        visited = set()
        current = heads.pop()
        while current is not None:
            assert current not in visited, f"Cycle detected at revision {current}"
            visited.add(current)
            current = rev_to_down.get(current)

        assert visited == all_revisions, (
            f"Chain does not cover all revisions. "
            f"Visited: {sorted(visited)}, All: {sorted(all_revisions)}, "
            f"Missing: {sorted(all_revisions - visited)}"
        )

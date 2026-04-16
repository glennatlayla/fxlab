"""Allow ``python -m services.api.cli`` to list available CLI tools."""

from __future__ import annotations

import sys


def main() -> None:
    """Print available CLI subcommands and exit."""
    print("FXLab CLI tools:")
    print("  python -m services.api.cli.seed_admin   — Seed initial admin user")
    sys.exit(0)


if __name__ == "__main__":
    main()

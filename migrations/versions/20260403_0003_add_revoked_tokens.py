"""Add revoked_tokens table for JWT token revocation.

Stores revoked JWT tokens by their JTI (JWT ID) claim.
Supports token revocation (emergency logout, security incidents) and
cleanup of expired entries (automatic expiry).

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-03 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create revoked_tokens table."""
    op.create_table(
        "revoked_tokens",
        sa.Column("jti", sa.String(36), primary_key=True, nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    """Drop revoked_tokens table."""
    op.drop_table("revoked_tokens")

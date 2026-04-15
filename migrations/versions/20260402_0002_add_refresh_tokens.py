"""Add refresh_tokens table for OIDC token endpoint.

Stores server-side refresh token hashes for the OIDC-compatible
token endpoint (M14-T8). Supports single-token and per-user
revocation.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create refresh_tokens table."""
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(26), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.String(26),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "token_hash", sa.String(64), nullable=False, unique=True, index=True
        ),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    """Drop refresh_tokens table."""
    op.drop_table("refresh_tokens")

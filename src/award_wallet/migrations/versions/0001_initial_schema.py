"""Initial schema: users, loyalty accounts, balance snapshots, expiration lots

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "loyalty_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("credentials_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("session_state_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("sync_status", sa.String(20), nullable=False),
        sa.Column("sync_message", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_loyalty_accounts_user_id", "loyalty_accounts", ["user_id"])
    op.create_table(
        "balance_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("loyalty_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_balance_snapshots_account_captured", "balance_snapshots", ["account_id", "captured_at"])
    op.create_table(
        "expiration_lots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("balance_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_expiration_lots_snapshot_id", "expiration_lots", ["snapshot_id"])


def downgrade() -> None:
    op.drop_table("expiration_lots")
    op.drop_table("balance_snapshots")
    op.drop_table("loyalty_accounts")
    op.drop_table("users")

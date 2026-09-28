"""Add person accounts and separate organization profiles."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_accounts_and_organizations"
down_revision: Union[str, None] = "0002_workspace_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('participant', 'organizer')", name="ck_accounts_valid_role"),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=True)
    op.create_table(
        "organization_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("website", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=2000), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", name="uq_organization_profiles_owner_id"),
    )


def downgrade() -> None:
    op.drop_table("organization_profiles")
    op.drop_index("ix_accounts_email", table_name="accounts")
    op.drop_table("accounts")

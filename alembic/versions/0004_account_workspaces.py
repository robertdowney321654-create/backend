"""Associate workspace snapshots with account owners."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_account_workspaces"
down_revision: Union[str, None] = "0003_accounts_and_organizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workspace_snapshots") as batch_op:
        batch_op.drop_constraint("ck_workspace_snapshot_singleton_id", type_="check")
        batch_op.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_workspace_snapshots_owner_id_accounts",
            "accounts",
            ["owner_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint("uq_workspace_snapshots_owner_id", ["owner_id"])
        batch_op.create_check_constraint("ck_workspace_snapshot_positive_id", "id > 0")


def downgrade() -> None:
    op.drop_table("workspace_snapshots")
    op.create_table(
        "workspace_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_workspace_snapshot_singleton_id"),
        sa.PrimaryKeyConstraint("id"),
    )

"""Create the persisted workspace snapshot table."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_workspace_snapshot"
down_revision: Union[str, None] = "0001_infrastructure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_workspace_snapshot_singleton_id"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("workspace_snapshots")
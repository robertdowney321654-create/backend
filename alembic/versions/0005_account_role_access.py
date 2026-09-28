"""Allow one person account to access both participant and organizer spaces."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_account_role_access"
down_revision: Union[str, None] = "0004_account_workspaces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("roles", sa.JSON(), nullable=True))
    accounts = sa.table(
        "accounts",
        sa.column("id", sa.Integer()),
        sa.column("role", sa.String(length=24)),
        sa.column("roles", sa.JSON()),
    )
    connection = op.get_bind()
    for account_id, role in connection.execute(sa.select(accounts.c.id, accounts.c.role)):
        connection.execute(accounts.update().where(accounts.c.id == account_id).values(roles=[role]))
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.alter_column("roles", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("accounts", "roles")

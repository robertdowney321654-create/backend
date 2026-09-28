"""Add invite links, voting windows, comments, audit records, and webhooks."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_public_lifecycle_features"
down_revision: Union[str, None] = "0007_normalized_event_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hackathon_events", sa.Column("voting_deadline", sa.String(80), nullable=False, server_default=""))
    op.add_column("teams", sa.Column("invite_code", sa.String(64), nullable=True))
    op.execute("UPDATE teams SET invite_code = 'legacy-team-' || id WHERE invite_code IS NULL")
    with op.batch_alter_table("teams") as batch_op:
        batch_op.alter_column("invite_code", existing_type=sa.String(64), nullable=False)
        batch_op.create_unique_constraint("uq_team_invite_code", ["invite_code"])
    op.create_index("ix_teams_invite_code", "teams", ["invite_code"])

    op.create_table(
        "project_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_external_id", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_project_comments_event_id", "project_comments", ["event_id"])
    op.create_index("ix_project_comments_submission_external_id", "project_comments", ["submission_external_id"])
    op.create_index("ix_project_comments_author_id", "project_comments", ["author_id"])

    op.create_table(
        "event_audit_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_audit_entries_event_id", "event_audit_entries", ["event_id"])
    op.create_index("ix_event_audit_entries_actor_id", "event_audit_entries", ["actor_id"])

    op.create_table(
        "event_webhooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_url", sa.String(2000), nullable=False),
        sa.Column("signing_secret", sa.String(128), nullable=False),
        sa.Column("event_types", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_event_webhooks_event_id", "event_webhooks", ["event_id"])
    op.create_index("ix_event_webhooks_owner_id", "event_webhooks", ["owner_id"])


def downgrade() -> None:
    op.drop_table("event_webhooks")
    op.drop_table("event_audit_entries")
    op.drop_table("project_comments")
    op.drop_index("ix_teams_invite_code", table_name="teams")
    with op.batch_alter_table("teams") as batch_op:
        batch_op.drop_constraint("uq_team_invite_code", type_="unique")
        batch_op.drop_column("invite_code")
    op.drop_column("hackathon_events", "voting_deadline")
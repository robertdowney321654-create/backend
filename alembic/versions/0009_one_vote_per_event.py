"""Enforce one community vote per account and event."""

from typing import Sequence, Union

from alembic import op

revision: str = "0009_one_vote_per_event"
down_revision: Union[str, None] = "0008_public_lifecycle_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM community_votes
        WHERE id NOT IN (
            SELECT MIN(id) FROM community_votes GROUP BY event_id, voter_id
        )
    """)
    op.create_index("ux_event_voter_ballot", "community_votes", ["event_id", "voter_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_event_voter_ballot", table_name="community_votes")
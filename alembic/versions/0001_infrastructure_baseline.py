"""Infrastructure baseline with no domain tables."""

from typing import Sequence, Union

revision: str = "0001_infrastructure"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No infrastructure objects are required at this stage."""


def downgrade() -> None:
    """The baseline migration has no objects to remove."""

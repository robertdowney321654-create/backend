"""Database snapshot for the single active hackathon workspace."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WorkspaceSnapshot(Base):
    """Persist the current workspace payload as one replaceable snapshot."""

    __tablename__ = "workspace_snapshots"
    __table_args__ = (CheckConstraint("id > 0", name="ck_workspace_snapshot_positive_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
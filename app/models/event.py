"""Normalized hackathon events and their operational records."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class HackathonEvent(Base):
    __tablename__ = "hackathon_events"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    host: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(160), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    dates: Mapped[str] = mapped_column(String(160), nullable=False)
    deadline: Mapped[str] = mapped_column(String(80), nullable=False)
    registration_deadline: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    submission_deadline: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    voting_deadline: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    prize: Mapped[str] = mapped_column(String(160), nullable=False)
    participants: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spots: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tracks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    eligibility: Mapped[str] = mapped_column(Text, default="", nullable=False)
    color: Mapped[str] = mapped_column(String(32), default="mint", nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    schedule: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    results_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    judging_normalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (UniqueConstraint("event_id", "email", name="uq_event_registration_email"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    track: Mapped[str] = mapped_column(String(160), nullable=False)
    team_preference: Mapped[str] = mapped_column(String(80), nullable=False)
    team_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ProjectSubmissionRecord(Base):
    __tablename__ = "project_submissions"
    __table_args__ = (UniqueConstraint("event_id", "external_id", name="uq_event_submission_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    submitter_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    submitter_email: Mapped[str] = mapped_column(String(320), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    team: Mapped[str] = mapped_column(String(160), nullable=False)
    track: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    repository_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    demo_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="Submitted", nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    legacy_votes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RubricCriterionRecord(Base):
    __tablename__ = "event_rubric_criteria"
    __table_args__ = (UniqueConstraint("event_id", "criterion_id", name="uq_event_rubric_criterion"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False, index=True)
    criterion_id: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)


class JudgeScoreRecord(Base):
    __tablename__ = "judge_score_records"
    __table_args__ = (UniqueConstraint("event_id", "submission_external_id", "judge_account_id", name="uq_event_submission_judge_score"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False, index=True)
    submission_external_id: Mapped[int] = mapped_column(Integer, nullable=False)
    judge_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    criterion_scores: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
"""Normalize events, registrations, submissions, rubrics, and judge scores."""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_normalized_event_records"
down_revision: Union[str, None] = "0006_lifecycle_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _value(record: dict[str, object], camel: str, snake: str, default: object = "") -> object:
    return record.get(camel, record.get(snake, default))


def upgrade() -> None:
    op.create_table(
        "hackathon_events",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("host", sa.String(240), nullable=False),
        sa.Column("category", sa.String(160), nullable=False),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("dates", sa.String(160), nullable=False),
        sa.Column("deadline", sa.String(80), nullable=False),
        sa.Column("registration_deadline", sa.String(80), nullable=False, server_default=""),
        sa.Column("submission_deadline", sa.String(80), nullable=False, server_default=""),
        sa.Column("location", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("prize", sa.String(160), nullable=False),
        sa.Column("participants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tracks", sa.JSON(), nullable=False),
        sa.Column("eligibility", sa.Text(), nullable=False, server_default=""),
        sa.Column("color", sa.String(32), nullable=False, server_default="mint"),
        sa.Column("symbol", sa.String(32), nullable=False, server_default=""),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("results_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("judging_normalized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_hackathon_events_owner_id", "hackathon_events", ["owner_id"])
    op.create_table(
        "event_registrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("track", sa.String(160), nullable=False),
        sa.Column("team_preference", sa.String(80), nullable=False),
        sa.Column("team_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "email", name="uq_event_registration_email"),
    )
    op.create_index("ix_event_registrations_event_id", "event_registrations", ["event_id"])
    op.create_index("ix_event_registrations_account_id", "event_registrations", ["account_id"])
    op.create_table(
        "project_submissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.Integer(), nullable=False),
        sa.Column("submitter_account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitter_email", sa.String(320), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("team", sa.String(160), nullable=False),
        sa.Column("track", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("repository_url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("demo_url", sa.String(1000), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="Submitted"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("legacy_votes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "external_id", name="uq_event_submission_external_id"),
    )
    op.create_index("ix_project_submissions_event_id", "project_submissions", ["event_id"])
    op.create_index("ix_project_submissions_submitter_account_id", "project_submissions", ["submitter_account_id"])
    op.create_table(
        "event_rubric_criteria",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("criterion_id", sa.String(120), nullable=False),
        sa.Column("label", sa.String(240), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.UniqueConstraint("event_id", "criterion_id", name="uq_event_rubric_criterion"),
    )
    op.create_index("ix_event_rubric_criteria_event_id", "event_rubric_criteria", ["event_id"])
    op.create_table(
        "judge_score_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(120), sa.ForeignKey("hackathon_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("submission_external_id", sa.Integer(), nullable=False),
        sa.Column("judge_account_id", sa.Integer(), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("criterion_scores", sa.JSON(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", "submission_external_id", "judge_account_id", name="uq_event_submission_judge_score"),
    )
    op.create_index("ix_judge_score_records_event_id", "judge_score_records", ["event_id"])
    op.create_index("ix_judge_score_records_judge_account_id", "judge_score_records", ["judge_account_id"])

    bind = op.get_bind()
    snapshots = list(bind.execute(sa.text("SELECT owner_id, payload FROM workspace_snapshots WHERE owner_id IS NOT NULL")))
    workspaces: list[tuple[int, dict[str, object]]] = []
    for owner_id, payload in snapshots:
        if isinstance(payload, str):
            payload = json.loads(payload)
        workspaces.append((owner_id, payload or {}))

    event_owners: dict[str, int] = {}
    for owner_id, workspace in workspaces:
        published = set(workspace.get("publishedEventIds", workspace.get("published_event_ids", [])) or [])
        normalized = bool(workspace.get("judgingNormalized", workspace.get("judging_normalized", False)))
        for event in workspace.get("events", []) or []:
            event_id = str(event["id"])
            existing_owner = event_owners.get(event_id)
            if existing_owner is not None:
                if existing_owner != owner_id:
                    raise RuntimeError(f"Event id {event_id!r} is owned by multiple accounts; resolve the duplicate before migration.")
                continue
            event_owners[event_id] = owner_id
            bind.execute(sa.text("""
                INSERT INTO hackathon_events (
                    id, owner_id, title, host, category, format, dates, deadline,
                    registration_deadline, submission_deadline, location, description,
                    prize, participants, spots, tracks, eligibility, color, symbol, schedule,
                    is_archived, results_published, judging_normalized
                ) VALUES (
                    :id, :owner_id, :title, :host, :category, :format, :dates, :deadline,
                    :registration_deadline, :submission_deadline, :location, :description,
                    :prize, :participants, :spots, :tracks, :eligibility, :color, :symbol, :schedule,
                    :is_archived, :results_published, :judging_normalized
                )
            """), {
                "id": event_id, "owner_id": owner_id, "title": event.get("title", ""),
                "host": event.get("host", ""), "category": event.get("category", ""),
                "format": event.get("format", "Online"), "dates": event.get("dates", ""),
                "deadline": event.get("deadline", ""),
                "registration_deadline": _value(event, "registrationDeadline", "registration_deadline"),
                "submission_deadline": _value(event, "submissionDeadline", "submission_deadline"),
                "location": event.get("location", ""), "description": event.get("description", ""),
                "prize": event.get("prize", ""), "participants": event.get("participants", 0),
                "spots": event.get("spots", 0), "tracks": json.dumps(event.get("tracks", [])),
                "eligibility": event.get("eligibility", ""), "color": event.get("color", "mint"),
                "symbol": event.get("symbol", ""), "schedule": json.dumps(event.get("schedule", [])),
                "is_archived": _value(event, "isArchived", "is_archived", False),
                "results_published": event_id in published, "judging_normalized": normalized,
            })

    registrations_seen: set[tuple[str, str]] = set()
    for owner_id, workspace in workspaces:
        for registration in workspace.get("registrations", []) or []:
            event_id = str(_value(registration, "eventId", "event_id"))
            if event_owners.get(event_id) is None:
                continue
            email = str(registration.get("email", "")).casefold()
            key = (event_id, email)
            if key in registrations_seen:
                continue
            registrations_seen.add(key)
            account_id = bind.execute(sa.text("SELECT id FROM accounts WHERE lower(email) = :email"), {"email": email}).scalar()
            bind.execute(sa.text("""
                INSERT INTO event_registrations (event_id, account_id, name, email, track, team_preference, team_name)
                VALUES (:event_id, :account_id, :name, :email, :track, :team_preference, :team_name)
            """), {
                "event_id": event_id, "account_id": account_id, "name": registration.get("name", ""),
                "email": email, "track": registration.get("track", ""),
                "team_preference": _value(registration, "teamPreference", "team_preference", "Going solo"),
                "team_name": _value(registration, "teamName", "team_name"),
            })

    submission_seen: set[tuple[str, int]] = set()
    ordered_workspaces = sorted(workspaces, key=lambda item: item[0] not in set(event_owners.values()))
    for owner_id, workspace in ordered_workspaces:
        for submission in workspace.get("projectSubmissions", workspace.get("project_submissions", [])) or []:
            event_id = str(_value(submission, "eventId", "event_id"))
            if event_id not in event_owners:
                continue
            external_id = int(submission.get("id", 0))
            key = (event_id, external_id)
            if key in submission_seen:
                continue
            submission_seen.add(key)
            email = str(_value(submission, "submitterEmail", "submitter_email")).casefold()
            account_id = bind.execute(sa.text("SELECT id FROM accounts WHERE lower(email) = :email"), {"email": email}).scalar() if email else None
            bind.execute(sa.text("""
                INSERT INTO project_submissions (
                    event_id, external_id, submitter_account_id, submitter_email, title, team,
                    track, description, repository_url, demo_url, status, score, legacy_votes
                ) VALUES (
                    :event_id, :external_id, :submitter_account_id, :submitter_email, :title, :team,
                    :track, :description, :repository_url, :demo_url, :status, :score, :legacy_votes
                )
            """), {
                "event_id": event_id, "external_id": external_id, "submitter_account_id": account_id,
                "submitter_email": email, "title": submission.get("title", ""),
                "team": submission.get("team", ""), "track": submission.get("track", ""),
                "description": submission.get("description", ""),
                "repository_url": _value(submission, "repositoryUrl", "repository_url"),
                "demo_url": _value(submission, "demoUrl", "demo_url"),
                "status": submission.get("status", "Submitted"), "score": submission.get("score", 0),
                "legacy_votes": submission.get("votes", 0),
            })

    for owner_id, workspace in workspaces:
        criteria = workspace.get("judgingRubric", workspace.get("judging_rubric", [])) or []
        for event_id, event_owner in event_owners.items():
            if owner_id != event_owner:
                continue
            for criterion in criteria:
                bind.execute(sa.text("""
                    INSERT INTO event_rubric_criteria (event_id, criterion_id, label, weight)
                    VALUES (:event_id, :criterion_id, :label, :weight)
                """), {
                    "event_id": event_id,
                    "criterion_id": _value(criterion, "id", "criterion_id"),
                    "label": criterion.get("label", ""), "weight": criterion.get("weight", 0),
                })
        for score in workspace.get("judgeScores", workspace.get("judge_scores", [])) or []:
            event_id = str(_value(score, "eventId", "event_id"))
            if event_owners.get(event_id) != owner_id:
                continue
            judge_email = str(_value(score, "judgeEmail", "judge_email")).casefold()
            judge_id = bind.execute(sa.text("SELECT id FROM accounts WHERE lower(email) = :email"), {"email": judge_email}).scalar()
            if judge_id is None:
                continue
            bind.execute(sa.text("""
                INSERT INTO judge_score_records (event_id, submission_external_id, judge_account_id, criterion_scores, comment)
                VALUES (:event_id, :submission_id, :judge_id, :criterion_scores, :comment)
            """), {
                "event_id": event_id, "submission_id": _value(score, "submissionId", "submission_id"),
                "judge_id": judge_id,
                "criterion_scores": json.dumps(_value(score, "criterionScores", "criterion_scores", {})),
                "comment": score.get("comment", ""),
            })


def downgrade() -> None:
    op.drop_table("judge_score_records")
    op.drop_table("event_rubric_criteria")
    op.drop_table("project_submissions")
    op.drop_table("event_registrations")
    op.drop_table("hackathon_events")
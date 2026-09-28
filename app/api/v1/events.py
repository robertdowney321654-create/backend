"""Public event listings shared across organizer accounts."""

import csv
import io
import random
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from typing import Literal
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import Field
from secrets import token_urlsafe

from app.api.v1.auth import get_current_account
from app.core.database import get_db
from app.models.account import Account
from app.models.event import EventRegistration, HackathonEvent, ProjectSubmissionRecord
from app.models.lifecycle import CommunityVote, EventAuditEntry, EventWebhook, ProjectComment
from app.models.workspace import WorkspaceSnapshot
from app.schemas.workspace import ApiModel, EventData, ProjectSubmissionData, WorkspaceData
from app.services.workspace_store import _is_closed
from app.services.webhooks import dispatch_webhooks
from app.schemas.lifecycle import EventWebhookCreate, EventWebhookCreated, EventWebhookView

router = APIRouter(prefix="/events", tags=["events"])


class FixtureSubmissionCreate(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(default="", max_length=4000)
    status: Literal["Draft", "Submitted"] = "Submitted"


class ProjectSubmissionEdit(ApiModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4000)
    repository_url: str = Field(default="", max_length=1000)
    demo_url: str = Field(default="", max_length=1000)
    track: str = Field(default="", max_length=160)
    status: Literal["Draft", "Submitted"] | None = None


class ProjectCommentCreate(ApiModel):
    body: str = Field(min_length=1, max_length=2000)


class ProjectCommentView(ApiModel):
    id: int
    author: str
    body: str
    created_at: datetime


class BulkSubmissionItem(ApiModel):
    id: int | None = None
    title: str = Field(min_length=1, max_length=240)
    team: str = Field(min_length=1, max_length=160)
    track: str = Field(min_length=1, max_length=160)
    submitter_email: str = Field(default="", max_length=320)
    summary: str = Field(default="", max_length=4000)
    repo_url: str = Field(default="", max_length=1000)


class BulkSubmissionImport(ApiModel):
    submissions: list[BulkSubmissionItem] = Field(min_length=1, max_length=500)


@router.get("/admin/events", response_model=list[EventData])
async def list_all_events_for_admin(
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> list[EventData]:
    if getattr(account, "active_role", account.role) != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    events = (await session.scalars(select(HackathonEvent).order_by(HackathonEvent.created_at.desc()))).all()
    return [EventData(
        id=event.id, title=event.title, host=event.host, category=event.category, format=event.format,
        dates=event.dates, deadline=event.deadline, registrationDeadline=event.registration_deadline,
        submissionDeadline=event.submission_deadline, votingDeadline=event.voting_deadline,
        location=event.location, description=event.description, prize=event.prize,
        participants=event.participants, spots=event.spots, tracks=event.tracks,
        eligibility=event.eligibility, color=event.color, symbol=event.symbol,
        schedule=event.schedule, isArchived=event.is_archived,
    ) for event in events]


@router.get("", response_model=list[EventData])
async def list_public_events(session: AsyncSession = Depends(get_db)) -> list[EventData]:
    """List non-archived events from the event table."""
    events = (await session.scalars(select(HackathonEvent).where(HackathonEvent.is_archived.is_(False)))).all()
    return [EventData(
        id=event.id, title=event.title, host=event.host, category=event.category, format=event.format,
        dates=event.dates, deadline=event.deadline, registrationDeadline=event.registration_deadline,
        submissionDeadline=event.submission_deadline, votingDeadline=event.voting_deadline,
        location=event.location, description=event.description,
        prize=event.prize, participants=event.participants, spots=event.spots, tracks=event.tracks,
        eligibility=event.eligibility, color=event.color, symbol=event.symbol, schedule=event.schedule,
        isArchived=event.is_archived,
    ) for event in events]


@router.get("/{event_id}/webhooks", response_model=list[EventWebhookView])
async def list_event_webhooks(
    event_id: str,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> list[EventWebhookView]:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required.")
    owner_id = getattr(account, "active_workspace_owner_id", account.id)
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Event was not found in this organization.")
    hooks = (await session.scalars(select(EventWebhook).where(EventWebhook.event_id == event_id))).all()
    return [EventWebhookView(id=hook.id, event_id=hook.event_id, target_url=hook.target_url, event_types=hook.event_types, enabled=hook.enabled) for hook in hooks]


@router.post("/{event_id}/webhooks", response_model=EventWebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_event_webhook(
    event_id: str,
    payload: EventWebhookCreate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> EventWebhookCreated:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required.")
    owner_id = getattr(account, "active_workspace_owner_id", account.id)
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Event was not found in this organization.")
    supported = {"project.submitted", "project.updated", "project.commented", "vote.cast", "results.published"}
    if set(payload.event_types) - supported:
        raise HTTPException(status_code=422, detail="One or more webhook event types are unsupported.")
    if payload.target_url.scheme != "https":
        raise HTTPException(status_code=422, detail="Webhook URLs must use HTTPS.")
    secret = token_urlsafe(32)
    hook = EventWebhook(
        event_id=event_id, owner_id=owner_id, target_url=str(payload.target_url),
        signing_secret=secret, event_types=payload.event_types,
    )
    session.add(hook)
    await session.commit()
    await session.refresh(hook)
    return EventWebhookCreated(
        id=hook.id, event_id=hook.event_id, target_url=hook.target_url,
        event_types=hook.event_types, enabled=hook.enabled, signing_secret=secret,
    )


@router.delete("/{event_id}/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_webhook(
    event_id: str,
    webhook_id: int,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> Response:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required.")
    owner_id = getattr(account, "active_workspace_owner_id", account.id)
    hook = await session.scalar(select(EventWebhook).where(
        EventWebhook.id == webhook_id, EventWebhook.event_id == event_id, EventWebhook.owner_id == owner_id,
    ))
    if hook is None:
        raise HTTPException(status_code=404, detail="Webhook was not found.")
    await session.delete(hook)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{event_id}/submissions/import", response_model=list[ProjectSubmissionData], status_code=status.HTTP_201_CREATED)
async def bulk_import_submissions(
    event_id: str,
    payload: BulkSubmissionImport,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> list[ProjectSubmissionData]:
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required to import submissions.")
    owner_id = getattr(account, "active_workspace_owner_id", account.id)
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Event was not found in this organization.")
    rows = []
    next_id = (await session.scalar(select(func.max(ProjectSubmissionRecord.external_id).where(ProjectSubmissionRecord.event_id == event_id))) or 0) + 1
    existing_ids = set((await session.scalars(select(ProjectSubmissionRecord.external_id).where(ProjectSubmissionRecord.event_id == event_id))).all())
    for item in payload.submissions:
        external_id = item.id if item.id is not None else next_id
        next_id = max(next_id, external_id + 1)
        if external_id in existing_ids:
            raise HTTPException(status_code=409, detail=f"Submission id {external_id} already exists.")
        submission = ProjectSubmissionRecord(
            event_id=event_id, external_id=external_id, submitter_email=item.submitter_email.casefold(),
            submitter_account_id=None, title=item.title.strip(), team=item.team.strip(), track=item.track.strip(),
            description=item.summary.strip(), repository_url=item.repo_url.strip(), status="Submitted",
        )
        session.add(submission)
        rows.append(submission)
        existing_ids.add(external_id)
    await session.commit()
    return [ProjectSubmissionData(
        id=row.external_id, eventId=row.event_id, title=row.title, team=row.team, track=row.track,
        submitterEmail=row.submitter_email, description=row.description, repositoryUrl=row.repository_url,
        demoUrl=row.demo_url, status=row.status, score=row.score, votes=row.legacy_votes,
    ) for row in rows]


@router.get("/{event_id}/submissions", response_model=list[ProjectSubmissionData])
async def list_public_submissions(event_id: str, session: AsyncSession = Depends(get_db)) -> list[ProjectSubmissionData]:
    """List submissions without exposing unreleased judge scores."""
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.is_archived:
        raise HTTPException(status_code=404, detail="Event was not found.")
    submissions = (await session.scalars(select(ProjectSubmissionRecord).where(
        ProjectSubmissionRecord.event_id == event_id,
        ProjectSubmissionRecord.status != "Draft",
    ))).all()
    result = []
    for item in submissions:
        votes = await session.scalar(select(func.count(CommunityVote.id)).where(
            CommunityVote.event_id == event_id,
            CommunityVote.submission_id == item.external_id,
        )) or 0
        result.append(ProjectSubmissionData(
            id=item.external_id, eventId=item.event_id, title=item.title, team=item.team,
            track=item.track, submitterEmail=item.submitter_email, description=item.description,
            repositoryUrl=item.repository_url, demoUrl=item.demo_url, status=item.status,
            score=item.score if event.results_published else 0, votes=item.legacy_votes + votes,
        ))
    random.SystemRandom().shuffle(result)
    return result


@router.get("/{event_id}/submissions/{submission_id}/comments", response_model=list[ProjectCommentView])
async def list_project_comments(
    event_id: str,
    submission_id: int,
    session: AsyncSession = Depends(get_db),
) -> list[ProjectCommentView]:
    submission = await session.scalar(select(ProjectSubmissionRecord).where(
        ProjectSubmissionRecord.event_id == event_id,
        ProjectSubmissionRecord.external_id == submission_id,
        ProjectSubmissionRecord.status != "Draft",
    ))
    if submission is None:
        raise HTTPException(status_code=404, detail="Project submission was not found.")
    comments = (await session.scalars(select(ProjectComment).where(
        ProjectComment.event_id == event_id,
        ProjectComment.submission_external_id == submission_id,
    ).order_by(ProjectComment.created_at))).all()
    result = []
    for comment in comments:
        author = await session.get(Account, comment.author_id)
        result.append(ProjectCommentView(
            id=comment.id, author=author.full_name if author else "Community member",
            body=comment.body, created_at=comment.created_at,
        ))
    return result


@router.post("/{event_id}/submissions/{submission_id}/comments", response_model=ProjectCommentView, status_code=status.HTTP_201_CREATED)
async def add_project_comment(
    event_id: str,
    submission_id: int,
    payload: ProjectCommentCreate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> ProjectCommentView:
    if getattr(account, "active_role", account.role) != "participant":
        raise HTTPException(status_code=403, detail="Participant access is required to comment.")
    submission = await session.scalar(select(ProjectSubmissionRecord).where(
        ProjectSubmissionRecord.event_id == event_id,
        ProjectSubmissionRecord.external_id == submission_id,
        ProjectSubmissionRecord.status != "Draft",
    ))
    if submission is None:
        raise HTTPException(status_code=404, detail="Project submission was not found.")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    recent_count = await session.scalar(select(func.count(ProjectComment.id)).where(
        ProjectComment.author_id == account.id,
        ProjectComment.created_at >= cutoff,
    )) or 0
    if recent_count >= 10:
        raise HTTPException(status_code=429, detail="Comment rate limit reached. Try again later.")
    comment = ProjectComment(event_id=event_id, submission_external_id=submission_id, author_id=account.id, body=payload.body.strip())
    session.add(comment)
    session.add(EventAuditEntry(event_id=event_id, actor_id=account.id, action="project.comment", target_id=str(submission_id), detail={}))
    await session.commit()
    await session.refresh(comment)
    return ProjectCommentView(id=comment.id, author=account.full_name, body=comment.body, created_at=comment.created_at)


@router.post("/{event_id}/submissions", response_model=ProjectSubmissionData, status_code=status.HTTP_201_CREATED)
async def create_public_submission(
    event_id: str,
    payload: FixtureSubmissionCreate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> ProjectSubmissionData:
    """Accept a participant project only while the event submission window is open."""
    if getattr(account, "active_role", account.role) != "participant":
        raise HTTPException(status_code=403, detail="Participant access is required to submit a project.")
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.is_archived:
        raise HTTPException(status_code=404, detail="Event was not found.")
    if _is_closed(event.submission_deadline):
        raise HTTPException(status_code=409, detail="Project submissions are closed for this event.")
    registration = await session.scalar(select(EventRegistration).where(
        EventRegistration.event_id == event_id,
        func.lower(EventRegistration.email) == account.email.casefold(),
    ))
    if registration is None:
        raise HTTPException(status_code=403, detail="Register for this event before submitting a project.")
    next_id = (await session.scalar(select(func.max(ProjectSubmissionRecord.external_id)).where(
        ProjectSubmissionRecord.event_id == event_id,
    )) or 0) + 1
    submission = ProjectSubmissionRecord(
        event_id=event_id, external_id=next_id, submitter_account_id=account.id,
        submitter_email=account.email.casefold(), title=payload.title.strip(), team=registration.team_name,
        track=registration.track, description=payload.summary.strip(), status=payload.status, score=0, legacy_votes=0,
    )
    session.add(submission)
    await session.commit()
    return ProjectSubmissionData(
        id=submission.external_id, eventId=submission.event_id, title=submission.title,
        team=submission.team, track=submission.track, submitterEmail=submission.submitter_email,
        description=submission.description, repositoryUrl="", demoUrl="", status=submission.status,
        score=0, votes=0,
    )


@router.put("/{event_id}/submissions/{submission_id}", response_model=ProjectSubmissionData)
async def edit_project_submission(
    event_id: str,
    submission_id: int,
    payload: ProjectSubmissionEdit,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> ProjectSubmissionData:
    """Allow a project owner to edit their submission before the deadline."""
    if getattr(account, "active_role", account.role) != "participant":
        raise HTTPException(status_code=403, detail="Participant access is required to edit a project.")
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.is_archived:
        raise HTTPException(status_code=404, detail="Event was not found.")
    if _is_closed(event.submission_deadline):
        raise HTTPException(status_code=409, detail="Project submissions are closed for this event.")
    submission = await session.scalar(select(ProjectSubmissionRecord).where(
        ProjectSubmissionRecord.event_id == event_id,
        ProjectSubmissionRecord.external_id == submission_id,
    ))
    if submission is None:
        raise HTTPException(status_code=404, detail="Project submission was not found.")
    if submission.submitter_account_id != account.id and submission.submitter_email.casefold() != account.email.casefold():
        raise HTTPException(status_code=403, detail="You can only edit your own project.")
    submission.title = payload.title.strip()
    submission.description = payload.description.strip()
    submission.repository_url = payload.repository_url.strip()
    submission.demo_url = payload.demo_url.strip()
    if payload.track.strip():
        submission.track = payload.track.strip()
    if payload.status is not None:
        submission.status = payload.status

    snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == event.owner_id))
    if snapshot is not None:
        workspace = WorkspaceData.model_validate(snapshot.payload)
        workspace.project_submissions = [item.model_copy(update={
            "title": submission.title,
            "description": submission.description,
            "repository_url": submission.repository_url,
            "demo_url": submission.demo_url,
            "track": submission.track,
        }) if item.event_id == event_id and item.id == submission_id else item for item in workspace.project_submissions]
        snapshot.payload = workspace.model_dump(mode="json", by_alias=True)

    await session.commit()
    return ProjectSubmissionData(
        id=submission.external_id, eventId=submission.event_id, title=submission.title,
        team=submission.team, track=submission.track, submitterEmail=submission.submitter_email,
        description=submission.description, repositoryUrl=submission.repository_url,
        demoUrl=submission.demo_url, status=submission.status,
        score=submission.score if event.results_published else 0, votes=submission.legacy_votes,
    )


@router.get("/{event_id}/export.csv")
async def export_event_csv(
    event_id: str,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Export event submissions and current results for the owning organizer."""
    if getattr(account, "active_role", account.role) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required to export event results.")
    owner_id = getattr(account, "active_workspace_owner_id", account.id)
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="Event was not found in this organization.")
    submissions = (await session.scalars(select(ProjectSubmissionRecord).where(
        ProjectSubmissionRecord.event_id == event_id,
    ).order_by(ProjectSubmissionRecord.external_id))).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["project_id", "title", "team", "track", "status", "score", "votes"])
    for submission in submissions:
        votes = await session.scalar(select(func.count(CommunityVote.id)).where(
            CommunityVote.event_id == event_id,
            CommunityVote.submission_id == submission.external_id,
        )) or 0
        writer.writerow([
            submission.external_id, submission.title, submission.team, submission.track,
            submission.status, submission.score if event.results_published else "", submission.legacy_votes + votes,
        ])
    return Response(
        content=output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{event_id}-results.csv"'},
    )
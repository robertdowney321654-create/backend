"""Compatibility adapter between the workspace API and normalized records."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.event import EventRegistration, HackathonEvent, JudgeScoreRecord, ProjectSubmissionRecord, RubricCriterionRecord
from app.models.lifecycle import CommunityVote
from app.models.workspace import WorkspaceSnapshot
from app.schemas.workspace import EventData, JudgeScoreData, ProjectSubmissionData, RegistrationData, RubricCriterionData, WorkspaceData


def _is_closed(value: str) -> bool:
    try:
        cutoff = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= cutoff.astimezone(timezone.utc)


def _event_data(event: HackathonEvent) -> EventData:
    return EventData(
        id=event.id, title=event.title, host=event.host, category=event.category, format=event.format,
        dates=event.dates, deadline=event.deadline, registrationDeadline=event.registration_deadline,
        submissionDeadline=event.submission_deadline, votingDeadline=event.voting_deadline, location=event.location, description=event.description,
        prize=event.prize, participants=event.participants, spots=event.spots, tracks=event.tracks,
        eligibility=event.eligibility, color=event.color, symbol=event.symbol, schedule=event.schedule,
        isArchived=event.is_archived,
    )


async def load_workspace(session: AsyncSession, account: Account, owner_id: int | None = None) -> WorkspaceData:
    workspace_owner_id = owner_id or getattr(account, "active_workspace_owner_id", account.id)
    role = getattr(account, "active_role", account.role)
    snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == workspace_owner_id))
    auxiliary = WorkspaceData.model_validate(snapshot.payload) if snapshot else WorkspaceData()
    if role == "organizer":
        events = list((await session.scalars(select(HackathonEvent).where(HackathonEvent.owner_id == workspace_owner_id).order_by(HackathonEvent.created_at))).all())
        event_ids = [event.id for event in events]
        registrations = list((await session.scalars(select(EventRegistration).where(EventRegistration.event_id.in_(event_ids)))).all()) if event_ids else []
        submissions = list((await session.scalars(select(ProjectSubmissionRecord).where(ProjectSubmissionRecord.event_id.in_(event_ids)))).all()) if event_ids else []
        score_rows = list((await session.scalars(select(JudgeScoreRecord).where(JudgeScoreRecord.event_id.in_(event_ids)))).all()) if event_ids else []
        rubric_rows = list((await session.scalars(select(RubricCriterionRecord).where(RubricCriterionRecord.event_id == event_ids[0]).order_by(RubricCriterionRecord.id))).all()) if event_ids else []
        published_ids = [event.id for event in events if event.results_published]
        if snapshot is None and not events:
            raise HTTPException(status_code=404, detail="Workspace has not been initialized.")
    else:
        registrations = list((await session.scalars(select(EventRegistration).where(or_(EventRegistration.account_id == account.id, func.lower(EventRegistration.email) == account.email.casefold())))).all())
        event_ids = list(dict.fromkeys(registration.event_id for registration in registrations))
        events = list((await session.scalars(select(HackathonEvent).where(HackathonEvent.id.in_(event_ids)))).all()) if event_ids else []
        submissions = list((await session.scalars(select(ProjectSubmissionRecord).where(or_(ProjectSubmissionRecord.submitter_account_id == account.id, func.lower(ProjectSubmissionRecord.submitter_email) == account.email.casefold())))).all())
        visible_submission_ids = {item.external_id for item in submissions}
        score_rows = list((await session.scalars(select(JudgeScoreRecord).where(JudgeScoreRecord.event_id.in_(event_ids)))).all()) if event_ids else []
        published_ids = [event.id for event in events if event.results_published]
        score_rows = [score for score in score_rows if score.event_id in published_ids and score.submission_external_id in visible_submission_ids]
        rubric_rows = []
        if snapshot is None and not registrations:
            raise HTTPException(status_code=404, detail="Workspace has not been initialized.")

    vote_counts: dict[tuple[str, int], int] = {}
    for submission in submissions:
        count = await session.scalar(select(func.count(CommunityVote.id)).where(
            CommunityVote.event_id == submission.event_id,
            CommunityVote.submission_id == submission.external_id,
        )) or 0
        vote_counts[(submission.event_id, submission.external_id)] = submission.legacy_votes + count

    judge_ids = {score.judge_account_id for score in score_rows}
    judges = (await session.scalars(select(Account).where(Account.id.in_(judge_ids)))).all() if judge_ids else []
    judge_emails = {judge.id: judge.email for judge in judges}
    registrations_data = [RegistrationData(
        eventId=item.event_id, name=item.name, email=item.email, track=item.track,
        teamPreference=item.team_preference, teamName=item.team_name,
    ) for item in registrations]
    submissions_data = [ProjectSubmissionData(
        id=item.external_id, eventId=item.event_id, title=item.title, team=item.team, track=item.track,
        submitterEmail=item.submitter_email, description=item.description, repositoryUrl=item.repository_url,
        demoUrl=item.demo_url, status=item.status, score=item.score,
        votes=vote_counts.get((item.event_id, item.external_id), item.legacy_votes),
    ) for item in submissions]
    scores_data = [JudgeScoreData(
        id=item.id, eventId=item.event_id, submissionId=item.submission_external_id,
        judgeEmail=judge_emails.get(item.judge_account_id, ""),
        criterionScores=item.criterion_scores, comment=item.comment,
    ) for item in score_rows]
    return auxiliary.model_copy(update={
        "events": [_event_data(event) for event in events] if role == "organizer" else [],
        "registrations": registrations_data,
        "project_submissions": submissions_data,
        "judging_rubric": [RubricCriterionData(id=row.criterion_id, label=row.label, weight=row.weight) for row in rubric_rows],
        "judge_scores": scores_data,
        "published_event_ids": published_ids,
        "judgingNormalized": bool(events) and all(event.judging_normalized for event in events),
        "resultsPublished": bool(published_ids),
    })


async def save_workspace(session: AsyncSession, account: Account, workspace: WorkspaceData) -> WorkspaceData:
    role = getattr(account, "active_role", account.role)
    owner_id = getattr(account, "active_workspace_owner_id", account.id)
    if role != "organizer" and workspace.events:
        raise HTTPException(status_code=403, detail="Only organizers can publish hackathon events.")

    for payload in workspace.events:
        event = await session.get(HackathonEvent, payload.id)
        if event is not None and event.owner_id != owner_id:
            raise HTTPException(status_code=409, detail="This event id is already owned by another organization.")
        if event is None:
            event = HackathonEvent(id=payload.id, owner_id=owner_id)
            session.add(event)
        for field in (
            "title", "host", "category", "format", "dates", "deadline", "location", "description", "prize",
            "participants", "spots", "tracks", "eligibility", "color", "symbol",
        ):
            setattr(event, field, getattr(payload, field))
        event.schedule = [item.model_dump(mode="json", by_alias=True) for item in payload.schedule]
        event.registration_deadline = payload.registration_deadline
        event.submission_deadline = payload.submission_deadline
        event.voting_deadline = payload.voting_deadline
        event.is_archived = payload.is_archived
        publish_requested = payload.id in workspace.published_event_ids
        if publish_requested and not event.results_published and event.voting_deadline and not _is_closed(event.voting_deadline):
            raise HTTPException(status_code=409, detail="Results cannot be published until the voting window closes.")
        event.results_published = publish_requested
        event.judging_normalized = workspace.judgingNormalized

    await session.flush()
    event_rows = {event.id: event for event in (await session.scalars(select(HackathonEvent))).all()}
    existing_registrations = {(item.event_id, item.email.casefold()): item for item in (await session.scalars(select(EventRegistration))).all()}
    for payload in workspace.registrations:
        event = event_rows.get(payload.event_id)
        if event is None:
            continue
        email = payload.email.casefold()
        if role != "organizer" and email != account.email.casefold():
            raise HTTPException(status_code=403, detail="You can only register your own account.")
        existing = existing_registrations.get((payload.event_id, email))
        if existing is None and (event.is_archived or _is_closed(event.registration_deadline or event.deadline)):
            raise HTTPException(status_code=409, detail="Registration is closed for this event.")
        account_id = await session.scalar(select(Account.id).where(func.lower(Account.email) == email))
        if existing is None:
            existing = EventRegistration(event_id=event.id, account_id=account_id, name=payload.name, email=email, track=payload.track, team_preference=payload.team_preference, team_name=payload.team_name)
            session.add(existing)
            existing_registrations[(payload.event_id, email)] = existing
        elif existing.account_id is None and account_id is not None:
            existing.account_id = account_id

    existing_submissions = {(item.event_id, item.external_id): item for item in (await session.scalars(select(ProjectSubmissionRecord))).all()}
    registration_keys = {(item.event_id, item.email.casefold()) for item in existing_registrations.values()}
    for payload in workspace.project_submissions:
        event = event_rows.get(payload.event_id)
        if event is None:
            continue
        email = payload.submitter_email.casefold()
        if role != "organizer" and email != account.email.casefold():
            raise HTTPException(status_code=403, detail="You can only submit projects for your own account.")
        if role != "organizer" and (payload.event_id, email) not in registration_keys:
            raise HTTPException(status_code=403, detail="Register for this event before submitting a project.")
        key = (payload.event_id, payload.id)
        existing = existing_submissions.get(key)
        if existing is None and (event.is_archived or _is_closed(event.submission_deadline)):
            raise HTTPException(status_code=409, detail="Project submissions are closed for this event.")
        submitter_id = await session.scalar(select(Account.id).where(func.lower(Account.email) == email)) if email else None
        if existing is not None and existing.submitter_email.casefold() != email:
            raise HTTPException(status_code=409, detail="This submission id is already in use.")
        if existing is None:
            existing = ProjectSubmissionRecord(
                event_id=payload.event_id, external_id=payload.id, submitter_account_id=submitter_id,
                submitter_email=email, title=payload.title, team=payload.team, track=payload.track,
                description=payload.description, repository_url=payload.repository_url, demo_url=payload.demo_url,
                status=payload.status,
                score=0 if role != "organizer" else payload.score, legacy_votes=0 if role != "organizer" else payload.votes,
            )
            session.add(existing)
            existing_submissions[key] = existing
        elif role == "organizer":
            existing.title = payload.title
            existing.team = payload.team
            existing.track = payload.track
            existing.description = payload.description
            existing.repository_url = payload.repository_url
            existing.demo_url = payload.demo_url
            existing.status = payload.status
            existing.score = payload.score
            existing.legacy_votes = payload.votes
        elif existing.submitter_account_id is None and submitter_id is not None:
            existing.submitter_account_id = submitter_id

    owned_event_ids = [event.id for event in event_rows.values() if event.owner_id == owner_id]
    if role == "organizer" and owned_event_ids:
        for event_id in owned_event_ids:
            criterion_ids = {criterion.id for criterion in workspace.judging_rubric}
            stored_criteria = (await session.scalars(select(RubricCriterionRecord).where(RubricCriterionRecord.event_id == event_id))).all()
            for row in stored_criteria:
                if row.criterion_id not in criterion_ids:
                    await session.delete(row)
            for criterion in workspace.judging_rubric:
                row = await session.scalar(select(RubricCriterionRecord).where(
                    RubricCriterionRecord.event_id == event_id,
                    RubricCriterionRecord.criterion_id == criterion.id,
                ))
                if row is None:
                    session.add(RubricCriterionRecord(event_id=event_id, criterion_id=criterion.id, label=criterion.label, weight=criterion.weight))
                else:
                    row.label, row.weight = criterion.label, criterion.weight
        for score in workspace.judge_scores:
            if score.event_id not in owned_event_ids:
                continue
            judge_id = await session.scalar(select(Account.id).where(func.lower(Account.email) == score.judge_email.casefold()))
            if judge_id is None:
                continue
            row = await session.scalar(select(JudgeScoreRecord).where(
                JudgeScoreRecord.event_id == score.event_id,
                JudgeScoreRecord.submission_external_id == score.submission_id,
                JudgeScoreRecord.judge_account_id == judge_id,
            ))
            if row is None:
                session.add(JudgeScoreRecord(event_id=score.event_id, submission_external_id=score.submission_id, judge_account_id=judge_id, criterion_scores=score.criterion_scores, comment=score.comment))
            else:
                row.criterion_scores, row.comment = score.criterion_scores, score.comment

    snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == owner_id))
    payload = workspace.model_dump(mode="json", by_alias=True)
    if snapshot is None:
        snapshot = WorkspaceSnapshot(owner_id=owner_id, payload=payload)
        session.add(snapshot)
    else:
        snapshot.payload = payload

    if role != "organizer":
        for registration in workspace.registrations:
            event = event_rows.get(registration.event_id)
            if event is None:
                continue
            owner_snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == event.owner_id))
            if owner_snapshot is not None:
                owner_payload = WorkspaceData.model_validate(owner_snapshot.payload)
                if not any(item.event_id == registration.event_id and item.email.casefold() == registration.email.casefold() for item in owner_payload.registrations):
                    owner_payload.registrations.append(registration)
                owner_snapshot.payload = owner_payload.model_dump(mode="json", by_alias=True)
        for submission in workspace.project_submissions:
            event = event_rows.get(submission.event_id)
            if event is None:
                continue
            owner_snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == event.owner_id))
            if owner_snapshot is not None:
                owner_payload = WorkspaceData.model_validate(owner_snapshot.payload)
                if not any(item.event_id == submission.event_id and item.id == submission.id for item in owner_payload.project_submissions):
                    owner_payload.project_submissions.append(submission)
                owner_snapshot.payload = owner_payload.model_dump(mode="json", by_alias=True)
    await session.commit()
    return await load_workspace(session, account, owner_id)
"""Team, judge, vote, certificate, score normalization, and archive workflows."""

from collections import defaultdict
from datetime import timezone
from secrets import token_urlsafe
from statistics import fmean, pstdev

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_account
from app.core.database import get_db
from app.models.account import Account
from app.models.event import EventRegistration, HackathonEvent, JudgeScoreRecord, ProjectSubmissionRecord
from app.models.lifecycle import Certificate, CommunityVote, EventJudge, OrganizationMembership, Team, TeamMember
from app.models.lifecycle import Certificate, CommunityVote, EventAuditEntry, EventJudge, OrganizationMembership, ProjectComment, Team, TeamMember
from app.models.workspace import WorkspaceSnapshot
from app.schemas.lifecycle import (
    CertificateVerificationView,
    CertificateView,
    CommunityVoteCreate,
    JudgeAssignmentCreate,
    JudgeAssignmentView,
    EventJudgeView,
    JudgeReview,
    JudgeScoreSubmission,
    TeamCreate,
    TeamView,
)
from app.schemas.workspace import JudgeScoreData, RegistrationData, WorkspaceData
from app.services.workspace_store import _is_closed

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


def _active_role(account: Account) -> str:
    return getattr(account, "active_role", account.role)


def _workspace_owner(account: Account) -> int:
    return getattr(account, "active_workspace_owner_id", account.id)


@router.get("/judge-scores")
async def read_judge_scores(
    judge_email: str = Query(alias="judge"),
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    """Return scores only to the assigned judge who authored them."""
    if _active_role(account) != "judge":
        raise HTTPException(status_code=403, detail="Judge access is required to view judge scores.")
    if account.email.casefold() != judge_email.casefold():
        raise HTTPException(status_code=403, detail="Judges cannot view another judge's scores.")
    assignments = (await session.scalars(select(EventJudge).where(EventJudge.account_id == account.id))).all()
    if not assignments:
        raise HTTPException(status_code=403, detail="You are not assigned to judge an event.")
    event_ids = {assignment.event_id for assignment in assignments}
    rows = (await session.scalars(select(JudgeScoreRecord).where(
        JudgeScoreRecord.judge_account_id == account.id,
        JudgeScoreRecord.event_id.in_(event_ids),
    ))).all()
    return [{
        "eventId": row.event_id,
        "submissionId": row.submission_external_id,
        "criterionScores": row.criterion_scores,
        "comment": row.comment,
    } for row in rows]


async def _registered_event(session: AsyncSession, event_id: str, email: str) -> tuple[WorkspaceSnapshot, WorkspaceData]:
    snapshots = list((await session.scalars(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id.is_not(None)))).all())
    owner_snapshot = None
    owner_workspace = None
    registered = False
    for snapshot in snapshots:
        workspace = WorkspaceData.model_validate(snapshot.payload)
        if any(item.id == event_id and not item.is_archived for item in workspace.events):
            owner_snapshot, owner_workspace = snapshot, workspace
        if any(item.event_id == event_id and item.email.casefold() == email.casefold() for item in workspace.registrations):
            registered = True
    if owner_snapshot is None or owner_workspace is None:
        raise HTTPException(status_code=404, detail="Event was not found.")
    if not registered:
        raise HTTPException(status_code=403, detail="Register for this event before joining a team.")
    return owner_snapshot, owner_workspace


async def _load_owner_workspace(session: AsyncSession, account: Account) -> tuple[WorkspaceSnapshot, WorkspaceData]:
    snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == _workspace_owner(account)))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Create an event before using this action.")
    return snapshot, WorkspaceData.model_validate(snapshot.payload)


async def _set_registration_team(session: AsyncSession, event_id: str, email: str, team_name: str) -> None:
    registration = await session.scalar(select(EventRegistration).where(
        EventRegistration.event_id == event_id,
        func.lower(EventRegistration.email) == email.casefold(),
    ))
    if registration is not None:
        registration.team_name = team_name
        registration.team_preference = "I have a team"
    snapshots = (await session.scalars(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id.is_not(None)))).all()
    for snapshot in snapshots:
        workspace = WorkspaceData.model_validate(snapshot.payload)
        changed = False
        for registration in workspace.registrations:
            if registration.event_id == event_id and registration.email.casefold() == email.casefold():
                registration.team_name = team_name
                registration.team_preference = "I have a team"
                changed = True
        if changed:
            snapshot.payload = workspace.model_dump(mode="json", by_alias=True)


@router.get("/teams", response_model=list[TeamView])
async def list_teams(
    event_id: str = Query(alias="eventId"),
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> list[TeamView]:
    teams = (await session.scalars(select(Team).where(Team.event_id == event_id))).all()
    result = []
    for team in teams:
        count = await session.scalar(select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)) or 0
        joined = await session.scalar(select(TeamMember.id).where(TeamMember.team_id == team.id, TeamMember.account_id == account.id)) is not None
        result.append(TeamView(id=team.id, event_id=team.event_id, name=team.name, track=team.track, members=count, joined=joined, invite_code=team.invite_code or "" if joined else ""))
    return result


@router.post("/teams", response_model=TeamView, status_code=201)
async def create_team(
    payload: TeamCreate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> TeamView:
    if _active_role(account) != "participant":
        raise HTTPException(status_code=403, detail="Participant access is required to create a team.")
    organizer_snapshot, organizer_workspace = await _registered_event(session, payload.event_id, account.email)
    event = next((item for item in organizer_workspace.events if item.id == payload.event_id), None)
    if event is None or event.is_archived:
        raise HTTPException(status_code=409, detail="This event is not accepting teams.")
    existing_team = await session.scalar(
        select(TeamMember.id).join(Team, Team.id == TeamMember.team_id).where(
            Team.event_id == payload.event_id,
            TeamMember.account_id == account.id,
        )
    )
    if existing_team is not None:
        raise HTTPException(status_code=409, detail="You already belong to a team for this event.")
    team = Team(event_id=payload.event_id, organization_owner_id=organizer_snapshot.owner_id, captain_id=account.id, name=payload.name.strip(), track=payload.track.strip(), invite_code=token_urlsafe(18))
    session.add(team)
    await session.flush()
    session.add(TeamMember(team_id=team.id, account_id=account.id, role="captain"))
    await _set_registration_team(session, payload.event_id, account.email, team.name)
    await session.commit()
    return TeamView(id=team.id, event_id=team.event_id, name=team.name, track=team.track, members=1, joined=True, invite_code=team.invite_code or "")


@router.post("/teams/{team_id}/join", response_model=TeamView)
async def join_team(
    team_id: int,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> TeamView:
    if _active_role(account) != "participant":
        raise HTTPException(status_code=403, detail="Participant access is required to join a team.")
    team = await session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team was not found.")
    await _registered_event(session, team.event_id, account.email)
    current_team = await session.scalar(
        select(TeamMember.team_id).join(Team, Team.id == TeamMember.team_id).where(
            Team.event_id == team.event_id,
            TeamMember.account_id == account.id,
        )
    )
    if current_team is not None and current_team != team.id:
        raise HTTPException(status_code=409, detail="You already belong to another team for this event.")
    organizer_snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == team.organization_owner_id))
    organizer_workspace = WorkspaceData.model_validate(organizer_snapshot.payload) if organizer_snapshot else WorkspaceData()
    event = next((item for item in organizer_workspace.events if item.id == team.event_id), None)
    if event is None or event.is_archived or not team.join_open:
        raise HTTPException(status_code=409, detail="This team is no longer accepting members.")
    if await session.scalar(select(TeamMember.id).where(TeamMember.team_id == team.id, TeamMember.account_id == account.id)) is None:
        session.add(TeamMember(team_id=team.id, account_id=account.id, role="member"))
        await _set_registration_team(session, team.event_id, account.email, team.name)
        await session.commit()
    count = await session.scalar(select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)) or 0
    return TeamView(id=team.id, event_id=team.event_id, name=team.name, track=team.track, members=count, joined=True, invite_code=team.invite_code or "")


@router.post("/teams/invite/{invite_code}/join", response_model=TeamView)
async def join_team_by_invite(
    invite_code: str,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> TeamView:
    if _active_role(account) != "participant":
        raise HTTPException(status_code=403, detail="Participant access is required to join a team.")
    team = await session.scalar(select(Team).where(Team.invite_code == invite_code))
    if team is None:
        raise HTTPException(status_code=404, detail="Team invite was not found.")
    await _registered_event(session, team.event_id, account.email)
    current_team = await session.scalar(
        select(TeamMember.team_id).join(Team, Team.id == TeamMember.team_id).where(
            Team.event_id == team.event_id,
            TeamMember.account_id == account.id,
        )
    )
    if current_team is not None and current_team != team.id:
        raise HTTPException(status_code=409, detail="You already belong to another team for this event.")
    event = await session.get(HackathonEvent, team.event_id)
    if event is None or event.is_archived or not team.join_open:
        raise HTTPException(status_code=409, detail="This team is no longer accepting members.")
    member = await session.scalar(select(TeamMember.id).where(TeamMember.team_id == team.id, TeamMember.account_id == account.id))
    if member is None:
        session.add(TeamMember(team_id=team.id, account_id=account.id, role="member"))
        await _set_registration_team(session, team.event_id, account.email, team.name)
        await session.commit()
    count = await session.scalar(select(func.count(TeamMember.id)).where(TeamMember.team_id == team.id)) or 0
    return TeamView(id=team.id, event_id=team.event_id, name=team.name, track=team.track, members=count, joined=True, invite_code=team.invite_code or "")


@router.post("/events/{event_id}/judges", response_model=JudgeAssignmentView, status_code=201)
async def assign_judge(
    event_id: str,
    payload: JudgeAssignmentCreate,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> JudgeAssignmentView:
    if _active_role(account) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required to assign judges.")
    owner, workspace = await _load_owner_workspace(session, account)
    if not any(event.id == event_id and not event.is_archived for event in workspace.events):
        raise HTTPException(status_code=404, detail="Event was not found in this organization.")
    judge = await session.scalar(select(Account).where(Account.email == payload.email.casefold()))
    if judge is None:
        raise HTTPException(status_code=404, detail="Create a participant account for this person before assigning them.")
    assignment = await session.scalar(select(EventJudge).where(EventJudge.event_id == event_id, EventJudge.account_id == judge.id))
    if assignment is None:
        session.add(EventJudge(event_id=event_id, organization_owner_id=owner.owner_id, account_id=judge.id))
        roles = list(judge.roles or [judge.role])
        if "judge" not in roles:
            roles.append("judge")
            judge.roles = roles
        await session.commit()
    return JudgeAssignmentView(event_id=event_id, account_id=judge.id, email=judge.email, full_name=judge.full_name)


@router.get("/events/{event_id}/judges", response_model=list[EventJudgeView])
async def list_event_judges(event_id: str, account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> list[EventJudgeView]:
    if _active_role(account) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required to view judge assignments.")
    owner = _workspace_owner(account)
    assignments = (await session.scalars(select(EventJudge).where(EventJudge.event_id == event_id, EventJudge.organization_owner_id == owner))).all()
    result = []
    for assignment in assignments:
        judge = await session.get(Account, assignment.account_id)
        if judge:
            result.append(EventJudgeView(account_id=judge.id, email=judge.email, full_name=judge.full_name))
    return result


@router.get("/judge-reviews", response_model=list[JudgeReview])
async def list_judge_reviews(account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> list[JudgeReview]:
    assignments = (await session.scalars(select(EventJudge).where(EventJudge.account_id == account.id))).all()
    reviews: list[JudgeReview] = []
    for assignment in assignments:
        snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == assignment.organization_owner_id))
        if snapshot is None:
            continue
        workspace = WorkspaceData.model_validate(snapshot.payload)
        event = next((item for item in workspace.events if item.id == assignment.event_id), None)
        if event is None or event.is_archived:
            continue
        for submission in workspace.project_submissions:
            if submission.event_id != event.id or submission.status == "Draft":
                continue
            previous = next((score for score in workspace.judge_scores if score.event_id == event.id and score.submission_id == submission.id and score.judge_email.casefold() == account.email.casefold()), None)
            reviews.append(JudgeReview(
                event_id=event.id, event_title=event.title, event_tracks=event.tracks,
                submission_id=submission.id, submission_title=submission.title, submission_team=submission.team,
                track=submission.track, description=submission.description,
                rubric=[item.model_dump(by_alias=True) for item in workspace.judging_rubric],
                score=previous.criterion_scores if previous else {}, comment=previous.comment if previous else "",
            ))
    return reviews


@router.put("/judge-reviews/{event_id}", response_model=JudgeReview)
async def save_judge_review(
    event_id: str,
    payload: JudgeScoreSubmission,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
) -> JudgeReview:
    assignment = await session.scalar(select(EventJudge).where(EventJudge.account_id == account.id, EventJudge.event_id == event_id))
    if assignment is None:
        raise HTTPException(status_code=403, detail="You are not assigned to judge this event.")
    snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == assignment.organization_owner_id))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Event workspace was not found.")
    workspace = WorkspaceData.model_validate(snapshot.payload)
    event = next((item for item in workspace.events if item.id == event_id), None)
    submission = next((item for item in workspace.project_submissions if item.event_id == event_id and item.id == payload.submission_id), None)
    if event is None or event.is_archived or submission is None:
        raise HTTPException(status_code=404, detail="Project submission was not found.")
    criterion_ids = {criterion.id for criterion in workspace.judging_rubric}
    if not criterion_ids or set(payload.criterion_scores) != criterion_ids or any(score < 1 or score > 5 for score in payload.criterion_scores.values()):
        raise HTTPException(status_code=422, detail="Score every rubric criterion from 1 to 5.")
    previous = next((score for score in workspace.judge_scores if score.event_id == event_id and score.submission_id == submission.id and score.judge_email.casefold() == account.email.casefold()), None)
    next_id = max((score.id for score in workspace.judge_scores), default=0) + 1
    score = JudgeScoreData(id=previous.id if previous else next_id, event_id=event_id, submission_id=submission.id, judge_email=account.email, criterion_scores=payload.criterion_scores, comment=payload.comment)
    if previous:
        workspace.judge_scores = [score if item.id == previous.id else item for item in workspace.judge_scores]
    else:
        workspace.judge_scores.append(score)
    workspace.project_submissions = [item.model_copy(update={"status": "Scored"}) if item.id == submission.id and item.event_id == event_id else item for item in workspace.project_submissions]
    weighted = [
        sum((judge.criterion_scores.get(criterion.id, 0) / 5) * criterion.weight for criterion in workspace.judging_rubric)
        for judge in workspace.judge_scores if judge.event_id == event_id and judge.submission_id == submission.id
    ]
    total_score = round(fmean(weighted)) if weighted else 0
    workspace.project_submissions = [item.model_copy(update={"score": total_score}) if item.id == submission.id and item.event_id == event_id else item for item in workspace.project_submissions]
    snapshot.payload = workspace.model_dump(mode="json", by_alias=True)
    judge_score = await session.scalar(select(JudgeScoreRecord).where(
        JudgeScoreRecord.event_id == event_id,
        JudgeScoreRecord.submission_external_id == submission.id,
        JudgeScoreRecord.judge_account_id == account.id,
    ))
    if judge_score is None:
        judge_score = JudgeScoreRecord(
            event_id=event_id, submission_external_id=submission.id, judge_account_id=account.id,
            criterion_scores=payload.criterion_scores, comment=payload.comment,
        )
        session.add(judge_score)
    else:
        judge_score.criterion_scores = payload.criterion_scores
        judge_score.comment = payload.comment
    normalized_submission = await session.scalar(select(ProjectSubmissionRecord).where(
        ProjectSubmissionRecord.event_id == event_id,
        ProjectSubmissionRecord.external_id == submission.id,
    ))
    if normalized_submission is not None:
        normalized_submission.status = "Scored"
        normalized_submission.score = total_score
    await session.commit()
    return JudgeReview(event_id=event.id, event_title=event.title, event_tracks=event.tracks, submission_id=submission.id, submission_title=submission.title, submission_team=submission.team, track=submission.track, description=submission.description, rubric=[item.model_dump(by_alias=True) for item in workspace.judging_rubric], score=score.criterion_scores, comment=score.comment)


@router.post("/events/{event_id}/normalize", response_model=WorkspaceData)
async def normalize_event_scores(event_id: str, account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> WorkspaceData:
    if _active_role(account) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required to normalize scores.")
    snapshot, workspace = await _load_owner_workspace(session, account)
    if not any(event.id == event_id and not event.is_archived for event in workspace.events):
        raise HTTPException(status_code=404, detail="Event was not found.")
    rubric = workspace.judging_rubric
    by_judge: dict[str, dict[int, float]] = defaultdict(dict)
    for review in workspace.judge_scores:
        if review.event_id == event_id:
            by_judge[review.judge_email.casefold()][review.submission_id] = sum((review.criterion_scores.get(item.id, 0) / 5) * item.weight for item in rubric)
    if not by_judge:
        raise HTTPException(status_code=409, detail="There are no completed judge scores to normalize.")
    distributions = {judge: (fmean(values.values()), pstdev(values.values())) for judge, values in by_judge.items() if values}
    normalized: dict[int, list[float]] = defaultdict(list)
    for judge, values in by_judge.items():
        mean, deviation = distributions[judge]
        for submission_id, raw_score in values.items():
            normalized[submission_id].append(raw_score if deviation == 0 else max(0.0, min(100.0, 50.0 + 15.0 * ((raw_score - mean) / deviation))))
    workspace.project_submissions = [item.model_copy(update={"score": round(fmean(normalized[item.id]))}) if item.event_id == event_id and item.id in normalized else item for item in workspace.project_submissions]
    workspace.judgingNormalized = True
    event_row = await session.get(HackathonEvent, event_id)
    if event_row is not None:
        event_row.judging_normalized = True
    for submission in workspace.project_submissions:
        if submission.event_id != event_id:
            continue
        normalized_submission = await session.scalar(select(ProjectSubmissionRecord).where(
            ProjectSubmissionRecord.event_id == event_id,
            ProjectSubmissionRecord.external_id == submission.id,
        ))
        if normalized_submission is not None:
            normalized_submission.score = submission.score
    snapshot.payload = workspace.model_dump(mode="json", by_alias=True)
    await session.commit()
    return workspace


@router.post("/events/{event_id}/votes", status_code=201)
async def cast_community_vote(event_id: str, payload: CommunityVoteCreate, account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> dict[str, int]:
    if _active_role(account) != "participant":
        raise HTTPException(status_code=403, detail="Participant access is required to vote.")
    event = await session.get(HackathonEvent, event_id)
    if event is None or event.is_archived:
        raise HTTPException(status_code=404, detail="Event was not found.")
    if _is_closed(event.voting_deadline or event.submission_deadline):
        raise HTTPException(status_code=409, detail="Voting is closed for this event.")
    submission = await session.scalar(select(ProjectSubmissionRecord).where(
        ProjectSubmissionRecord.event_id == event_id,
        ProjectSubmissionRecord.external_id == payload.submission_id,
        ProjectSubmissionRecord.status != "Draft",
    ))
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission was not found.")
    if submission.submitter_account_id == account.id or submission.submitter_email.casefold() == account.email.casefold():
        raise HTTPException(status_code=409, detail="You cannot vote for your own submission.")
    voted = await session.scalar(select(CommunityVote.id).where(
        CommunityVote.event_id == event_id,
        CommunityVote.voter_id == account.id,
    ))
    if voted is not None:
        raise HTTPException(status_code=409, detail="You have already cast your event ballot.")
    session.add(CommunityVote(event_id=event_id, submission_id=submission.external_id, voter_id=account.id))
    session.add(EventAuditEntry(event_id=event_id, actor_id=account.id, action="community.vote", target_id=str(submission.external_id), detail={}))
    await session.commit()
    count = await session.scalar(select(func.count(CommunityVote.id)).where(
        CommunityVote.event_id == event_id,
        CommunityVote.submission_id == submission.external_id,
    )) or 0
    return {"votes": submission.legacy_votes + count}


@router.post("/events/{event_id}/archive", response_model=WorkspaceData)
async def archive_event(event_id: str, account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> WorkspaceData:
    if _active_role(account) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required to archive events.")
    snapshot, workspace = await _load_owner_workspace(session, account)
    found = False
    for event in workspace.events:
        if event.id == event_id:
            event.is_archived = True
            found = True
    if not found:
        raise HTTPException(status_code=404, detail="Event was not found in this organization.")
    snapshot.payload = workspace.model_dump(mode="json", by_alias=True)
    event_row = await session.get(HackathonEvent, event_id)
    if event_row is not None and event_row.owner_id == _workspace_owner(account):
        event_row.is_archived = True
    await session.commit()
    return workspace


@router.post("/events/{event_id}/certificates", response_model=list[CertificateView])
async def issue_certificates(event_id: str, account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> list[CertificateView]:
    if _active_role(account) != "organizer":
        raise HTTPException(status_code=403, detail="Organizer access is required to issue certificates.")
    snapshot, workspace = await _load_owner_workspace(session, account)
    event = next((item for item in workspace.events if item.id == event_id and not item.is_archived), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Event was not found in this organization.")
    if event_id not in workspace.published_event_ids:
        raise HTTPException(status_code=409, detail="Publish results before issuing certificates.")
    certificates = []
    for registration in workspace.registrations:
        if registration.event_id != event_id:
            continue
        recipient = await session.scalar(select(Account).where(Account.email == registration.email.casefold()))
        if recipient is None:
            continue
        certificate = await session.scalar(select(Certificate).where(Certificate.event_id == event_id, Certificate.recipient_id == recipient.id))
        if certificate is None:
            certificate = Certificate(event_id=event_id, recipient_id=recipient.id, organization_owner_id=snapshot.owner_id, verification_code=token_urlsafe(18))
            session.add(certificate)
            await session.flush()
        certificates.append(CertificateView(event_id=event_id, event_title=event.title, recipient_name=recipient.full_name, verification_code=certificate.verification_code, issued_at=certificate.created_at))
    workspace.certificatesIssued = len(certificates)
    snapshot.payload = workspace.model_dump(mode="json", by_alias=True)
    await session.commit()
    return certificates


@router.get("/certificates/verify", response_model=CertificateVerificationView)
async def verify_certificate(
    code: str = Query(..., min_length=1, description="Certificate verification code"),
    session: AsyncSession = Depends(get_db),
) -> CertificateVerificationView:
    certificate = await session.scalar(select(Certificate).where(Certificate.verification_code == code.strip()))
    if certificate is None:
        return CertificateVerificationView(
            valid=False,
            event_id="",
            event_title="",
            recipient_name="",
            issued_at=datetime.now(timezone.utc),
            verification_code=code.strip(),
        )

    snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == certificate.organization_owner_id))
    workspace = WorkspaceData.model_validate(snapshot.payload) if snapshot else WorkspaceData()
    event = next((item for item in workspace.events if item.id == certificate.event_id), None)
    recipient = await session.get(Account, certificate.recipient_id)
    return CertificateVerificationView(
        valid=True,
        event_id=certificate.event_id,
        event_title=event.title if event else "Archived hackathon",
        recipient_name=recipient.full_name if recipient else "Participant",
        issued_at=certificate.created_at,
        verification_code=certificate.verification_code,
    )


@router.get("/certificates/me", response_model=list[CertificateView])
async def my_certificates(account: Account = Depends(get_current_account), session: AsyncSession = Depends(get_db)) -> list[CertificateView]:
    certificates = (await session.scalars(select(Certificate).where(Certificate.recipient_id == account.id))).all()
    result = []
    for certificate in certificates:
        snapshot = await session.scalar(select(WorkspaceSnapshot).where(WorkspaceSnapshot.owner_id == certificate.organization_owner_id))
        workspace = WorkspaceData.model_validate(snapshot.payload) if snapshot else WorkspaceData()
        event = next((item for item in workspace.events if item.id == certificate.event_id), None)
        result.append(CertificateView(event_id=certificate.event_id, event_title=event.title if event else "Archived hackathon", recipient_name=account.full_name, verification_code=certificate.verification_code, issued_at=certificate.created_at))
    return result

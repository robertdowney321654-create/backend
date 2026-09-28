"""Seed the official Dogfood acceptance fixture for local/offline runs."""

import json
from collections import defaultdict
from pathlib import Path
from secrets import token_urlsafe

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, OrganizationProfile
from app.models.event import EventRegistration, HackathonEvent, JudgeScoreRecord, ProjectSubmissionRecord, RubricCriterionRecord
from app.models.lifecycle import EventJudge, OrganizationMembership, Team, TeamMember
from app.models.workspace import WorkspaceSnapshot
from app.schemas.workspace import (
    EventData,
    JudgeScoreData,
    ProjectSubmissionData,
    RegistrationData,
    RubricCriterionData,
    ScheduleItemData,
    TeamData,
    WorkspaceData,
)

DOGFOOD_EVENT_ID = "evt_01"
DOGFOOD_ORGANIZER_EMAIL = "organizer@dogfoodhack.local"
DOGFOOD_INVITEE_EMAIL = "invitee@dogfoodhack.local"
DOGFOOD_ADMIN_EMAIL = "admin@dogfoodhack.local"
DOGFOOD_TOKENS = {
    "organizer": ("dogfood-organizer", DOGFOOD_ORGANIZER_EMAIL, "organizer"),
    "judge_a": ("dogfood-judge-a", "tomas.varga@example.org", "judge"),
    "judge_b": ("dogfood-judge-b", "wei.lindqvist@example.org", "judge"),
    "participant": ("dogfood-participant", "priya1@example.org", "participant"),
    "invitee": ("dogfood-invitee", DOGFOOD_INVITEE_EMAIL, "participant"),
    "admin": ("dogfood-admin", DOGFOOD_ADMIN_EMAIL, "admin"),
}


def fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures.json"


async def seed_dogfood_fixture(session: AsyncSession) -> bool:
    """Load the official fixture once; never overwrite organizer changes."""
    if await session.get(HackathonEvent, DOGFOOD_EVENT_ID) is not None:
        return False

    with fixture_path().open(encoding="utf-8") as source:
        fixture = json.load(source)

    role_by_email: dict[str, set[str]] = defaultdict(set)
    name_by_email: dict[str, str] = {}
    for judge in fixture["judges"]:
        email = judge["email"].casefold()
        role_by_email[email].add("judge")
        name_by_email[email] = judge["name"]
    for team in fixture["teams"]:
        for email in team["members"]:
            normalized_email = email.casefold()
            role_by_email[normalized_email].add("participant")
            name_by_email.setdefault(normalized_email, email.split("@", 1)[0])
    role_by_email[DOGFOOD_ORGANIZER_EMAIL].add("organizer")
    name_by_email[DOGFOOD_ORGANIZER_EMAIL] = "Dogfood Organizer"
    role_by_email[DOGFOOD_INVITEE_EMAIL].add("participant")
    name_by_email[DOGFOOD_INVITEE_EMAIL] = "Dogfood Invitee"
    role_by_email[DOGFOOD_ADMIN_EMAIL].add("admin")
    name_by_email[DOGFOOD_ADMIN_EMAIL] = "Dogfood Admin"

    password_hash = PasswordHash.recommended().hash("dogfood-seed-only-not-for-login")
    accounts: dict[str, Account] = {}
    for email, roles in role_by_email.items():
        account = await session.scalar(select(Account).where(Account.email == email))
        if account is None:
            preferred_role = "admin" if "admin" in roles else "organizer" if "organizer" in roles else "judge" if "judge" in roles else "participant"
            account = Account(
                email=email,
                full_name=name_by_email[email],
                password_hash=password_hash,
                role=preferred_role,
                roles=sorted(roles),
            )
            session.add(account)
        else:
            account.roles = sorted(set(account.roles or [account.role]) | roles)
        accounts[email] = account

    await session.flush()
    organizer = accounts[DOGFOOD_ORGANIZER_EMAIL]
    organization = await session.scalar(select(OrganizationProfile).where(OrganizationProfile.owner_id == organizer.id))
    if organization is None:
        organization = OrganizationProfile(owner_id=organizer.id, name="Dogfood Hackathon")
        session.add(organization)
        await session.flush()
    membership = await session.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization.id,
        OrganizationMembership.account_id == organizer.id,
    ))
    if membership is None:
        session.add(OrganizationMembership(organization_id=organization.id, account_id=organizer.id, role="owner"))

    tracks = {track["id"]: track["name"] for track in fixture["tracks"]}
    event = fixture["event"]
    closes = event["submissions_close"]
    schedule = [
        {"date": closes, "title": "Fixture event closes", "detail": "Loaded from the official Dogfood fixture."},
    ]
    event_row = HackathonEvent(
        id=event["id"], owner_id=organizer.id, title=event["name"], host="Dogfood Hackathon",
        category="Open source", format="Online", dates="Sample Hack 2026", deadline=closes,
        registration_deadline=closes, submission_deadline=closes, voting_deadline=closes, location="Online",
        description="Official Dogfood acceptance fixture.", prize="Community awards",
        participants=len(role_by_email), spots=len(role_by_email), tracks=list(tracks.values()),
        eligibility="Dogfood fixture participants.", color="mint", symbol="D", schedule=schedule,
    )
    session.add(event_row)

    project_by_team: dict[str, list[dict[str, object]]] = defaultdict(list)
    project_ids: dict[str, int] = {}
    project_by_id: dict[str, dict[str, object]] = {}
    for project in fixture["projects"]:
        project_by_team[project["team"]].append(project)
        project_id = int(str(project["id"]).rsplit("_", 1)[1])
        project_ids[project["id"]] = project_id
        project_by_id[project["id"]] = project

    team_names_used: set[str] = set()
    team_name_by_id: dict[str, str] = {}
    registrations: dict[str, RegistrationData] = {}
    fixture_teams: dict[str, Team] = {}
    for team_data in fixture["teams"]:
        external_team_id = team_data["id"]
        members = [email.casefold() for email in team_data["members"]]
        display_name = team_data["name"]
        if display_name in team_names_used:
            display_name = f"{display_name} ({external_team_id})"
        team_names_used.add(display_name)
        team_name_by_id[external_team_id] = display_name
        related_projects = project_by_team.get(external_team_id, [])
        track_id = str(related_projects[0]["track"]) if related_projects else next(iter(tracks))
        track_name = tracks.get(track_id, track_id)
        team = Team(
            event_id=event["id"], organization_owner_id=organizer.id,
            captain_id=accounts[members[0]].id, name=display_name, track=track_name,
            invite_code=token_urlsafe(18),
        )
        session.add(team)
        await session.flush()
        fixture_teams[external_team_id] = team
        for index, email in enumerate(members):
            session.add(TeamMember(team_id=team.id, account_id=accounts[email].id, role="captain" if index == 0 else "member"))
            registrations[email] = RegistrationData(
                eventId=event["id"], name=accounts[email].full_name, email=email,
                track=track_name, teamPreference="I have a team", teamName=display_name,
            )
            session.add(EventRegistration(
                event_id=event["id"], account_id=accounts[email].id, name=accounts[email].full_name,
                email=email, track=track_name, team_preference="I have a team", team_name=display_name,
            ))

    invite_track = next(iter(tracks.values()))
    registrations[DOGFOOD_INVITEE_EMAIL] = RegistrationData(
        eventId=event["id"], name=name_by_email[DOGFOOD_INVITEE_EMAIL], email=DOGFOOD_INVITEE_EMAIL,
        track=invite_track, teamPreference="Looking for a team", teamName="",
    )
    session.add(EventRegistration(
        event_id=event["id"], account_id=accounts[DOGFOOD_INVITEE_EMAIL].id,
        name=name_by_email[DOGFOOD_INVITEE_EMAIL], email=DOGFOOD_INVITEE_EMAIL,
        track=invite_track, team_preference="Looking for a team", team_name="",
    ))

    await session.flush()

    score_by_project: dict[str, list[dict[str, object]]] = defaultdict(list)
    criteria_weights = {"functionality": 40, "quality": 35, "innovation": 25}
    for criterion_id, weight in criteria_weights.items():
        session.add(RubricCriterionRecord(event_id=event["id"], criterion_id=criterion_id, label=criterion_id.title(), weight=weight))
    for score in fixture["scores"]:
        score_by_project[str(score["project"])].append(score)

    for project in fixture["projects"]:
        project_id = str(project["id"])
        external_id = project_ids[project_id]
        team = fixture_teams[str(project["team"])]
        track_id = str(project["track"])
        team_members = [email.casefold() for email in next(item for item in fixture["teams"] if item["id"] == project["team"])["members"]]
        submitter_email = team_members[0]
        reviews = score_by_project.get(project_id, [])
        session.add(ProjectSubmissionRecord(
            event_id=event["id"], external_id=external_id, submitter_account_id=accounts[submitter_email].id,
            submitter_email=submitter_email, title=str(project["title"]), team=team.name,
            track=tracks.get(track_id, track_id), description=str(project.get("summary", "")),
            repository_url=str(project.get("repo_url", "")), demo_url="",
            status="Scored" if reviews else "Submitted", score=0, legacy_votes=0,
        ))
        for score in reviews:
            judge = next(item for item in fixture["judges"] if item["id"] == score["judge"])
            judge_account = accounts[judge["email"].casefold()]
            session.add(JudgeScoreRecord(
                event_id=event["id"], submission_external_id=external_id,
                judge_account_id=judge_account.id,
                criterion_scores={str(key): int(value) for key, value in score.get("criteria", {}).items()},
                comment=str(score.get("comment", "")),
            ))

    for judge in fixture["judges"]:
        judge_account = accounts[judge["email"].casefold()]
        session.add(EventJudge(event_id=event["id"], organization_owner_id=organizer.id, account_id=judge_account.id))

    await session.flush()
    event_data = EventData(
        id=event["id"], title=event["name"], host="Dogfood Hackathon", category="Open source",
        format="Online", dates="Sample Hack 2026", deadline=closes, registrationDeadline=closes,
        submissionDeadline=closes, votingDeadline=closes, location="Online", description="Official Dogfood acceptance fixture.",
        prize="Community awards", participants=len(registrations), spots=len(registrations),
        tracks=list(tracks.values()), eligibility="Dogfood fixture participants.", color="mint", symbol="D",
        schedule=[ScheduleItemData(**item) for item in schedule],
    )
    project_rows = (await session.scalars(select(ProjectSubmissionRecord).where(ProjectSubmissionRecord.event_id == event["id"]))).all()
    score_rows = (await session.scalars(select(JudgeScoreRecord).where(JudgeScoreRecord.event_id == event["id"]))).all()
    score_emails = {account.id: account.email for account in accounts.values()}
    rubric_rows = (await session.scalars(select(RubricCriterionRecord).where(RubricCriterionRecord.event_id == event["id"]))).all()
    snapshot_workspace = WorkspaceData(
        events=[event_data],
        registrations=list(registrations.values()),
        projectSubmissions=[ProjectSubmissionData(
            id=row.external_id, eventId=row.event_id, title=row.title, team=row.team, track=row.track,
            submitterEmail=row.submitter_email, description=row.description, repositoryUrl=row.repository_url,
            demoUrl=row.demo_url, status=row.status, score=row.score, votes=row.legacy_votes,
        ) for row in project_rows],
        judgingRubric=[RubricCriterionData(id=row.criterion_id, label=row.label, weight=row.weight) for row in rubric_rows],
        judgeScores=[JudgeScoreData(
            id=row.id, eventId=row.event_id, submissionId=row.submission_external_id,
            judgeEmail=score_emails[row.judge_account_id], criterionScores=row.criterion_scores, comment=row.comment,
        ) for row in score_rows],
    )
    session.add(WorkspaceSnapshot(owner_id=organizer.id, payload=snapshot_workspace.model_dump(mode="json", by_alias=True)))
    await session.commit()
    return True
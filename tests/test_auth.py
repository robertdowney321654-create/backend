"""Account, role access, organization profile, and workspace isolation tests."""

import asyncio
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base, get_db
from app.main import app as fastapi_app
import app.models  # noqa: F401


async def exercise_account_flows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver") as client:
            anonymous = await client.get("/api/v1/workspace")
            assert anonymous.status_code == 401

            organizer = await client.post("/api/v1/auth/register", json={
                "full_name": "Riley Organizer", "email": "riley@example.org", "password": "secure-test-password",
                "role": "organizer", "organization_name": "Northstar Labs",
            })
            assert organizer.status_code == 201
            organizer_session = organizer.json()
            organizer_headers = {"Authorization": f"Bearer {organizer_session['access_token']}"}
            assert organizer_session["organization"]["name"] == "Northstar Labs"

            event = {
                "id": "northstar-build-day", "title": "Northstar Build Day", "host": "Northstar Labs",
                "category": "Open source", "format": "Online", "dates": "Nov 12, 2026",
                "deadline": "2099-11-11T23:59:00Z", "location": "Online", "description": "Build together.",
                "prize": "Community awards", "participants": 0, "spots": 50,
            }
            published = await client.put("/api/v1/workspace", headers=organizer_headers, json={
                "events": [event], "judgingRubric": [{"id": "impact", "label": "Impact", "weight": 100}],
            })
            assert published.status_code == 200
            public_events = await client.get("/api/v1/events")
            assert public_events.status_code == 200
            assert any(item["id"] == event["id"] for item in public_events.json())

            me = await client.get("/api/v1/auth/me", headers=organizer_headers)
            assert me.status_code == 200
            assert me.json()["account"]["role"] == "organizer"

            profile = await client.put("/api/v1/auth/organization", headers=organizer_headers, json={
                "name": "Northstar Studio", "website": "https://northstar.example", "description": "Community hackathons.",
            })
            assert profile.status_code == 200
            assert profile.json()["name"] == "Northstar Studio"

            person_profile = await client.put("/api/v1/auth/profile", headers=organizer_headers, json={"full_name": "Riley Park"})
            assert person_profile.status_code == 200
            assert person_profile.json()["full_name"] == "Riley Park"

            participant_access = await client.post("/api/v1/auth/login", json={
                "email": "riley@example.org", "password": "secure-test-password", "role": "participant",
            })
            assert participant_access.status_code == 200
            assert participant_access.json()["account"]["roles"] == ["organizer", "participant"]
            assert participant_access.json()["account"]["role"] == "participant"

            participant = await client.post("/api/v1/auth/register", json={
                "full_name": "Parker Participant", "email": "parker@example.org", "password": "another-secure-password",
                "role": "participant",
            })
            assert participant.status_code == 201
            participant_headers = {"Authorization": f"Bearer {participant.json()['access_token']}"}

            forbidden_event_create = await client.put("/api/v1/workspace", headers=participant_headers, json={"events": [event]})
            assert forbidden_event_create.status_code == 403

            forbidden_profile = await client.get("/api/v1/auth/organization", headers=participant_headers)
            assert forbidden_profile.status_code == 403

            saved_workspace = await client.put("/api/v1/workspace", headers=participant_headers, json={
                "registrations": [{
                    "eventId": event["id"], "name": "Parker Participant", "email": "parker@example.org",
                    "track": "Open source", "teamPreference": "Going solo", "teamName": "",
                }],
                "projectSubmissions": [{
                    "id": 4, "eventId": event["id"], "title": "Shared project", "team": "Parker",
                    "track": "Open source", "submitterEmail": "parker@example.org",
                }],
            })
            assert saved_workspace.status_code == 200
            assert (await client.get(f"/api/v1/lifecycle/teams?eventId={event['id']}", headers=participant_headers)).status_code == 200
            organizer_workspace = await client.get("/api/v1/workspace", headers=organizer_headers)
            assert organizer_workspace.status_code == 200
            assert organizer_workspace.json()["registrations"][0]["email"] == "parker@example.org"
            assert organizer_workspace.json()["projectSubmissions"][0]["title"] == "Shared project"

            team = await client.post("/api/v1/lifecycle/teams", headers=participant_headers, json={
                "eventId": event["id"], "name": "Parker's team", "track": "Open source",
            })
            assert team.status_code == 201
            joined_team = await client.post(f"/api/v1/lifecycle/teams/{team.json()['id']}/join", headers=participant_headers)
            assert joined_team.status_code == 200
            assert joined_team.json()["members"] == 1

            invited = await client.post("/api/v1/auth/organization/members", headers=organizer_headers, json={"email": "parker@example.org"})
            assert invited.status_code == 201
            member_login = await client.post("/api/v1/auth/login", json={
                "email": "parker@example.org", "password": "another-secure-password", "role": "organizer",
            })
            assert member_login.status_code == 200
            member_workspace = await client.get("/api/v1/workspace", headers={"Authorization": f"Bearer {member_login.json()['access_token']}"})
            assert member_workspace.status_code == 200
            assert member_workspace.json()["events"][0]["id"] == event["id"]

            assignment = await client.post(f"/api/v1/lifecycle/events/{event['id']}/judges", headers=organizer_headers, json={"email": "parker@example.org"})
            assert assignment.status_code == 201
            reviews = await client.get("/api/v1/lifecycle/judge-reviews", headers=participant_headers)
            assert reviews.status_code == 200
            assert reviews.json()[0]["submissionTitle"] == "Shared project"
            score = await client.put(f"/api/v1/lifecycle/judge-reviews/{event['id']}", headers=participant_headers, json={
                "submissionId": 4, "criterionScores": {"impact": 4}, "comment": "Clear community value.",
            })
            assert score.status_code == 200

            voter = await client.post("/api/v1/auth/register", json={
                "full_name": "Jordan Voter", "email": "jordan@example.org", "password": "voter-test-password-2026", "role": "participant",
            })
            assert voter.status_code == 201
            voter_headers = {"Authorization": f"Bearer {voter.json()['access_token']}"}
            vote = await client.post(f"/api/v1/lifecycle/events/{event['id']}/votes", headers=voter_headers, json={"submissionId": 4})
            assert vote.status_code == 201
            duplicate_vote = await client.post(f"/api/v1/lifecycle/events/{event['id']}/votes", headers=voter_headers, json={"submissionId": 4})
            assert duplicate_vote.status_code == 409

            normalized = await client.post(f"/api/v1/lifecycle/events/{event['id']}/normalize", headers=organizer_headers)
            assert normalized.status_code == 200
            assert normalized.json()["judgingNormalized"] is True

            owner_workspace = await client.get("/api/v1/workspace", headers=organizer_headers)
            published_workspace = owner_workspace.json()
            published_workspace["publishedEventIds"] = [event["id"]]
            published_workspace["judgeScores"] = score.json().get("judgeScores", published_workspace["judgeScores"])
            published_results = await client.put("/api/v1/workspace", headers=organizer_headers, json=published_workspace)
            assert published_results.status_code == 200
            certificates = await client.post(f"/api/v1/lifecycle/events/{event['id']}/certificates", headers=organizer_headers)
            assert certificates.status_code == 200
            assert certificates.json()[0]["recipientName"] == "Parker Participant"
            released_results = await client.get("/api/v1/workspace", headers=participant_headers)
            assert released_results.status_code == 200
            assert event["id"] in released_results.json()["publishedEventIds"]
            assert released_results.json()["projectSubmissions"][0]["score"] == 80
            assert released_results.json()["judgeScores"][0]["comment"] == "Clear community value."
            my_certificates = await client.get("/api/v1/lifecycle/certificates/me", headers=participant_headers)
            assert my_certificates.status_code == 200
            assert my_certificates.json()[0]["eventId"] == event["id"]

            verification = await client.get("/api/v1/lifecycle/certificates/verify", params={"code": my_certificates.json()[0]["verificationCode"]})
            assert verification.status_code == 200
            assert verification.json()["valid"] is True
            assert verification.json()["eventId"] == event["id"]

            archived = await client.post(f"/api/v1/lifecycle/events/{event['id']}/archive", headers=organizer_headers)
            assert archived.status_code == 200
            listed_after_archive = await client.get("/api/v1/events")
            assert all(item["id"] != event["id"] for item in listed_after_archive.json())

            login = await client.post("/api/v1/auth/login", json={
                "email": "parker@example.org", "password": "another-secure-password", "role": "organizer", "organization_name": "Parker Events",
            })
            assert login.status_code == 200
            assert login.json()["account"]["roles"] == ["participant", "organizer", "judge"]
            assert login.json()["account"]["role"] == "organizer"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def test_account_role_and_workspace_isolation() -> None:
    asyncio.run(exercise_account_flows())


async def exercise_admin_flow() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=fastapi_app), base_url="http://testserver") as client:
            admin = await client.post("/api/v1/auth/register", json={
                "full_name": "Admin User", "email": "admin@example.org", "password": "admin-pass-2026",
                "role": "admin",
            })
            assert admin.status_code == 201, admin.text
            admin_token = admin.json()["access_token"]

            listed = await client.get("/api/v1/events/admin/events", headers={"Authorization": f"Bearer {admin_token}"})
            assert listed.status_code == 200

            denied = await client.get("/api/v1/events/admin/events")
            assert denied.status_code == 401
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def test_admin_role_and_admin_events_access() -> None:
    asyncio.run(exercise_admin_flow())

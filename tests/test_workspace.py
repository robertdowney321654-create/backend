"""Workspace API tests against isolated normalized database tables."""

import asyncio
import copy
from collections.abc import AsyncIterator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.auth import get_current_account
from app.core.database import Base, get_db
from app.main import app as fastapi_app
from app.models.account import Account
import app.models  # noqa: F401


async def exercise_workspace_api() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        account = Account(
            email="organizer@example.org", full_name="Organizer", password_hash="test-hash",
            role="organizer", roles=["organizer"],
        )
        session.add(account)
        await session.commit()

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def override_account() -> Account:
        return account

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_current_account] = override_account
    try:
        transport = httpx.ASGITransport(app=fastapi_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            missing = await client.get("/api/v1/workspace")
            assert missing.status_code == 404

            payload = {
                "events": [{
                    "id": "build-for-better", "title": "Build for Better", "host": "Sparks Community",
                    "category": "Climate tech", "format": "Hybrid", "dates": "Oct 18-20, 2026",
                    "deadline": "2099-10-17T23:59:00Z", "registrationDeadline": "2099-10-17T23:59:00Z",
                    "submissionDeadline": "2099-10-20T12:00:00Z", "location": "Oakland + online",
                    "description": "Build together.", "prize": "$12,000", "participants": 1, "spots": 20,
                    "tracks": ["Climate tech"], "eligibility": "Open to all.", "color": "mint", "symbol": "B",
                    "schedule": [{"date": "Oct 18, 2026", "title": "Kickoff", "detail": "Form teams."}], "isArchived": False,
                }],
                "registrations": [{
                    "eventId": "build-for-better", "name": "Maya Chen", "email": "maya@example.org",
                    "track": "Climate tech", "teamPreference": "Looking for a team", "teamName": "",
                }],
                "projectSubmissions": [{
                    "id": 5, "eventId": "build-for-better", "title": "Canopy", "team": "Northstar",
                    "track": "Climate tech", "submitterEmail": "maya@example.org", "description": "Community forestry tool.",
                    "repositoryUrl": "", "demoUrl": "", "status": "Submitted", "score": 0, "votes": 0,
                }],
                "judgingRubric": [{"id": "impact", "label": "Impact", "weight": 100}],
                "judgeScores": [], "publishedEventIds": [], "participants": [], "teams": [], "submissions": [],
                "judgingNormalized": False, "resultsPublished": False, "certificatesIssued": 0, "archived": False,
            }
            saved = await client.put("/api/v1/workspace", json=payload)
            assert saved.status_code == 200

            loaded = await client.get("/api/v1/workspace")
            assert loaded.status_code == 200
            assert loaded.json()["events"][0]["id"] == "build-for-better"
            assert loaded.json()["registrations"][0]["email"] == "maya@example.org"
            assert loaded.json()["projectSubmissions"][0]["title"] == "Canopy"
            assert loaded.json()["judgingRubric"] == payload["judgingRubric"]
            assert loaded.json()["events"][0]["schedule"] == payload["events"][0]["schedule"]

            public_listing = await client.get("/api/v1/events")
            assert public_listing.status_code == 200
            assert next(item for item in public_listing.json() if item["id"] == "build-for-better")["title"] == "Build for Better"

            edited_payload = copy.deepcopy(payload)
            edited_payload["events"][0]["title"] = "Build for Better: Updated"
            edited_payload["events"][0]["description"] = "Updated challenge brief."
            edited = await client.put("/api/v1/workspace", json=edited_payload)
            assert edited.status_code == 200
            public_listing_after_edit = await client.get("/api/v1/events")
            updated_event = next(item for item in public_listing_after_edit.json() if item["id"] == "build-for-better")
            assert updated_event["title"] == "Build for Better: Updated"
            assert updated_event["description"] == "Updated challenge brief."

            late_registration = copy.deepcopy(payload)
            late_registration["events"][0]["registrationDeadline"] = "2000-01-01T00:00:00Z"
            late_registration["registrations"].append({
                "eventId": "build-for-better", "name": "Late Maker", "email": "late@example.org",
                "track": "Climate tech", "teamPreference": "Looking for a team", "teamName": "",
            })
            rejected_registration = await client.put("/api/v1/workspace", json=late_registration)
            assert rejected_registration.status_code == 409

            late_submission = copy.deepcopy(payload)
            late_submission["events"][0]["submissionDeadline"] = "2000-01-01T00:00:00Z"
            late_submission["projectSubmissions"].append({
                "id": 6, "eventId": "build-for-better", "title": "Late Project", "team": "Northstar",
                "track": "Climate tech", "submitterEmail": "maya@example.org", "description": "",
                "repositoryUrl": "", "demoUrl": "", "status": "Submitted", "score": 0, "votes": 0,
            })
            rejected_submission = await client.put("/api/v1/workspace", json=late_submission)
            assert rejected_submission.status_code == 409

            preflight = await client.options(
                "/api/v1/workspace",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "PUT",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)
        fastapi_app.dependency_overrides.pop(get_current_account, None)
        await engine.dispose()


def test_workspace_round_trip_and_cors() -> None:
    asyncio.run(exercise_workspace_api())
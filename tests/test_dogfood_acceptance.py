"""Exercise the official Dogfood acceptance contract on fixture-seeded SQLite."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1 import auth as auth_api
from app.core.config import Settings
from app.core.database import Base, get_db
from app.core.dogfood_seed import DOGFOOD_TOKENS, DOGFOOD_EVENT_ID, seed_dogfood_fixture
from app.main import app as fastapi_app
from app.models.event import HackathonEvent
import app.models  # noqa: F401


def _headers(role: str) -> dict[str, str]:
    token = DOGFOOD_TOKENS[role][0]
    return {"Authorization": f"Bearer {token}"}


async def exercise_dogfood_contract() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        assert await seed_dogfood_fixture(session)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    original_get_settings = auth_api.get_settings
    auth_api.get_settings = lambda: Settings(dogfood_mode=True)  # type: ignore[assignment]
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=fastapi_app),
            base_url="http://testserver",
        ) as client:
            gallery_path = f"/api/v1/events/{DOGFOOD_EVENT_ID}/submissions"
            gallery = await client.get(gallery_path)
            assert gallery.status_code == 200
            assert "Glass Signal" in gallery.text

            closed_submit = await client.post(
                gallery_path,
                headers=_headers("participant"),
                json={"title": "dogfood-late-submission-probe", "summary": "probe"},
            )
            assert 400 <= closed_submit.status_code < 500

            judge_scores_path = "/api/v1/lifecycle/judge-scores?judge=tomas.varga%40example.org"
            own_scores = await client.get(judge_scores_path, headers=_headers("judge_a"))
            assert own_scores.status_code == 200
            peer_scores = await client.get(judge_scores_path, headers=_headers("judge_b"))
            assert peer_scores.status_code == 403
            participant_scores = await client.get(judge_scores_path, headers=_headers("participant"))
            assert participant_scores.status_code == 403

            export = await client.get(
                f"/api/v1/events/{DOGFOOD_EVENT_ID}/export.csv",
                headers=_headers("organizer"),
            )
            assert export.status_code == 200
            assert "," in export.text.splitlines()[0]

            async with factory() as session:
                event = await session.get(HackathonEvent, DOGFOOD_EVENT_ID)
                assert event is not None
                event.submission_deadline = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                await session.commit()

            edited = await client.put(
                f"{gallery_path}/1",
                headers=_headers("participant"),
                json={
                    "title": "Glass Signal edited",
                    "description": "Edited before the deadline.",
                    "repositoryUrl": "https://example.org/repo/edited",
                    "demoUrl": "",
                    "track": "Security",
                },
            )
            assert edited.status_code == 200
            assert edited.json()["title"] == "Glass Signal edited"

            denied_edit = await client.put(
                f"{gallery_path}/1",
                headers=_headers("judge_a"),
                json={"title": "Unauthorized", "description": "", "repositoryUrl": "", "demoUrl": "", "track": ""},
            )
            assert denied_edit.status_code == 403

            async with factory() as session:
                event = await session.get(HackathonEvent, DOGFOOD_EVENT_ID)
                assert event is not None
                event.submission_deadline = "2026-03-01T18:00:00Z"
                await session.commit()
            late_edit = await client.put(
                f"{gallery_path}/1",
                headers=_headers("participant"),
                json={"title": "Late edit", "description": "", "repositoryUrl": "", "demoUrl": "", "track": ""},
            )
            assert late_edit.status_code == 409
    finally:
        auth_api.get_settings = original_get_settings  # type: ignore[assignment]
        fastapi_app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def test_dogfood_acceptance_contract() -> None:
    asyncio.run(exercise_dogfood_contract())
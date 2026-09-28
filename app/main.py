"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.health import router as v1_health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.events import router as events_router
from app.api.v1.lifecycle import router as lifecycle_router
from app.api.v1.workspace import router as workspace_router
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.dogfood_seed import DOGFOOD_TOKENS, seed_dogfood_fixture

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
	if settings.dogfood_mode:
		async with AsyncSessionLocal() as session:
			seeded = await seed_dogfood_fixture(session)
		print("Dogfood fixture seeded." if seeded else "Dogfood fixture already present.", flush=True)
		print("Dogfood test auth headers:", flush=True)
		for name, (token, _, _) in DOGFOOD_TOKENS.items():
			print(f"  {name}: Authorization: Bearer {token}", flush=True)
	yield


app = FastAPI(title="Sparks Hackathon Platform", version="0.2.0", lifespan=lifespan)

app.add_middleware(
	CORSMiddleware,
	allow_origins=settings.cors_origins,
	allow_methods=["GET", "POST", "PUT", "OPTIONS"],
	allow_headers=["Accept", "Authorization", "Content-Type"],
)

app.include_router(health_router)
app.include_router(v1_health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(events_router, prefix="/api/v1")
app.include_router(lifecycle_router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")

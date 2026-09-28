# Architecture

Sparks is a React/Vite frontend backed by a FastAPI service. The browser uses JSON APIs; SQLAlchemy persists application records in SQLite for local development and PostgreSQL in Docker Compose. Alembic owns schema evolution.

## Startup

The backend container applies migrations before starting Uvicorn. Compose enables `DOGFOOD_MODE`, which idempotently loads `fixtures.json` and prints the four test-only Bearer headers used by `run.py`. Those fixed identities are accepted only when Dogfood mode is enabled; normal accounts continue to use email/password sign-in and signed JWT sessions.

`docker compose up --build` starts PostgreSQL, the seeded API on port 8000, and the built frontend on port 5173. Runtime services do not call hosted APIs. The first image build requires base images and package dependencies to be available; subsequent runs can use cached images offline.

## Request boundaries

- Public event and submission gallery reads do not require authentication.
- Participant writes require participant identity, event registration where applicable, and an open event deadline.
- Project edits verify ownership and the submission cutoff in the backend.
- Judge score reads require an assigned judge and only return that judge's own rows. A request for another judge is denied server-side.
- Event CSV export requires the organizer that owns the event.

The `/api/v1/workspace` response remains as a compatibility surface for the existing UI. Core event, registration, project, rubric, and judge-score data are persisted in normalized tables.
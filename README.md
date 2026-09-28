# Sparks backend

FastAPI backend for account access, organization profiles, event discovery, registrations, teams, submissions, judging, voting, results, certificates, and event archiving.

## Requirements

- Python 3.12 or newer
- Docker Compose v2 for the containerized PostgreSQL setup

## Local development

Local development uses SQLite at `backend/sparks.db` by default.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at <http://127.0.0.1:8000>; interactive API documentation is at `/docs`. Run the tests with `python -m pytest` from this directory.

To load the official acceptance fixture locally, set `$env:DOGFOOD_MODE="true"` before starting Uvicorn. The app seeds `fixtures.json` once and prints the direct test Bearer headers. Dogfood mode is only for local acceptance testing; leave it disabled in production.

## One-command seeded portal

```powershell
docker compose up --build
```

Open <http://127.0.0.1:5174>. The backend is at <http://127.0.0.1:8001>. Compose starts PostgreSQL, runs migrations, seeds the official fixture, prints checker headers, and serves the static frontend. The fixture seed is idempotent and will not overwrite an existing `evt_01`.

These Compose defaults are for local Dogfood testing only. Before deployment, create `.env` from `.env.example`, set unique strong `JWT_SECRET_KEY` and `POSTGRES_PASSWORD` values, set `DOGFOOD_MODE=false`, and configure `CORS_ORIGINS` for the actual frontend origin. Put the services behind HTTPS and do not expose PostgreSQL publicly.

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

Database files persist in the `postgres_data` volume. Back it up regularly. The frontend's `VITE_API_BASE_URL` is a build-time value and must point to the public API origin for a deployed build.

To use PostgreSQL outside Compose, set `DATABASE_URL` to a SQLAlchemy async URL such as `postgresql+asyncpg://user:password@host:5432/sparks` and apply migrations with `alembic upgrade head`.

## API overview

- `GET /health` and `GET /api/v1/health`: health checks.
- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`: account and session operations.
- `PUT /api/v1/auth/profile`, `GET/PUT /api/v1/auth/organization`, `GET/POST /api/v1/auth/organization/members`: profile and organization membership.
- `GET /api/v1/events` and `GET /api/v1/events/{event_id}/submissions`: public event and project listings.
- `GET/PUT /api/v1/workspace`: authenticated workspace compatibility API. Event, registration, submission, rubric, and score records are stored in normalized database tables; the API response retains the existing workspace shape for the frontend.
- `/api/v1/lifecycle`: team creation and joining, judge assignment and reviews, score normalization, community voting, certificate issuance and retrieval, and event archiving.
- `POST /api/v1/events/{event_id}/submissions` and `PUT /api/v1/events/{event_id}/submissions/{submission_id}`: participant submission and pre-deadline edits.
- `GET /api/v1/lifecycle/judge-scores?judge={email}`: judge-only, self-scoped score export used by the Dogfood acceptance checker.
- `GET /api/v1/events/{event_id}/export.csv`: organizer-only event results export.

Migration `0007_normalized_event_records` imports existing account-owned event snapshots into normalized tables and preserves the old snapshot for compatibility with auxiliary workspace fields and existing lifecycle handlers. Keep a database backup before applying migrations in production.

## Dogfood acceptance checks

With the Compose portal running, execute `python run.py .dogfood.toml` from this directory. The official checker uses the configured routes and direct test headers; it never submits the human login form. To regenerate the committed report, run `python run.py .dogfood.toml > acceptance-report.txt`.

## Current limitations

This is an early self-hosted MVP. The seven Dogfood T1/T2 acceptance checks pass. The platform now includes draft submissions, invite-link team formation, project-gallery search/filter, a platform admin view, public certificate verification, and community project comments. Some broader tier items remain absent: email verification and password recovery, configurable team-size and voting policies, randomized voting ballots, and a fully normalized replacement for the compatibility workspace API. The Dogfood fixture is seeded separately from the human event directory. Account deletion and participant data export workflows are not implemented.

This project is licensed under the MIT License; see [`LICENSE`](LICENSE).
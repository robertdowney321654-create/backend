# Data Model

## Core records

- `accounts` stores human users and their roles; organizations are separate profiles.
- `hackathon_events` stores event metadata, ownership, deadlines, publication state, and archive state.
- `event_registrations` associates an event with a participant account/email, selected track, and team.
- `teams` and `team_members` represent event teams.
- `project_submissions` stores each team's project, submitter, repository/demo links, status, score, and legacy vote count.
- `event_rubric_criteria` stores criterion weights per event.
- `judge_score_records` stores criterion scores and comments per event, project, and judge account.
- `event_judges`, `community_votes`, and `certificates` record assignments, votes, and issued certificates.

The Dogfood fixture uses string IDs. The loader preserves event, team, track, judge, and project identity in the seeded relationships; the existing submission table uses an integer internal project key derived from the numeric suffix of `prj_NN`, scoped by event. Original fixture JSON remains bundled as `fixtures.json` for the acceptance runner.

## Import and export

At Dogfood-mode startup, `app/core/dogfood_seed.py` reads `fixtures.json` and creates fixture rows only when `evt_01` is absent. It does not overwrite existing event edits on restart. Migration `0007_normalized_event_records` imports previous account-owned workspace snapshots into the normalized tables.

The authenticated organizer endpoint `/api/v1/events/{event_id}/export.csv` exports project, track, team, score, and vote columns. Alembic migrations are the supported schema upgrade path; back up the database before deploying a migration.
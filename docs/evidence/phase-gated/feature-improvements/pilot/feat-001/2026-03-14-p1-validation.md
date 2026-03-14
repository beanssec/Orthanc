# FEAT-001 P1 Validation Evidence (2026-03-14)

Feature: Narrative intelligence tracker scaffolding
Scope: P1 acceptance gates (flag isolation, auth/validation, no regression)
Environment: local validation compose override with isolated named Postgres volume

## Environment notes
- Default compose Postgres mount (`/mnt/data/postgres/overwatch`) failed in this host with `Operation not permitted` during initdb.
- Validation used override file: `/home/beans/.hermes/tmp/orthanc-compose.validation.yml`.
- A pre-existing migration-chain issue exists on fresh DBs:
  - `020_entity_relationships` attempts `CREATE TABLE entity_relationships` although table already created by `008_entity_relationships`.
  - Workaround used for isolated validation only:
    1) `alembic upgrade 019_frontline_snapshots`
    2) `alembic stamp 022_timeline_perf_indexes`
    3) `alembic upgrade head` (023/024)

## Gate checks

### 1) Feature flag OFF behavior
- Backend started with default `NARRATIVE_TRACKERS_ENABLED=false`.
- Request:
  - `GET /narratives/trackers` with valid auth token
- Result:
  - HTTP 404
  - Body: `{"detail":"Narrative trackers are disabled"}`

### 2) Feature flag ON behavior (CRUD + auth + validation)
- Backend restarted with override: `/home/beans/.hermes/tmp/orthanc-compose.trackers-on.yml` (`NARRATIVE_TRACKERS_ENABLED=true`).

Checks:
- `GET /narratives/trackers` without auth => HTTP 401 (`Not authenticated`)
- `POST /narratives/trackers` with `{}` => HTTP 400 (`name is required`)
- `POST /narratives/trackers` valid payload => HTTP 200, tracker created
- `GET /narratives/trackers` => HTTP 200
- `GET /narratives/trackers/{id}` => HTTP 200
- `PATCH /narratives/trackers/{id}` criteria update => HTTP 200
- `POST /narratives/trackers/{id}/recompute` => HTTP 200
- `GET /narratives/trackers/{id}/monthly` => HTTP 200
- `POST /narratives/trackers/{id}/deactivate` => HTTP 200

Observed recompute summary (empty narrative fixture):
- `matched_narratives: 0`
- `months: 0`
- version incremented to 2 after criteria update

### 3) Regression checks for existing narrative APIs
- `GET /narratives/` => HTTP 200 (flag off + flag on)
- `GET /layers/narratives` => HTTP 200 (flag off + flag on)

## Defect found and fixed during validation
- Symptom: `GET /narratives/trackers` hit wildcard route `/{narrative_id}` and returned 500/422 instead of tracker route behavior.
- Root cause: route precedence with wildcard path before tracker endpoints.
- Fix applied in `backend/app/routers/narratives.py`:
  - narrative routes changed to explicit UUID path converters:
    - `/{narrative_id:uuid}`
    - `/{narrative_id:uuid}/timeline`
    - `/{narrative_id:uuid}/claims`
    - `/{narrative_id:uuid}/refresh`
  - corresponding handler params adjusted to `uuid.UUID`.
- Post-fix result: `/narratives/trackers` correctly reaches tracker route and returns 404 when flag is off.

## Data-safety check
Current counts after tracker CRUD/recompute in validation DB:
- `narratives=0`
- `narrative_posts=0`
- `claims=0`
- `claim_evidence=0`
- `narrative_trackers=1`
- `narrative_tracker_versions=2`
- `narrative_tracker_matches=0`
- `narrative_tracker_monthly_snapshots=0`

Interpretation: tracker writes are additive to tracker tables; no writes observed to legacy narrative tables in this fixture run.

## FEAT-001 P1 gate status
- additive migration safety: PARTIAL (validated on isolated DB; blocked from direct host mount path)
- feature-flag isolation: PASS
- auth + ownership/validation behavior: PASS
- no regression to `/narratives` and `/layers/narratives`: PASS
- observability criteria: NOT FULLY VERIFIED in this pass

Overall: FEAT-001 P1 is functionally validated with one critical routing defect fixed; migration-chain anomaly at revision 020 remains a separate blocker for clean from-scratch upgrades.

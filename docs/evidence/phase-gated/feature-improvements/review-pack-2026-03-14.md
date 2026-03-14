# Orthanc Change Review Pack
Date: 2026-03-14
Repo: /home/beans/projects/Orthanc
Branch: main (working tree only; not committed yet)

## 1) Snapshot

Tracked files modified (10):
- backend/app/config.py
- backend/app/models/__init__.py
- backend/app/models/entity.py
- backend/app/models/narrative.py
- backend/app/routers/entities.py
- backend/app/routers/narratives.py
- backend/app/services/entity_extractor.py
- frontend/src/components/entities/EntitiesView.tsx
- frontend/src/components/narratives/NarrativesView.tsx
- frontend/src/components/narratives/types.ts

Untracked files:
- FEAT-001_P1_PILOT_SETUP.md
- backend/alembic/versions/023_narrative_trackers.py
- backend/alembic/versions/024_entity_aliases_and_overrides.py
- docs/ (includes new validation evidence)

Diff stat:
- 10 files changed
- 991 insertions(+), 28 deletions(-)

## 2) FEAT-001: Narrative trackers (pilot)

### Backend/config/model changes
- Added feature flag in `backend/app/config.py`:
  - `NARRATIVE_TRACKERS_ENABLED: bool = False`

- Added new tracker models in `backend/app/models/narrative.py`:
  - `NarrativeTracker`
  - `NarrativeTrackerVersion`
  - `NarrativeTrackerMatch`
  - `NarrativeTrackerMonthlySnapshot`

- Added migration `backend/alembic/versions/023_narrative_trackers.py`:
  - creates all tracker tables + indexes + constraints

### API changes (`backend/app/routers/narratives.py`)
- Route hardening/fix:
  - switched wildcard narrative routes to UUID converters to avoid shadowing:
    - `/{narrative_id:uuid}`
    - `/{narrative_id:uuid}/timeline`
    - `/{narrative_id:uuid}/claims`
    - `/{narrative_id:uuid}/refresh`

- Added feature-gated tracker APIs:
  - `GET /narratives/trackers`
  - `POST /narratives/trackers`
  - `GET /narratives/trackers/{tracker_id}`
  - `PATCH /narratives/trackers/{tracker_id}`
  - `POST /narratives/trackers/{tracker_id}/deactivate`
  - `GET /narratives/trackers/{tracker_id}/monthly`
  - `POST /narratives/trackers/{tracker_id}/recompute`

- Added internal helpers:
  - `_ensure_trackers_enabled()` (404 when disabled)
  - `_normalize_criteria()`
  - `_get_latest_tracker_version()`
  - `_recompute_tracker()` including month-bucket snapshot rollups

### Frontend changes (trackers UI)
- `frontend/src/components/narratives/types.ts`
  - added `NarrativeTracker`
  - added `NarrativeTrackerMonthlyPoint`

- `frontend/src/components/narratives/NarrativesView.tsx`
  - added tracker state management
  - added tracker fetch/create/recompute interactions
  - added tracker monthly timeline panel in UI
  - handles 404 from trackers endpoint as flag-disabled behavior

### Evidence
- `docs/evidence/phase-gated/feature-improvements/pilot/feat-001/2026-03-14-p1-validation.md`

## 3) FEAT-002: Entity alias normalization + type overrides

### Model/migration changes
- `backend/app/models/entity.py`
  - added `EntityAlias`
  - added `EntityTypeOverride`

- `backend/alembic/versions/024_entity_aliases_and_overrides.py`
  - creates `entity_aliases`
  - creates `entity_type_overrides`

### API changes (`backend/app/routers/entities.py`)
- Updated list endpoint:
  - `GET /entities` now supports `resolved=true` to apply type overrides in response

- Added normalization endpoints:
  - `GET /entities/normalization/summary`
  - `POST /entities/normalization/rebuild`
  - `POST /entities/{entity_id}/aliases`
  - `POST /entities/{entity_id}/type-override`

- Added heuristic/support constants for type override inference:
  - `VALID_ENTITY_TYPES`
  - `_ORG_SUFFIX_HINTS`

### Extractor normalization enhancement
- `backend/app/services/entity_extractor.py`
  - improved canonicalization (punctuation + spacing normalization)
  - added high-confidence geo alias mapping (US/USA/UAE/UK variants)

### Evidence
- `docs/evidence/phase-gated/feature-improvements/pilot/feat-002/2026-03-14-validation.md`

## 4) FEAT-003 (in progress)

### Frontend entity ID handling cleanup
- `frontend/src/components/entities/EntitiesView.tsx`
  - `Entity.id` updated from `number` -> `string`
  - selected route/query id handling updated from `number|null` -> `string|null`
  - removes numeric parse assumptions (`parseInt`) for UUID-safe navigation

Status: in progress; not yet closed with full validation evidence.

## 5) Additional notes in working tree
- `FEAT-001_P1_PILOT_SETUP.md` is present as planning/spec package context doc.

## 6) How to inspect locally

From `/home/beans/projects/Orthanc`:
- `git status --short`
- `git diff --stat`
- `git diff backend/app/routers/narratives.py`
- `git diff backend/app/routers/entities.py`
- `git diff frontend/src/components/narratives/NarrativesView.tsx`
- `git diff frontend/src/components/entities/EntitiesView.tsx`
- `git diff -- backend/alembic/versions/023_narrative_trackers.py`
- `git diff -- backend/alembic/versions/024_entity_aliases_and_overrides.py`

## 7) Proposed commit slicing (recommended)
- Commit A (FEAT-001 backend + migration + narratives UI/types)
- Commit B (FEAT-002 backend + migration + extractor)
- Commit C (FEAT-003 EntitiesView UUID-safe frontend adjustments)
- Commit D (evidence/docs)

This keeps review and rollback clean by feature boundary.

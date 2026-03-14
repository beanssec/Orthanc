# FEAT-002 Validation Evidence (2026-03-14)

Feature: Entity normalization + taxonomy quality
Scope: alias normalization, type override behavior, resolved listing
Environment: same isolated validation stack used for FEAT-001

## Fixture setup
Inserted entity fixtures into `entities`:
- United States (GPE, canonical_name=unitedstates)
- U.S. (GPE, canonical_name=unitedstates)
- US (GPE, canonical_name=unitedstates)
- Iran Ministry of Defense (PERSON, canonical_name=iranministryofdefense)

## API validation

### 1) Summary before rebuild
- `GET /entities/normalization/summary`
- HTTP 200
- Body:
  - `alias_count=0`
  - `override_count=0`

### 2) Rebuild normalization
- `POST /entities/normalization/rebuild`
- HTTP 200
- Body:
  - `entities_scanned=4`
  - `aliases_created=1`
  - `overrides_created=1`

### 3) Summary after rebuild
- `GET /entities/normalization/summary`
- HTTP 200
- Body confirms generated artifacts:
  - `alias_count=1`
  - `override_count=1`
  - recent alias includes `United States` normalization

### 4) Resolved type list honors overrides
- `GET /entities/?resolved=true&type=ORG`
- HTTP 200
- Response includes `Iran Ministry of Defense` as `type=ORG` (override applied)

### 5) Manual alias endpoint
- `POST /entities/{united_states_id}/aliases` with `alias_text="U S A"`
- HTTP 200
- Result: `status=exists` (normalized alias already represented)

### 6) Manual type override endpoint
- `POST /entities/{iran_ministry_id}/type-override` with `override_type="ORG"`
- HTTP 200
- Result: `status=updated`

## FEAT-002 gate status (current pass)
- alias normalization pipeline: PASS
- taxonomy override storage/application: PASS
- resolved view behavior: PASS
- manual endpoint contracts (auth + validation baseline): PASS

Notes:
- Validation executed on isolated local fixture DB; production-like dataset scale and perf profiling remain pending.

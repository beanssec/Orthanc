# FEAT-001 P1 Pilot Setup Package

Feature: Orthanc/Overwatch Narrative Intelligence Overhaul
Scope: operator-defined narrative tracking over multi-month windows
Status: planning/spec only (no code changes)
Date: 2026-03-13

## 1) Executive summary

Orthanc already auto-generates narratives from posts, computes stance/evidence/consensus, and exposes narrative list/detail/bias/map endpoints. What is missing for FEAT-001 is persistent operator-defined tracking: analysts cannot define a narrative hypothesis, track it over months, version the definition, or produce longitudinal trend evidence.

This package defines a phase-gated implementation that is additive-only (no destructive DB operations), preserves existing narrative data, and supports service-scoped deploys (backend and frontend can be rolled independently).

Recommended pilot:
- P1: data and API scaffolding for tracker definitions and monthly snapshots
- P2: minimal usable slice (create tracker, match to existing narratives, see monthly trend)
- P3: hardening (automation, auditability, drift controls, operational SLOs)


## 2) Current-state map (models, endpoints, UI)

### Backend data model (narrative-related)

Primary files:
- backend/app/models/narrative.py
- backend/alembic/versions/017_narratives.py

Existing tables and purpose:
- narratives
  - system-generated cluster object (title/summary/status/first_seen/last_updated/post_count/source_count/divergence_score/evidence_score/consensus/topic_keywords)
- narrative_posts
  - joins posts to narrative + stance fields
- claims
  - extracted verifiable claims per narrative
- claim_evidence
  - corroboration rows per claim
- source_groups / source_group_members
  - source grouping for bias/divergence views
- source_bias_profiles
  - periodic bias/reliability profile snapshots
- post_embeddings
  - embeddings used by clustering

Important current constraints:
- No operator-authored tracker entity exists.
- No monthly or longitudinal tracker snapshot model exists.
- Existing downgrade for 017 is destructive; FEAT-001 must use forward-only operational rollout and avoid any data-destructive actions.

### Backend services and workflows

Primary files:
- backend/app/services/narrative_engine.py
- backend/app/services/narrative_analyzer.py
- backend/app/services/stance_classifier.py
- backend/app/services/source_group_seeder.py
- backend/app/main.py

Current behavior:
- narrative_engine (10 min cycle): embed posts, assign to active narratives, create new narratives, update stats, mark stale.
- narrative_analyzer (15 min cycle): classify unclassified stances, link evidence, recompute divergence/evidence/consensus.
- stance_classifier: AI mode with keyword fallback; also claim extraction.
- startup in main.py launches both engine and analyzer loops.

Observed gaps for FEAT-001:
- no tracker loop or backfill worker
- no versioned definition logic
- no longitudinal aggregation pipeline (month buckets)
- refresh endpoint is placeholder only (/narratives/{id}/refresh)

### Backend API surface (narrative-related)

Primary file:
- backend/app/routers/narratives.py

Existing endpoints:
- GET /narratives/
- GET /narratives/trending
- GET /narratives/{id}
- GET /narratives/{id}/timeline
- GET /narratives/{id}/claims
- POST /narratives/{id}/refresh (placeholder)
- source group endpoints:
  - GET/POST /narratives/source-groups/
  - POST /narratives/source-groups/{group_id}/members
  - DELETE /narratives/source-groups/{group_id}/members/{source_id}
- bias endpoints:
  - GET /narratives/bias/profiles
  - GET /narratives/bias/compass

Geo integration:
- GET /layers/narratives (claims with lat/lng for map)

Gap:
- no CRUD for operator-defined narrative trackers
- no endpoint for multi-month tracker trends
- no backfill/recompute job management endpoints

### Frontend narrative UX

Primary files:
- frontend/src/components/narratives/NarrativesView.tsx
- frontend/src/components/narratives/NarrativeDetail.tsx
- frontend/src/components/narratives/NarrativeCard.tsx
- frontend/src/components/narratives/BiasCompass.tsx
- frontend/src/components/narratives/types.ts
- frontend/src/components/dashboard/DashboardView.tsx
- frontend/src/components/map/MapView.tsx

Current UI capabilities:
- narrative list filtered by status
- narrative detail tabs (overview, stances, claims, timeline)
- bias compass panel
- dashboard “trending narratives” card
- map layer for geolocated claims

Gap:
- no tracker objects in UI
- no ability to define narrative criteria/hypothesis
- no monthly trend chart tied to operator definitions
- no version history or ownership/audit flow


## 3) FEAT-001 target capability (what will exist)

Operator can:
1) define a narrative tracker (name, objective, criteria, watch window),
2) activate/deactivate it,
3) see which narratives matched over time,
4) view month-over-month trend snapshots for the tracker,
5) revise tracker definition with version history (non-destructive).

System must:
- keep existing narrative generation intact,
- add tracker layer as additive read/compute over existing narrative data,
- preserve historical tracker outputs even if definitions change.


## 4) Phase-gated delivery plan

## P1 (pilot setup foundation)

Goal: introduce safe scaffolding with no behavior change to existing narrative engine outputs.

Deliverables:
1. Additive DB schema (new tables only)
   - narrative_trackers
   - narrative_tracker_versions
   - narrative_tracker_matches
   - narrative_tracker_monthly_snapshots
2. Backend API skeleton (auth-protected)
   - create/list/get/update/deactivate tracker
   - get tracker monthly timeline
   - trigger recompute/backfill (queued, idempotent)
3. Feature flag
   - NARRATIVE_TRACKERS_ENABLED=false by default
4. Observability scaffolding
   - structured logs with tracker_id, version_id, run_id
   - basic metrics counters/timers

Out of scope in P1:
- frontend production UX
- advanced ranking algorithms
- automatic alerting

P1 acceptance (must pass):
- additive migration applies with zero row loss in existing narrative tables
- all new endpoints return 404 or feature-disabled response when flag off
- when flag on, tracker CRUD works with auth and validation
- no regression to existing /narratives and /layers/narratives behavior

## P2 (minimal pilot slice)

Goal: smallest end-to-end analyst workflow.

Deliverables:
1. Matching logic v1
   - keyword + optional topic keyword overlap + divergence/evidence threshold filters
   - daily job computes narrative_tracker_matches
2. Monthly rollup
   - compute and persist month buckets in narrative_tracker_monthly_snapshots
3. Minimal frontend
   - tracker list + create/edit form
   - tracker detail: matched narratives list + monthly trend chart
   - quick action from NarrativeDetail: “Track this narrative pattern” (prefill)
4. Service-scoped deployment path
   - backend can deploy first; frontend can follow later without breaking existing views

P2 acceptance (must pass):
- analyst can create one tracker and see non-empty monthly trend data on seeded fixture
- monthly snapshots remain stable and queryable after tracker definition edits (versioned)
- trend endpoint p95 < 500 ms for 12-month window on pilot dataset
- no destructive mutations to narratives/claims/narrative_posts

## P3 (hardening and scale)

Goal: operational reliability for multi-month production use.

Deliverables:
- backfill job controls (pause/resume/retry/status)
- audit log for tracker definition changes and manual runs
- drift controls (definition version pinning per snapshot)
- SLOs, alerting, and runbooks
- optional export (CSV/JSON) for external reporting

P3 acceptance:
- 3-month soak with no data corruption incidents
- backfill/recompute idempotency proven in repeated runs
- rollback drill validated in staging


## 5) Proposed schema changes (additive only)

All new tables should be created via a new Alembic revision after 022. No existing table drops/renames.

1) narrative_trackers
- id (uuid pk)
- owner_user_id (uuid fk users.id)
- name (text, unique per owner)
- objective (text)
- status (active|paused|archived)
- current_version (int)
- created_at, updated_at

2) narrative_tracker_versions
- id (uuid pk)
- tracker_id (fk narrative_trackers.id)
- version (int)
- definition_json (jsonb)  // filters, keywords, source groups, score thresholds
- change_note (text)
- created_by (uuid fk users.id)
- created_at
- unique(tracker_id, version)

3) narrative_tracker_matches
- id (uuid pk)
- tracker_id (fk)
- tracker_version (int)
- narrative_id (fk narratives.id)
- match_score (float)
- matched_at (timestamptz)
- first_seen_at (timestamptz)
- last_seen_at (timestamptz)
- match_reason_json (jsonb)
- unique(tracker_id, tracker_version, narrative_id, matched_at_date_bucket)

4) narrative_tracker_monthly_snapshots
- id (uuid pk)
- tracker_id (fk)
- tracker_version (int)
- month_start (date)
- narratives_matched (int)
- posts_total (int)
- avg_divergence (float)
- avg_evidence (float)
- consensus_breakdown (jsonb)
- generated_at (timestamptz)
- unique(tracker_id, tracker_version, month_start)

Indexes:
- tracker_id + month_start on monthly snapshots
- tracker_id + matched_at on matches
- narrative_id on matches (reverse lookup)


## 6) Proposed API changes

Namespace recommendation: /narrative-trackers

P1 APIs:
- POST /narrative-trackers
- GET /narrative-trackers
- GET /narrative-trackers/{tracker_id}
- PATCH /narrative-trackers/{tracker_id}
- POST /narrative-trackers/{tracker_id}/versions
- POST /narrative-trackers/{tracker_id}/status
- POST /narrative-trackers/{tracker_id}/recompute
- GET /narrative-trackers/{tracker_id}/jobs/{job_id}

P2 APIs:
- GET /narrative-trackers/{tracker_id}/matches?from=&to=&limit=&offset=
- GET /narrative-trackers/{tracker_id}/timeline?bucket=month&from=&to=
- GET /narrative-trackers/{tracker_id}/summary

API design notes:
- strict auth via existing get_current_user
- per-owner access control
- all recompute/backfill operations idempotent using request_id/run_id
- timeline endpoint returns dense month series (including zero buckets)


## 7) Proposed UI changes

P1 (hidden/admin or flag-only):
- no required user-facing changes
- optional dev-only route for tracker API smoke tests

P2 minimal UX:
1. Narratives page:
   - add “Trackers” tab/panel alongside existing list/detail flow
2. Tracker create/edit modal:
   - fields: name, objective, keywords, source group filters, divergence/evidence thresholds
3. Tracker detail panel:
   - monthly trend bars (12 months)
   - matched narratives table (title, match_score, last_updated, consensus)
4. Narrative detail quick action:
   - button “Create tracker from this narrative” pre-fills keywords/topic/thresholds

Non-goal for pilot:
- full dashboard integration and map overlays for trackers (can be P3+)


## 8) Minimal pilot slice definition for P2

“Single-operator, single-tracker, 12-month trend” scenario:
- Operator creates one tracker with 3-10 keywords and one threshold rule.
- System computes matches against existing narratives.
- System stores and returns 12 monthly snapshots.
- Operator can edit definition once (new version), preserving old month series tied to prior version.

Exit criteria for pilot success:
- Operator can explain month-over-month narrative movement from tracker timeline.
- Data provenance is auditable (which tracker version produced each month value).
- No regressions to baseline narrative views and APIs.


## 9) Acceptance rubric (P1/P2/P3)

Scoring model per criterion:
- 0 = fail
- 1 = partial
- 2 = pass

Minimum release gate:
- P1 >= 85% of max and all “critical” criteria must be 2
- P2 >= 90% of max and all “critical” criteria must be 2
- P3 >= 90% of max and all “critical” criteria must be 2

P1 criteria:
- [critical] additive migration safety (no data loss)
- [critical] feature-flag isolation
- [critical] auth + ownership enforcement
- endpoint contract correctness (validation/errors)
- basic observability emitted
- service restart without tracker side effects

P2 criteria:
- [critical] end-to-end create→match→timeline workflow
- [critical] versioned definition integrity
- [critical] monthly aggregation accuracy on fixture
- UI usability for core workflow
- query performance for 12-month range
- no narrative pipeline regression

P3 criteria:
- [critical] backfill idempotency and recovery
- [critical] rollback drill success
- [critical] audit trail completeness
- long-run stability/SLO adherence
- operator runbook completeness


## 10) Test plan and evidence artifacts

P1 test plan:
- DB migration test
  - run alembic upgrade on production-like snapshot clone
  - validate row counts unchanged for narratives, narrative_posts, claims, claim_evidence
- API contract tests
  - CRUD + validation + auth boundary tests
- flag-off regression test
  - ensure existing routes unchanged

P1 evidence artifacts:
- migration execution log
- before/after row-count report
- OpenAPI diff for added endpoints
- API test report

P2 test plan:
- matching accuracy test with deterministic fixture set
- monthly rollup correctness test (known expected month buckets)
- UI integration test (create tracker, view timeline)
- performance test for timeline and matches endpoints

P2 evidence artifacts:
- fixture dataset manifest
- expected-vs-actual snapshot comparison
- UI screenshots/video capture
- latency benchmark output

P3 test plan:
- repeated recompute/backfill idempotency test
- failure-injection test (job interruption/restart)
- rollback rehearsal (backend-only and frontend-only)

P3 evidence artifacts:
- runbook and incident drill notes
- rollback rehearsal logs
- soak test summary metrics


## 11) Rollback plan (service-scoped, non-destructive)

Principles:
- rollback by disabling feature and/or reverting service image
- do not drop new tables during rollback
- preserve all tracker data for forward re-enable

Procedure:
1) Immediate mitigation
- set NARRATIVE_TRACKERS_ENABLED=false
- restart backend service only
- existing narrative endpoints continue unaffected

2) Backend rollback
- deploy previous backend image/tag
- keep DB at latest revision (forward-compatible contract required)

3) Frontend rollback
- if UI issue only, redeploy previous frontend image
- backend tracker endpoints may remain available but unused

4) Data safety checks after rollback
- verify existing /narratives and /layers/narratives health
- verify no row churn in legacy narrative tables
- preserve tracker tables untouched


## 12) Risks and mitigations

Risk: tracker matching quality too noisy initially
- Mitigation: explicit versioned definitions + match_reason_json for transparency

Risk: long-window queries become slow
- Mitigation: precomputed monthly snapshots + index strategy

Risk: accidental coupling with core narrative generation loops
- Mitigation: separate tracker worker/job path; no writes to narratives table required

Risk: source identity inconsistencies can reduce grouping fidelity
- Mitigation: in tracker logic, key on stable narrative ids and avoid assuming perfect source mapping


## 13) Implementation handoff checklist

- [ ] approve schema and endpoint contracts
- [ ] define feature flags and default values
- [ ] draft Alembic revision (additive only)
- [ ] add backend router/service stubs behind flag
- [ ] prepare fixture dataset for P2 pilot
- [ ] define operator pilot cohort and success review date

End of FEAT-001 P1 pilot setup package.

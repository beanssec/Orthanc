# Sprint Plan — Post-MVP Development

**Status:** Draft  
**Created:** 2026-03-07  
**Sprints completed:** 1–16 (core platform)

---

## Sprint 17 — LLM Provider Framework

**Goal:** Decouple all AI operations from OpenRouter. Support multiple providers, model routing by task, and self-hosted models (Ollama, vLLM, llama.cpp server, LM Studio).

### Phase 1: Model Router Service
- [ ] Create `backend/app/services/model_router.py`
  - Provider abstraction: `OpenRouterProvider`, `OllamaProvider`, `OpenAICompatibleProvider`
  - All providers implement common interface: `chat()`, `embed()`, `classify()`
  - Config-driven: map task → provider + model in credentials/settings
  - Fallback chains: try preferred model, fall back to cheaper/local on failure
- [ ] Task categories with default model assignments:
  | Task | Default (Cloud) | Cheap Alternative | Self-Hosted |
  |------|-----------------|-------------------|-------------|
  | Intelligence briefs | claude-sonnet-4 | grok-3-mini | llama-3.1-70b |
  | Stance classification | grok-3-mini | gemini-2.0-flash | mistral-7b |
  | Translation | grok-3-mini | gemini-2.0-flash | any |
  | Embeddings | text-embedding-3-small | — | nomic-embed-text |
  | Narrative summarisation | grok-3-mini | gemini-2.0-flash | llama-3.1-8b |
  | Entity enrichment | grok-3-mini | gemini-2.0-flash | phi-3 |
  | Image analysis | gpt-4o | — | llava |

### Phase 2: Ollama Integration
- [ ] `OllamaProvider` — HTTP client for Ollama REST API (`/api/generate`, `/api/chat`, `/api/embeddings`)
- [ ] Auto-detect available models via `GET /api/tags`
- [ ] Support both local Ollama and remote (Tailscale-accessible) Ollama instances
- [ ] Connection pooling + timeout handling (local models can be slow on first load)
- [ ] Credential type: `ollama` — stores base URL (default `http://localhost:11434`)

### Phase 3: OpenAI-Compatible Provider
- [ ] Supports any server implementing OpenAI chat completions API (`/v1/chat/completions`)
- [ ] Covers: vLLM, llama.cpp server, text-generation-webui, LM Studio, LocalAI, Aphrodite
- [ ] Credential type: `openai_compatible` — stores base URL + optional API key
- [ ] Model listing via `/v1/models` endpoint

### Phase 4: Frontend Model Settings
- [ ] Settings → Models page
  - List configured providers (OpenRouter, Ollama, OpenAI-compatible)
  - Test connection button per provider
  - Task-to-model assignment grid (dropdown per task)
  - Model cost/speed indicators
  - "Available models" auto-populated from provider APIs
- [ ] Per-brief model selector uses full model list from all providers
- [ ] Display token usage / cost estimates on brief generation

### Phase 5: Cost Tracking
- [ ] `llm_usage` table — log every LLM call (provider, model, task, tokens_in, tokens_out, latency_ms, cost_usd)
- [ ] Dashboard widget: LLM usage summary (calls/day, tokens/day, estimated cost)
- [ ] Settings → Models page: usage breakdown by task and model

---

## Sprint 18 — Bug Fixes & Polish

**Goal:** Fix all known bugs and rough edges from Sprints 1–16.

### Phase 1: Collector Fixes
- [ ] Add `last_polled` update to: telegram, reddit, discord, shodan, acled, bluesky, mastodon, firms, flights, youtube collectors
- [ ] Fix fusion scan UUID string error (`asyncpg.DataError: sized iterable expected, got str`)
- [ ] Fix Post.source_id inconsistency — some are UUIDs, some are URLs/names. Normalise to UUID FK where possible, add migration
- [ ] Auto-disable sources after N consecutive failures (configurable, default 5)
- [ ] Source health endpoint: `GET /sources/health` — returns per-source status, last_polled, error_count, last_error

### Phase 2: Narrative Engine Improvements
- [ ] AI-generated narrative titles (use cheapest available model, currently "word frequency" is bad)
- [ ] Narrative merging — detect when two narratives are about the same topic and merge
- [ ] Narrative lifecycle: auto-resolve stale narratives after configurable TTL (default 48h)
- [ ] Divergence score recalculation: weight by source reliability, not just Western vs Russian

### Phase 3: Frontend Polish
- [ ] Dashboard drill-downs:
  - Click velocity chart bar → feed filtered to that hour
  - Click alert row → jump to matching posts
  - Click activity feed item → navigate to relevant view
- [ ] Source Health: compact horizontal strip instead of full card
- [ ] Feed: infinite scroll instead of pagination buttons
- [ ] Map: layer panel redesign — collapsible categories, search
- [ ] Loading skeletons for all views (currently shows "Loading..." text)
- [ ] Error boundaries: catch component crashes without white-screening

### Phase 4: Backend Hardening
- [ ] Docker healthcheck for backend container (`/health` endpoint)
- [ ] Graceful shutdown: cancel all background tasks on SIGTERM
- [ ] Rate limiting on auth endpoints (prevent brute force)
- [ ] Request logging middleware (structured JSON logs)
- [ ] Database connection pool tuning (currently default)

---

## Sprint 19 — Frontline History & Playback

**Goal:** Store daily conflict frontline snapshots and enable historical playback on the map.

### Phase 1: Snapshot Storage
- [ ] Migration: `frontline_snapshots` table (date, source, geojson, hash)
- [ ] Daily scheduled task: fetch DeepState frontlines, store if changed
- [ ] Dedup by geometry hash (don't store if identical to previous day)
- [ ] Retain at least 90 days of history

### Phase 2: Map Playback UI
- [ ] Date slider control on map (when Frontlines layer is active)
- [ ] Playback controls: play/pause, speed selector (1d/step, 7d/step)
- [ ] Diff visualisation: highlight areas where frontlines moved (red = lost, green = gained)
- [ ] Date label overlay on map during playback

### Phase 3: Frontline Analytics
- [ ] Territory change statistics per day/week
- [ ] OQL target: `frontlines:` — query by date range, region
- [ ] Timeline chart: frontline movement over time (area gained/lost)

---

## Sprint 20 — Entity Relationship Graph

**Goal:** Build a visual network graph showing relationships between entities based on co-occurrence.

### Phase 1: Co-occurrence Engine
- [ ] Background task: compute entity co-occurrence matrix (entities mentioned in same post)
- [ ] Store in `entity_relationships` table (entity_a, entity_b, weight, last_seen)
- [ ] Incremental updates (process new posts only)
- [ ] Configurable minimum co-occurrence threshold (default 3)

### Phase 2: Graph Visualisation
- [ ] Force-directed graph (SVG, no external libraries)
- [ ] Node size = mention count, edge thickness = co-occurrence weight
- [ ] Node colour by entity type (PER=blue, ORG=green, GPE=amber)
- [ ] Click node → show entity detail panel
- [ ] Filter: entity type, minimum connections, time range
- [ ] Search: highlight and centre on a specific entity
- [ ] Cluster detection: visually group tightly-connected entities

### Phase 3: Graph in Context
- [ ] Entity detail view: "Related entities" graph for a single entity
- [ ] Case detail: graph of all entities in a case
- [ ] OQL: `entities: | graph` pipe renders co-occurrence network

---

## Sprint 21 — Scheduled Briefs & Delivery

**Goal:** Auto-generate intelligence briefs on a schedule and deliver via Telegram, email, or webhook.

### Phase 1: Brief Scheduler
- [ ] Migration: `scheduled_briefs` table (cron expression, template, model, recipients, enabled)
- [ ] Background task: evaluate schedules, generate briefs, store results
- [ ] Templates: Daily SITREP, Weekly Summary, Entity Watch, Narrative Digest
- [ ] Configurable time window (brief covers last 24h, 7d, etc.)

### Phase 2: Delivery Channels
- [ ] Telegram delivery — send brief summary + PDF attachment to configured chat
- [ ] Email delivery — SMTP integration (optional, self-hosted or external)
- [ ] Webhook delivery — POST brief JSON to any URL
- [ ] In-app notification — new brief badge in sidebar

### Phase 3: Brief Templates
- [ ] Template editor in frontend (prompt template with variables)
- [ ] Variables: `{{date_range}}`, `{{top_entities}}`, `{{active_narratives}}`, `{{alert_summary}}`
- [ ] Preview mode: render template without running LLM
- [ ] Share templates between users

---

## Sprint 22 — Production Hardening

**Goal:** Make Orthanc production-ready for always-on deployment.

### Phase 1: Reverse Proxy & HTTPS
- [ ] Nginx config: reverse proxy frontend (3001) + backend (8000) on single port (443)
- [ ] Let's Encrypt / ACME auto-certificate renewal
- [ ] HSTS headers, CSP policy
- [ ] Optional: Tailscale-only mode (no public exposure)

### Phase 2: Backup & Recovery
- [ ] `orthanc backup` CLI command — pg_dump + media archive
- [ ] `orthanc restore` CLI command — restore from backup
- [ ] Scheduled backups (configurable, default daily)
- [ ] Backup to local path, S3-compatible storage, or remote via rsync

### Phase 3: Monitoring
- [ ] `/metrics` Prometheus endpoint (post count, collector status, LLM usage, queue depth)
- [ ] Optional Grafana dashboard template
- [ ] System status page: database size, uptime, collector health, LLM provider status
- [ ] Disk usage monitoring with alerts

### Phase 4: Multi-User
- [ ] Role-based access: Admin, Analyst, Viewer
- [ ] Admin panel: manage users, view all sources, system settings
- [ ] Shared cases between users
- [ ] Per-user source isolation (each user sees only their configured sources) vs shared mode
- [ ] Audit log: who did what, when

---

## Sprint 23 — GDELT & Source Reliability

**Goal:** Integrate GDELT for massive event coverage and build a source reliability scoring system.

### Phase 1: GDELT Integration
- [ ] GDELT v2 Events API collector (event database, 15-min updates)
- [ ] GDELT GKG (Global Knowledge Graph) — entity/theme/tone extraction
- [ ] Map layer: GDELT events (conflict, protest, diplomacy)
- [ ] Cross-reference: match Orthanc posts to GDELT events by location/time/entity

### Phase 2: Source Reliability Scoring
- [ ] Track claim → corroboration pipeline:
  - Source makes a claim (extracted by narrative engine)
  - Other sources confirm or deny
  - Evidence linker finds supporting data (FIRMS, ACLED, etc.)
- [ ] Reliability score per source: % of claims corroborated within 48h
- [ ] Bias Compass: auto-position sources based on reliability + stance patterns
- [ ] Feed: reliability badge on each post (🟢 reliable, 🟡 unverified, 🔴 unreliable)

### Phase 3: OSINT Verification Toolkit
- [ ] Reverse image search integration (TinEye or Google Lens API)
- [ ] Geolocation verification: cross-reference claimed location with image metadata
- [ ] Timestamp verification: cross-reference claimed time with EXIF/metadata
- [ ] Verification status on posts: Verified, Unverified, Disputed, Debunked

---

## Sprint 24 — Mobile & Accessibility

**Goal:** Make Orthanc usable on tablets and phones.

### Phase 1: Responsive Layout
- [ ] Breakpoints: mobile (<768px), tablet (768–1200px), desktop (>1200px)
- [ ] Sidebar: drawer overlay on mobile, collapsible on tablet
- [ ] Feed: single-column card layout on mobile
- [ ] Map: full-screen mode with floating controls
- [ ] Dashboard: stack cards vertically on narrow screens

### Phase 2: PWA
- [ ] Service worker for offline access to cached data
- [ ] App manifest for "Add to Home Screen"
- [ ] Push notifications for alerts (via service worker)
- [ ] Background sync for brief delivery

---

## Priority Order

| Priority | Sprint | Effort | Impact |
|----------|--------|--------|--------|
| 🔴 High | Sprint 17 — LLM Provider Framework | Large | Enables cost control + self-hosted |
| 🔴 High | Sprint 18 — Bug Fixes & Polish | Medium | Quality of life, stability |
| 🟡 Medium | Sprint 21 — Scheduled Briefs | Medium | Key analyst workflow |
| 🟡 Medium | Sprint 19 — Frontline History | Medium | Unique differentiator |
| 🟡 Medium | Sprint 20 — Entity Graph | Medium | Visual intelligence |
| 🟡 Medium | Sprint 22 — Production Hardening | Medium | Required for real deployment |
| 🟢 Lower | Sprint 23 — GDELT & Reliability | Large | Advanced analysis |
| 🟢 Lower | Sprint 24 — Mobile | Medium | Broader access |

---

## Notes

- Each sprint is independent — can be done in any order
- Sprint 17 (LLM) should be done first as other sprints benefit from cheaper model access
- Sprint 18 (bugs) can be interleaved with any other sprint
- Estimated total: ~8 sprints × 2–4 sessions each = 16–32 sessions
- All work follows existing patterns: Docker, async, no external UI libs, CSS variables, OQL integration


---

## Sprint 25 — Narrative Intelligence 2.0

**Goal:** Upgrade narratives from rough embedding clusters into analyst-usable canonical narratives with better titles, claims, type classification, and optional LLM confirmation.

### Phase 1: Canonical Narrative Layer
- [ ] Extend narrative model/schema with canonical fields:
  - `raw_title`
  - `canonical_title`
  - `canonical_claim`
  - `narrative_type`
  - `label_confidence`
  - `confirmation_status`
- [ ] Preserve raw/heuristic clustering output separately from analyst-facing title
- [ ] Update API responses + frontend to prefer `canonical_title` when present

### Phase 2: Better Heuristic Labeling
- [ ] Replace naive word-frequency title generation with stronger heuristic labeler
- [ ] Suppress boilerplate/source-attribution terms (`said`, `officials`, `embassy`, `report`, etc.)
- [ ] Weight entities, action words, and locations more highly than generic tokens
- [ ] Generate a better heuristic title + heuristic canonical claim before any LLM step

### Phase 3: LLM-Assisted Narrative Labeling
- [ ] Add model-router tasks:
  - `narrative_label`
  - `narrative_confirmation`
- [ ] Run LLM refinement on representative posts after clustering (not in hot ingestion path)
- [ ] LLM outputs:
  - canonical title
  - canonical claim
  - narrative type
  - cluster coherence / confirmation result
- [ ] Add execution modes:
  - Off
  - Assist
  - Strict
- [ ] Default provider path: OpenRouter; allow model dropdown selection (Hunter Alpha if available)

### Phase 4: Narrative UI Improvements
- [ ] Show canonical title, type badge, and confirmation state in narratives page/detail view
- [ ] Keep UI restrained — no badge spam
- [ ] Preserve fallback behavior when no provider/model is available

---

## Sprint 26 — Tracked Narratives

**Goal:** Support operator-defined narratives/hypotheses that accumulate supporting/contradicting evidence over time.

### Phase 1: Analyst-Defined Narrative Objects
- [ ] Expand current tracker system into true tracked narratives / standing hypotheses
- [ ] Add richer fields:
  - `name`
  - `hypothesis`
  - `description`
  - `entity_ids`
  - `keywords`
  - `claim_patterns`
  - `status`
  - `model_policy`
- [ ] Preserve versioning of criteria

### Phase 2: Matching Engine
- [ ] Match tracked narratives against:
  - new posts
  - discovered narratives
- [ ] Store scored matches with rationale and timestamps
- [ ] Add model-router task: `tracked_narrative_match`
- [ ] Support OpenRouter model dropdown for matching model selection

### Phase 3: Evidence Semantics
- [ ] Classify matched evidence into:
  - supports
  - contradicts
  - contextual / mention-only
  - unclear
- [ ] Surface source-type breakdown, source-group divergence, and evidence timelines

### Phase 4: UI
- [ ] Create tracked narrative workflow for create/edit/review
- [ ] Show longitudinal evolution over time (volume, source mix, support vs contradiction)

---

## Sprint 27 — Entity Resolution

**Goal:** Clean up duplicate entities and establish canonical identity handling for aliases and merges.

### Phase 1: Better Normalization
- [ ] Improve canonicalization rules:
  - punctuation normalization
  - abbreviation expansion
  - country/org alias mapping
  - whitespace/hyphen normalization
- [ ] Handle obvious equivalents like `US`, `U.S.`, `USA`, `United States`

### Phase 2: Merge Candidates
- [ ] Add merge-candidate API with confidence + rationale
- [ ] Signals:
  - normalized text similarity
  - alias matches
  - shared context
  - entity type compatibility
  - optional LLM assistance
- [ ] Add model-router task: `entity_resolution_assist`

### Phase 3: Merge Workflow
- [ ] Add safe manual merge endpoint/process
- [ ] Reassign mentions, preserve aliases, retain canonical entity, and avoid destructive blind deletes
- [ ] Ensure downstream systems (graph, narratives, search) continue to resolve correctly after merge

### Phase 4: Entity Detail Improvements
- [ ] Show aliases, effective type, and merge suggestions in entity detail UI

---

## Sprint 28 — Full Entity Search & Scale

**Goal:** Remove top-500 frontend limitation and make entities searchable/paginatable across the full dataset.

### Phase 1: Backend Pagination
- [ ] Update `/entities/` to return paginated results with `items`, `total`, `limit`, `offset`
- [ ] Support server-side search/filter/sort against full dataset
- [ ] Make search alias-aware once Sprint 27 lands

### Phase 2: Frontend Entity Browser
- [ ] Replace top-500 preload with backend-driven pagination/search
- [ ] Ensure list/search/sort reflect full dataset, not an in-memory subset
- [ ] Update entity pickers/path selectors/detail dropdowns to use backend search, not local 500-row cache

### Phase 3: UX Clarification
- [ ] Show real totals (e.g. `displaying 1–50 of 5,318`)
- [ ] Remove misleading `500/500` style counts

### Cross-Cutting LLM Model Routing
- [ ] Add new model-router tasks for narrative and entity-intelligence workflows:
  - `narrative_label`
  - `narrative_confirmation`
  - `tracked_narrative_match`
  - `entity_resolution_assist`
- [ ] Expose dropdown model selection for these tasks in Models settings
- [ ] Default to OpenRouter path; allow Hunter Alpha selection when available
- [ ] Keep heuristics-only fallback for all AI-assisted features

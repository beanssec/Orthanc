# Build Log

---

## 2026-03-04: Sprint 1 — Foundation ✅

- Docker Compose (Postgres 16 + PostGIS on port 5433, FastAPI on 8000, React on 3001)
- Alembic migration `001_initial_schema`: users, credentials, posts, sources, events, alerts, alert_hits
- FastAPI routers: auth, credentials, sources, feed (REST + WebSocket), alerts
- Crypto service (Argon2id + Fernet per-user encryption)
- Collector manager (in-memory key store)
- Fixes: User model field mismatch, Post→Event relationship, PostResponse schema types

## 2026-03-04: Sprint 2 — Collectors ✅

- RSS collector (feedparser, async polling, dedup, broadcast)
- X poller (xAI/Grok API, dedup, rate limit handling)
- Telegram collector (Telethon, interactive auth flow, channel listener)
- Collector orchestrator wired into FastAPI lifespan
- 7 RSS sources seeded, ~150 posts ingested

## 2026-03-04: Sprint 3 — Frontend ✅

- React + Vite + TypeScript with dark professional theme
- Auth pages (login/register), Feed (3-column SIEM), Settings (sources, credentials, alerts, Telegram)
- WebSocket live feed
- Fixes: greenlet error, login format mismatch, component prop names

## 2026-03-04: Sprint 4 — Geo Pipeline + Map ✅

- spaCy NER geo extraction (GPE/LOC/FAC)
- Nominatim geocoding (rate-limited, cached)
- 321 geo events from initial posts
- MapLibre GL map: CartoDB dark-matter tiles, clustered markers, sidebar filters, heatmap toggle

## 2026-03-04: Sprint 5 — Connectors + Analysis ✅

- Shodan, Discord, Reddit, Webhook collectors
- Entity extraction (PERSON/ORG/GPE/EVENT/NORP) + dedup/linking → 361 entities
- Dashboard stats API
- AI intelligence briefs (9 models: xAI Grok + OpenRouter)

## 2026-03-04: Sprint 6 — Intel Layers ✅

- FIRMS thermal anomaly collector
- Flight tracking (OpenSky Network, military filtering)
- AIS ship tracking
- Satellite tracking (CelesTrak TLEs + sgp4, ~130 satellites)
- Multi-source Ukraine frontlines (DeepState, AMK, Suriyak, UA Control Map, Playfra, Radov)
- Translation service (auto-detect + AI translate)
- Brief persistence + history view

## 2026-03-04: Sprint 7 — Financial Intelligence ✅

- Migration `004_financial`: holdings, quotes, entity_ticker_map, signals
- Market collector (Yahoo Finance via yfinance)
- Cashtag collector ($TICKER monitoring via xAI)
- Opportunity scanner (entity spike detection → ticker mapping → AI signals)
- Frontend: PortfolioView, MarketsView, SignalsView (Bloomberg terminal aesthetic)

## 2026-03-05: Sprint 8 — Launch Prep ✅

### Bug Fixes
- JWT username in sidebar, HTML entity decoding, RSS title cleanup
- Double-@@ fix, currency symbols, delete confirmations, text contrast
- Brief cost badge, signal timestamps, zero-count source dimming
- Empty state CTAs, login form labels, brief headline extraction

### Correlation Engine
- Migration `006_alert_rules`: alert_rules + alert_events tables
- 3-level system: keyword → velocity → multi-stage correlation
- 60s velocity loop, Telegram/in-app/webhook delivery
- Full CRUD API + frontend rule builder wizard
- Iran velocity rule fired (3.9x baseline), Gulf Escalation correlation fired URGENT

### Setup & Rename
- First-run setup wizard (4-step, auto-redirect for new users)
- Orthanc rename across 30+ Python files, 7 frontend files, docker-compose.yml
- README.md, .env.example, .gitignore written
- Credential scan — removed all hardcoded secrets

## 2026-03-05: Sprint 9 — Post-Launch Polish ✅

### Dashboard Overhaul
- Velocity chart, source health matrix, trending entities, geo hotspots
- KPI strip, 60s auto-refresh

### Analysis Features
- Entity network graph (canvas force-directed, co-occurrence edges)
- Translate button per feed item
- Brief scheduling (hourly/daily/weekly) + history (3-tab UI)
- Feed volume sparkline

### Reports & Visualization
- PDF intelligence reports (reportlab, dark theme, classification banners)
- Sentiment heatmap (keyword-based scoring, circle + heatmap modes on map)

### Mobile
- Hamburger sidebar, bottom-sheet panels, FABs on map, touch targets
- Tested on Pixel 7 Pro (412×915 viewport)

### Stability
- Location precision scoring (exact/city/region/country/continent)
- JWT token expiry bumped to 8 hours
- Full interaction test — zero 401s, zero JS errors

## 2026-03-05: Sprint 10 — Wave 1 (Parallel Build) ✅

### Global Search
- `GET /search` endpoint (ILIKE across posts, entities, events, briefs)
- GlobalSearch component with Ctrl+K shortcut, debounced dropdown (300ms)
- Full `/search?q=` results page with filter tabs (All/Posts/Entities/Events/Briefs)
- Keyword highlighting with `<mark>` tags
- AppShell top bar with search + WS status + alert bell

### Alerts V2
- Migration `007_alert_enhancements`: 8 new columns for geo + silence fields
- Geo-proximity alerts: haversine formula, configurable center + radius (1-500km)
- Silence detection: 5-minute periodic loop, tracks last-seen timestamps
- Frontend: 5 rule type cards in wizard (keyword, velocity, correlation, geo-proximity, silence)

### Entity Timeline + Path Analysis
- `GET /entities/{id}/timeline`: paginated chronological mentions with geo data
- `GET /entities/path`: BFS shortest path between entities via co-occurrence (max depth 5)
- EntityDetail: Overview/Timeline tabs, time range filter pills
- EntityGraph: path-finding controls, highlighted path nodes/edges in amber

### Document Upload
- `POST /documents/upload`: accepts PDF/DOCX/TXT/MD/CSV (max 50MB)
- Text extraction: pdfminer.six (PDF), python-docx (DOCX), native (TXT/MD/CSV)
- Auto-runs geo + entity NER pipeline on upload, broadcasts via WebSocket
- Frontend: drag-and-drop DocumentsView, "ANALYSIS" sidebar section
- `document` source type added to feed labels

### Layout Fix
- Global search agent's inline flex styles conflicted with CSS Grid
- Fixed: removed inline styles, updated grid to `auto 1fr` rows, topbar spans full width

## 2026-03-05: Sprint 11 — Wave 2 (Parallel Build) ✅

### Natural Language Querying
- `POST /query` endpoint: LLM translates questions → structured JSON query plan → executes → AI summary
- Two-stage pipeline: query planning (grok-3-mini) → result collection → summarization
- 6 query types: search, entity_top, entity_search, events_near, signals, summarize
- Graceful fallbacks: invalid JSON → simple search; no credentials → helpful error
- Frontend: `/query` page with example chips, history sidebar, collapsible data sections
- GlobalSearch: detects NL questions, shows "🧠 Ask AI" button

### Entity Relationships + Collaboration
- Migration `008_entity_relationships`: 5 new tables
- `entity_relationships`: 11 typed relationships (commands, funds, opposes, sanctions, etc.) with confidence scoring
- `entity_properties`: extensible key-value per entity
- `user_notes`: per-user notes on entity/post/event with edit/delete
- `user_bookmarks`: cross-type bookmarking (entity/post/event/brief)
- `user_tags`: user-defined labels, searchable across platform
- Frontend: Relationships tab (add modal, confidence bars), Notes tab, bookmark toggle, tag chips
- BookmarksView at `/bookmarks` with type grouping

## 2026-03-05: Sprint 12 — Telegram Media & Verification ✅

### Telegram Collector Activation
- Wired TelegramCollector into orchestrator (was never started before)
- Added history backfill on startup (last 50 messages per channel)
- Successfully connected to Middle_East_Spectator: 50 messages pulled

### Media Capture
- Migration `009_media_support`: 9 media columns on posts, 4 settings columns on sources
- Per-source opt-in: separate toggles for images vs videos with max size limits
- Telethon `download_media()` → save to `/data/media/{channel}/{msg}.{ext}`
- Pillow-based thumbnail generation (400px wide)

### Metadata & Verification
- EXIF extraction: camera make/model, software (flags DALL-E/Midjourney/etc.), GPS, timestamps
- SHA256 file hashing for deduplication
- Video metadata via ffprobe (codec, resolution, duration)
- AI authenticity analysis via Grok Vision (primary) or GPT-4o (fallback)
- Structured scoring: 0.0 (AI) → 1.0 (real), verdict, reasoning, 6 indicator flags
- Async analysis — never blocks post ingestion

### Frontend
- Auth-gated media serving (`GET /media/{post_id}?thumb=true/false`)
- FeedItem: inline thumbnails, authenticity badges (🟢/🟡/🔴/⏳)
- FeedDetail: full-size media, MediaAnalysisPanel (score bar, EXIF table, AI reasoning)
- SourcesPage: per-Telegram-source media toggles with size inputs

---

## Database Migrations (9 total)
1. `001_initial_schema` — core tables
2. `002_entities` — entity extraction
3. `003_briefs` — intelligence briefs
4. `004_financial` — portfolio + market data
5. `005_geo_precision` — location precision scoring
6. `006_alert_rules` — correlation engine
7. `007_alert_enhancements` — geo-proximity + silence detection
8. `008_entity_relationships` — relationships, properties, notes, bookmarks, tags
9. `009_media_support` — media capture + authenticity

## Current Stats
- ~1240+ posts (RSS, X, Telegram, cashtag, document, webhook)
- ~470+ entities (PERSON, ORG, GPE, NORP, EVENT)
- ~430+ geo events
- 12 active collectors
- 14 frontend pages
- 5 alert rule types
- 9+ AI models supported

## Next Up
- Wave 3: Investigation/case management + Connector plugin framework

## Sprint 13: Data Fusion & Entity Enrichment (2026-03-06)

### Phase 1: Map & Cleanup ✅
- Satellite imagery tile toggle (Dark / Satellite / Hybrid) using Esri World Imagery
- Style switch re-adds all data layers via extracted `setupDataLayers()` function
- Removed Mapbox from credential providers (dead code)
- Collapsible sidebar navigation (icon-only mode, persists in localStorage)

### Phase 2: ACLED Conflict Intelligence ✅
- `acled_collector.py` — polls ACLED API every 6h for Middle East, Eastern Europe, Northern Africa
- Migration `010_acled.py` — `external_id` column on posts for dedup
- ACLED credential provider (api_key + email)
- Map layer: circle markers color-coded by event type (battles=red, explosions=orange, protests=yellow, riots=purple, violence=darkred, strategic=blue)
- Layer default OFF, requires API key

### Phase 3: GDELT Media Intelligence ✅
- `gdelt_service.py` — DOC API for article search (rate-limited 1/5s, 15min cache)
- `gdelt_geo_service.py` — GEO API for media attention heatmaps
- Router: `GET /gdelt/articles`, `GET /gdelt/geo`
- Map layer: "Media Attention" heatmap with keyword input + presets
- Entity detail: "Global Media" tab showing GDELT articles
- No API key required

### Phase 4: OpenSanctions Matching ✅
- Migration `011_sanctions.py` — `sanctions_entities` + `entity_sanctions_matches` tables, pg_trgm
- `sanctions_service.py` — streaming download of 200MB bulk dataset, trigram fuzzy matching
- Router: `/sanctions/status`, `/sanctions/refresh`, `/sanctions/search`, `/sanctions/matches/{id}`, `/sanctions/check/{id}`
- Entity detail: "Sanctions" tab with red/amber match badges, dataset labels, confidence scores
- Download only on explicit trigger (not on startup)

### Phase 5: ICIJ + OCCRP Entity Enrichment ✅
- `icij_service.py` — ICIJ Offshore Leaks search (Panama/Paradise/Pandora/Bahamas Papers)
- `occrp_service.py` — OCCRP Aleph search (1B+ corporate/legal/leaked records)
- Router: `/investigations/icij/search`, `/investigations/occrp/search`
- OCCRP credential provider (optional free API key)
- Entity detail: "Investigations" tab with color-coded dataset badges
- 24-hour result caching, no bulk downloads

### Phase 6: Cross-Source Fusion Engine ✅
- Migration `012_fused_events.py` — fused events table with UUID/TEXT arrays
- `fusion_service.py` — background 5-minute scan, haversine clustering (50km/6h window)
- Severity: FLASH (4+ sources/10+ posts), URGENT (3 sources), ROUTINE (2 sources)
- Map layer: diamond markers color-coded by severity
- Dashboard widget: "Intelligence Fusion" card (only visible when fused events exist)
- Router: `/fusion/events`, `/layers/fusion`

### Phase 7: Investigation Workspaces ✅
- Migration `013_investigations.py` — cases, case_items, case_timeline tables
- Full CRUD: create/list/update/delete cases, add/remove items, timeline, PDF export
- Frontend: Cases list + Case detail (3-tab: Evidence Board, Timeline, Map)
- "Add to Case" dropdown on feed items and entity details
- Status workflow: Open → Active → Closed → Archived
- Classification badges: Unclassified, Confidential, Secret, Top Secret

### Bug Fixes
- Fixed OpenRouter model IDs: `claude-haiku-3.5` → `claude-3.5-haiku`, `claude-sonnet-4-20250514` → `claude-sonnet-4`
- Fixed AIS credential 422 (missing from Pydantic Literal type)
- Fixed image authenticity "Analyzing..." stuck forever (set checked_at on failure)
- Fixed authenticity analyzer to prefer OpenRouter/GPT-4o (xAI vision needs higher tier)
- Added `POST /media/reanalyze` endpoint for bulk retry
- Better API error messages (include response body)

### Brief Enhancements
- Topic keyword filter — scope briefs to specific subjects
- Source type checkboxes — include/exclude specific data sources
- Custom system prompt — override the default analyst persona
- Advanced options toggle in the briefs UI

## Sprint 14 Phase 3 — OQL Visualization Builder

### New Files
- `frontend/src/components/charts/BarChart.tsx` — Horizontal bar chart (HTML+CSS, animated widths)
- `frontend/src/components/charts/TimeSeriesChart.tsx` — SVG line/area chart with ResizeObserver
- `frontend/src/components/charts/DonutChart.tsx` — SVG donut chart with path-based arcs
- `frontend/src/components/charts/StatCard.tsx` — Big number display with trend arrow
- `frontend/src/components/query/VizBuilder.tsx` — Viz type toolbar + auto-mapping + save to dashboard
- `frontend/src/styles/charts.css` — All chart styles (no Tailwind, CSS variables, monospace font)

### Modified Files
- `frontend/src/components/query/QueryView.tsx` — Added VizBuilder import + integration below results
- `backend/app/routers/oql.py` — Extended `SaveQueryRequest` + `save_query` to accept `is_pinned` + `visualization_config`

### Features
- Auto-selects chart type from `visualization_hint` (bar/timeseries/pie/table)
- StatCard auto-selected for single-row single-numeric results
- Bar chart: horizontal bars, CSS transitions, scrollable (max 20), hover tooltip, click handler
- Time series: SVG area+line, ResizeObserver responsive, crosshair tooltip, multi-series legend
- Donut chart: SVG path arcs, max 8 segments + "Other", hover expand, center total
- VizBuilder toolbar: 📋 Table | 📊 Bar | 📈 Line | 🍩 Donut | 🔢 Stat
- "Save to Dashboard" pins query with visualization_config to saved_queries
- No external chart libraries — raw SVG + HTML only

## 2026-03-14: Spec Re-alignment Cleanup ✅

### Auth / Session Handling
- Reverted frontend auth token storage to Zustand in-memory only (removed localStorage persistence) to match SPEC.md security model
- Added `GET /auth/session-status` to expose post-login warm-up state for provider registration + collector startup
- Added in-memory post-login init tracking fields: `authenticated`, `initializing`, `providers_initialized`, `collectors_started`, `init_error`

### Narrative Tracker UI
- Removed non-dynamic inline styles from tracker UI in `NarrativesView.tsx`
- Moved tracker presentation styles into `frontend/src/styles/narratives.css`

### Migration Audit
- Canonical alembic head verified as `024_entity_aliases_and_overrides`
- Current chain in active history: `020_entity_relationships` → `021_entity_relationship_metadata` → `022_timeline_perf_indexes` → `023_narrative_trackers` → `024_entity_aliases_and_overrides`
- No duplicate heads present at audit time

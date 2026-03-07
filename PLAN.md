# Orthanc — Active Build Plan

## Working Mode
Autonomous iterative development with parallel subagent delegation.
Nick checks BUILD_LOG.md for progress. Platform at http://localhost:3001

---

## Completed Sprints

### Sprint 1: Foundation ✅
- Docker Compose stack (Postgres + Backend + Frontend)
- JWT auth, Argon2 password hashing, per-user Fernet encryption
- Credential management via web UI
- Collector manager with in-memory key store

### Sprint 2: Collectors ✅
- RSS, X/Twitter (xAI), Telegram (Telethon) collectors
- Collector orchestrator wired into FastAPI lifespan

### Sprint 3: Frontend ✅
- React + Vite + TypeScript with dark professional theme
- Feed (3-column SIEM), Settings (sources, credentials, alerts, Telegram)

### Sprint 4: Geo Pipeline + Map ✅
- spaCy NER → Nominatim geocoding → events table
- MapLibre GL map with clustered markers, dark CartoDB tiles

### Sprint 5: Connectors + Analysis ✅
- Shodan, Discord, Reddit, Webhook collectors
- Entity extraction + linking (PERSON/ORG/GPE/NORP/EVENT)
- AI intelligence briefs (9 models via xAI + OpenRouter)
- Dashboard stats API

### Sprint 6: Intel Layers ✅
- FIRMS thermal, Flight tracking, Ship tracking, Satellite tracking
- Multi-source frontlines (6 Ukraine mapping sources)
- Translation service
- Brief persistence + history

### Sprint 7: Financial Intelligence ✅
- Portfolio tracking, market watchlist (Yahoo Finance)
- Cashtag monitoring, opportunity scanner
- Entity-to-ticker mapping, AI signals

### Sprint 8: Launch Prep ✅
- P0/P1 bug fixes (JWT, contrast, currency symbols, etc.)
- Correlation engine (3-level: keyword, velocity, multi-stage correlation)
- First-run setup wizard
- Orthanc rename (from Overwatch)
- README.md, .env.example, .gitignore
- Credential scan (removed all hardcoded secrets)

### Sprint 9: Post-Launch Polish ✅
- Dashboard overhaul (velocity chart, source health, trending entities, geo hotspots)
- Entity network graph (canvas force-directed)
- Translate button per feed item
- Brief scheduling + history (3-tab UI)
- Feed volume sparkline
- PDF intelligence reports (reportlab, dark theme)
- Sentiment heatmap (keyword scoring, map layer)
- Mobile responsive (hamburger sidebar, bottom-sheet, FABs)

### Sprint 10: Wave 1 — Core Analysis ✅
- **Global Search** — unified /search endpoint, Ctrl+K shortcut, debounced dropdown, full results page with tabs
- **Alerts V2** — geo-proximity alerts (haversine) + silence detection (5min loop), 5 rule types total
- **Entity Timeline** — chronological mention view per entity with pagination
- **Link/Path Analysis** — BFS shortest path between entities via co-occurrence graph
- **Document Upload** — PDF/DOCX/TXT/MD/CSV upload with automatic NER pipeline

### Sprint 11: Wave 2 — Intelligence & Collaboration ✅
- **Natural Language Querying** — LLM translates questions → structured DB queries → AI summary
- **Typed Entity Relationships** — 11 types (commands, funds, opposes, etc.) with confidence scoring
- **Notes** — per-user notes on entities, posts, events
- **Bookmarks** — cross-type bookmarking with dedicated page
- **Tags** — user-defined labels, searchable across platform

### Sprint 12: Telegram Media & Verification ✅
- **Media Capture** — opt-in per-source (separate image/video toggles, size limits)
- **EXIF Extraction** — camera, software, GPS, timestamps, AI software detection
- **AI Authenticity Analysis** — Grok Vision / GPT-4o, structured scoring (0.0–1.0)
- **Media Serving** — auth-gated endpoint, thumbnail generation
- **Feed Integration** — inline thumbnails, authenticity badges, analysis panel

### Sprint 12.5: Dashboard & UX Polish ✅
- **Dashboard redesign** — Source Health → compact pill strip, Velocity → full width
- **Drill-down navigation** — every dashboard element clickable with deep linking
- **Feed URL params** — `?source=`, `?post=` for direct navigation
- **Entity deep links** — `?search=`, `?selected=` URL params
- **Image analysis fix** — OpenRouter/GPT-4o primary, xAI fallback; bulk reanalyze endpoint
- **AIS credential fix** — added to Pydantic schema, fixed error display

---

## Current: Sprint 13 — Data Fusion & Entity Enrichment

### Design Principles
- **Opt-in by default**: All data sources that don't require API keys start DISABLED
- **Toggle in Sources page**: Each source gets an on/off toggle, same UX as existing collectors
- **No bulk downloads**: Use APIs on-demand or with configurable polling intervals
- **Entity enrichment is passive**: Runs automatically when entities are extracted, results cached

---

### Phase 1: Map & Cleanup (1 agent, quick wins)

#### 1A. Satellite Imagery Tile Toggle
- Add base layer switcher to map: Dark (current) / Satellite / Hybrid
- **Satellite**: Esri World Imagery tiles (`https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`)
- **Hybrid**: Satellite + Esri Reference Overlay labels (`https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`)
- UI: 3-button toggle in map toolbar (🌑 Dark / 🛰️ Satellite / 🗺️ Hybrid)
- No API key required (Esri world imagery tiles are free for non-commercial/dev use)

#### 1B. Remove Mapbox
- Remove `mapbox` from `KNOWN_PROVIDERS`, `CredentialCreate` Literal, credential page config
- Remove any references in collector_manager
- Clean dead code

#### 1C. Documentation Update
- Update README with new data sources section
- Add "Data Sources" documentation page explaining each source, auth requirements, data volume, toggle behavior
- Update CONTRIBUTING.md with how to add a new enrichment source

---

### Phase 2: Conflict Intelligence — ACLED (1 agent)

**Source**: Armed Conflict Location & Event Data (acleddata.com)
**Auth**: Free API key (register at developer.acleddata.com)
**Data**: Structured conflict events — battles, explosions, protests, riots, strategic developments, violence against civilians
**Volume**: ~300k events/year globally, ~2KB each
**Storage**: ~500MB/year (filtered to configured regions)

#### Backend
- New collector: `backend/app/collectors/acled_collector.py`
  - Polls ACLED API: `https://api.acleddata.com/acled/read?key=KEY&email=EMAIL&...`
  - Configurable region filters (default: Middle East, Ukraine, Africa Sahel)
  - Configurable event type filters (battles, explosions/remote violence, protests, riots, violence against civilians, strategic developments)
  - Polling interval: every 6 hours (ACLED updates daily-ish)
  - Dedup by ACLED `data_id` field
  - Each event → posts table (source_type='acled') + geo_events table (lat/lng from ACLED, exact precision)
  - Entity extraction from ACLED `actor1`, `actor2`, `assoc_actor_1`, `assoc_actor_2` fields (structured, not NER — much more reliable)
  - Fatality data stored in post metadata
- New credential provider: `acled` (api_key + email)
- Add to orchestrator `start_user_collectors()` / `stop_user_collectors()`
- Migration: add `acled_event_id` to posts for dedup (indexed)

#### Frontend
- Add `acled` to credential page with setup guide
- Add ACLED as source type in Sources page
- **New map layer**: "Conflict Events" — circle markers color-coded by event type:
  - 🔴 Battles — red
  - 🟠 Explosions/Remote Violence — orange
  - 🟡 Protests — yellow
  - 🟣 Riots — purple
  - ⚫ Violence Against Civilians — dark red
  - 🔵 Strategic Developments — blue
- Layer panel: event type filter checkboxes
- Click event → detail panel showing actors, fatalities, notes, source articles
- **Default: OFF** (requires API key + explicit enable)

#### Docs
- Add ACLED section to README
- Document region filter configuration
- Note: "ACLED provides the most reliable structured conflict data available. Free for researchers and non-commercial use."

---

### Phase 3: Global Media Intelligence — GDELT (1 agent)

**Source**: GDELT Project (gdeltproject.org)
**Auth**: None — completely free, no key
**Data**: Global media monitoring — every news article worldwide, geolocated, tone-scored, translated from 65 languages
**Volume**: API-only (no bulk storage), ~1KB per query response
**Storage**: Negligible (~50MB cache)

#### Backend — Two Services

**3A. GDELT DOC API Service** (`backend/app/services/gdelt_service.py`)
- Query endpoint: `https://api.gdeltproject.org/api/v2/doc/doc?query=TERM&mode=artlist&maxrecords=250&format=json`
- Rate limit: 1 request per 5 seconds (enforce with asyncio semaphore)
- Used by: NL Query, Briefs, Entity enrichment
- Caches results for 15 minutes per query
- Returns: article title, URL, source, language, tone, date, domain, image
- **Not a collector** — on-demand service, not a polling loop

**3B. GDELT GEO API Map Layer** (`backend/app/services/gdelt_geo_service.py`)
- Endpoint: `https://api.gdeltproject.org/api/v2/geo/geo?query=KEYWORD&format=GeoJSON`
- Returns GeoJSON heatmap of global media attention for a keyword
- Map layer: "Media Attention" — heatmap overlay showing where the world is talking about a topic
- User types a keyword in the layer panel → heatmap updates
- 7-day rolling window, 15-minute updates from GDELT
- Cache: 15 minutes per keyword

#### Frontend
- **New map layer**: "Media Attention" (GDELT GEO)
  - Keyword input field in layer panel
  - Heatmap overlay (orange/red gradient)
  - Presets: "conflict", "nuclear", "cyber attack", "terrorism", "protest"
- **Brief enrichment**: When generating AI briefs, optionally pull GDELT context for mentioned entities
- **Entity detail enrichment**: "Global Media" tab showing recent GDELT articles mentioning the entity
- **Default: OFF** (no API key needed, but opt-in in Sources page toggle)

#### Docs
- Document GDELT integration, rate limits, caching strategy
- Note: "GDELT processes virtually every news article published worldwide in 65 languages. No API key required."

---

### Phase 4: Sanctions & Watchlist Matching — OpenSanctions (1 agent)

**Source**: OpenSanctions (opensanctions.org)
**Auth**: Free bulk download, API with free tier
**Data**: 350k+ entities — OFAC SDN, EU sanctions, UN sanctions, Interpol, PEPs (Politically Exposed Persons), crime watchlists
**Volume**: ~200MB bulk dataset (compressed), updates daily
**Storage**: ~500MB (local SQLite or Postgres table for fast matching)

#### Backend
- New service: `backend/app/services/sanctions_service.py`
  - Downloads OpenSanctions bulk dataset (JSON lines format) on first run + daily refresh
  - Stores in `sanctions_entities` table: name, aliases, entity_type (person/org/vessel/aircraft), datasets (which sanctions lists), countries, birth_date, properties (JSON)
  - Fuzzy matching service: given an entity name, return top matches with confidence score
  - Uses trigram similarity (pg_trgm extension) for fast fuzzy matching
  - Alias matching: OpenSanctions provides known aliases per entity
- New background task: `sanctions_matcher`
  - Runs on entity extraction: when a new entity is created/updated, check against sanctions DB
  - Stores matches in `entity_sanctions_matches` table: entity_id, sanctions_entity_id, confidence, matched_on (name/alias), datasets
  - Threshold: confidence > 0.7 = "possible match", > 0.9 = "strong match"
- Migration: `010_sanctions.py`
  - `sanctions_entities` table (id, name, aliases[], entity_type, datasets[], countries[], properties JSONB, updated_at)
  - `entity_sanctions_matches` table (entity_id FK, sanctions_entity_id FK, confidence, matched_on, datasets[], created_at)
  - Enable `pg_trgm` extension for trigram matching

#### Frontend
- **Entity detail**: "Sanctions" tab — if matched, show:
  - 🔴 SANCTIONED badge with dataset names (OFAC SDN, EU, UN, etc.)
  - Matched name vs alias
  - Confidence score
  - Link to OpenSanctions profile
- **Feed items**: If a post mentions a sanctioned entity, show 🔴 sanctions indicator
- **Dashboard widget**: "Sanctioned Entity Mentions" — count of feed items mentioning matched entities in last 24h
- **Alert rule type**: "Sanctions Match" — alert when a newly extracted entity matches a sanctions list
- **Default: OFF** (toggle in Sources page, downloads ~200MB on first enable)

#### Docs
- Document sanctions matching, confidence thresholds, update frequency
- Note: "OpenSanctions aggregates OFAC, EU, UN, Interpol, and 30+ other sanctions/watchlists. Free for non-commercial use."

---

### Phase 5: Leaked Data & Corporate Intelligence — ICIJ + OCCRP (1 agent)

**Source**: ICIJ Offshore Leaks Database + OCCRP Aleph
**Auth**: None (ICIJ) / Free registration (OCCRP)
**Data**: Panama/Pandora/Paradise Papers offshore structures, corporate registries, court records, leaked documents
**Volume**: API-only, no bulk storage
**Storage**: Negligible (~100MB cache)

#### Backend — Two Services

**5A. ICIJ Offshore Leaks** (`backend/app/services/icij_service.py`)
- API: `https://offshoreleaks.icij.org/api/v1/search?q=NAME&type=entity`
- Returns: offshore entities, officers, intermediaries, addresses + relationships
- Links entities to Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks
- Cache: 24 hours per query (data is historical, doesn't change often)
- Rate limit: be respectful, 1 req/2s

**5B. OCCRP Aleph** (`backend/app/services/occrp_service.py`)
- API: `https://aleph.occrp.org/api/2/search?q=NAME`
- Returns: documents, corporate registries, court records, leaked files
- 1B+ records across 100+ datasets
- Auth: free API key from registration
- Cache: 24 hours per query

#### Frontend
- **Entity detail**: "Investigations" tab with two sub-sections:
  - **Offshore Leaks** — if ICIJ has matches: show connected offshore entities, jurisdictions, leak source (Panama/Pandora/Paradise Papers)
  - **OCCRP Records** — document matches from corporate registries, court records, leaked datasets
- **Visual**: Entity network graph gets new edge types — "offshore connection", "corporate link"
- **Default: OFF** (toggle in Sources, OCCRP needs free API key in Credentials)

#### Docs
- Document ICIJ and OCCRP integration
- Note: "ICIJ Offshore Leaks contains data from the Panama Papers, Paradise Papers, and Pandora Papers investigations. OCCRP Aleph is the world's largest open database of corporate and legal records."
- Privacy note: "These services are queried on-demand only. No bulk data is downloaded. Queries are cached locally for 24 hours."

---

### Phase 6: Cross-Source Auto-Correlation v2 (1 agent)

The real Palantir differentiator — automatically connecting dots across all data sources.

#### Backend
- Extend correlation engine (`backend/app/services/correlation_engine.py`)
- New correlation type: **"Multi-Source Fusion"**
  - Trigger: When events from 2+ different source types occur within configurable radius + time window
  - Example rule: "ACLED battle event + FIRMS thermal anomaly + GDELT media spike within 50km and 6 hours → generate FLASH alert with fused context"
  - Example rule: "Entity appears on sanctions list + entity mentioned in 5+ feed items in 24h → generate URGENT alert"
  - Example rule: "Ship position anomaly (AIS gap or loitering) near sanctioned port + entity mention → generate intel brief"
- New service: `backend/app/services/fusion_service.py`
  - Runs every 5 minutes
  - Queries recent events across all active data sources
  - Geospatial + temporal clustering (DBSCAN-style: configurable eps_km and eps_hours)
  - Generates "fused events" — synthetic events that combine evidence from multiple sources
  - Each fused event gets an auto-generated AI summary via briefs service
- New table: `fused_events` (id, component_event_ids[], component_source_types[], centroid_lat, centroid_lng, time_window_start, time_window_end, ai_summary, severity, created_at)

#### Frontend
- **Map layer**: "Fused Intelligence" — diamond markers for multi-source corroborated events
  - Color by severity: 🔴 FLASH / 🟠 URGENT / 🔵 ROUTINE
  - Click → detail panel showing all contributing sources with links
- **Dashboard widget**: "Intelligence Fusion" — recent auto-correlated events
- **Feed**: Fused events appear as special cards with multi-source badges

---

### Phase 7: Investigation Workspaces (1 agent)

The case management system — where analysts do deep work.

#### Backend
- Migration: `011_investigations.py`
  - `cases` table (id, user_id, title, description, classification, status [open/active/closed], created_at, updated_at)
  - `case_items` table (case_id, item_type [post/entity/event/fused_event/note/document], item_id, added_at, analyst_note, position_x, position_y)
  - `case_timeline` table (case_id, timestamp, event_type, description, added_by)
- Router: `backend/app/routers/cases.py`
  - CRUD for cases
  - Add/remove items to case
  - Case timeline
  - Export case as PDF report (extends existing reportlab PDF generator)
  - Share case (generate read-only link with expiry)

#### Frontend
- New page: `/cases` — case list with status filters
- New page: `/cases/:id` — investigation workspace
  - **Evidence board**: drag-and-drop pinned items (entities, posts, map locations, documents)
  - **Timeline**: chronological view of case events with analyst annotations
  - **Map view**: case-specific map showing only pinned locations
  - **Connections**: auto-generated graph of entity relationships within the case
  - **Export**: PDF report with all evidence, timeline, and analyst notes
- **Context menu everywhere**: Right-click any entity/post/event → "Add to Case" dropdown

---

## Agent Delegation Plan

### Wave A (parallel, no dependencies)
| Agent | Phase | Estimated Files |
|-------|-------|----------------|
| `agent-map-satellite` | Phase 1 (satellite tiles + Mapbox removal + docs) | ~6 files |
| `agent-acled` | Phase 2 (ACLED collector + map layer) | ~10 files |
| `agent-gdelt` | Phase 3 (GDELT services + map layer + entity enrichment) | ~8 files |

### Wave B (after Wave A — needs entity infrastructure)
| Agent | Phase | Estimated Files |
|-------|-------|----------------|
| `agent-sanctions` | Phase 4 (OpenSanctions matching + migration) | ~10 files |
| `agent-leaks` | Phase 5 (ICIJ + OCCRP entity enrichment) | ~8 files |

### Wave C (after Wave B — needs all data sources)
| Agent | Phase | Estimated Files |
|-------|-------|----------------|
| `agent-fusion` | Phase 6 (cross-source auto-correlation v2) | ~8 files |
| `agent-cases` | Phase 7 (investigation workspaces) | ~10 files |

---

## Source Toggle Behavior

All new data sources follow this pattern:

| Source | API Key Required | Default State | Enable Via |
|--------|-----------------|---------------|------------|
| ACLED | ✅ (free registration) | OFF | Credentials page → add key, then Sources → enable |
| GDELT DOC | ❌ | OFF | Sources page → toggle on |
| GDELT GEO (map layer) | ❌ | OFF | Map layers panel → toggle on |
| OpenSanctions | ❌ (bulk download) | OFF | Sources page → toggle on (downloads ~200MB) |
| ICIJ Offshore Leaks | ❌ | OFF | Sources page → toggle on |
| OCCRP Aleph | ✅ (free registration) | OFF | Credentials page → add key, then Sources → enable |
| Satellite tiles | ❌ | OFF | Map toolbar → tile switcher |

Existing free sources (FIRMS, Flights, Satellites, Frontlines) remain ON by default since they're already live.

---

## Storage Budget (100GB volume)

| Component | Current | After Sprint 13 | Notes |
|-----------|---------|-----------------|-------|
| PostgreSQL | ~500MB | ~3-4GB | ACLED history is the biggest addition |
| Media files | ~200MB | ~200MB | No change (media is per-Telegram-source) |
| Satellite tiles | 0 | 0 | Served from CDN, not stored |
| OpenSanctions cache | 0 | ~500MB | Local copy for fast matching |
| GDELT cache | 0 | ~50MB | Query results cached 15min |
| ICIJ/OCCRP cache | 0 | ~100MB | Entity lookups cached 24h |
| **Total** | **~700MB** | **~4-5GB** | Well within 100GB budget |

---

## Current: Sprint 14 — SIEM Query Engine & Field-Level Search

### Vision
Transform Orthanc from a feed viewer into a proper SIEM-style analytics platform. Every field in the data model becomes searchable, filterable, and visualisable. Users can write structured queries, build ad-hoc visualizations, and save them as dashboard widgets — like Splunk/OpenSearch but purpose-built for OSINT.

### Design Principles
- **Server-side filtering**: Filters push to the API, not client-side filter on 50 pre-loaded posts
- **Every field is searchable**: Any column in the posts/entities/events tables can be filtered on
- **Query results are visualisable**: Any result set can be rendered as table, chart, map, or timeline
- **Composable**: Filters, queries, and visualizations can be saved and shared
- **Progressive disclosure**: Simple filters for casual use, full query language for power users

---

### Phase 1: Server-Side Feed Filtering (1 agent — `agent-feed-filters`)

**Problem**: Current feed filtering is 100% client-side. Only 50 posts are loaded per page, and filters operate on that tiny window. Selecting "Telegram" might show 0 results because the loaded page is all RSS.

#### Backend Changes
- **Extend `GET /feed/`** — already accepts `source_types`, `keyword`, `date_from`, `date_to` but frontend doesn't use them
- **Add new filter params**:
  - `author` — ILIKE match on post author
  - `has_media` — boolean, filter posts with/without media attachments
  - `media_type` — filter by image/video/document
  - `has_geo` — boolean, filter posts with/without geo events
  - `location` — ILIKE on event place_name
  - `entity` — filter posts that mention a specific entity (join through entity_mentions)
  - `min_authenticity` / `max_authenticity` — float range on authenticity_score
  - `external_id` — exact match on external_id (for ACLED, etc.)
  - `sort` — `newest` (default), `oldest`, `relevance` (when keyword present)
- **Add `GET /feed/facets`** — returns available field values with counts:
  ```json
  {
    "source_types": [{"value": "telegram", "count": 341}, ...],
    "authors": [{"value": "AMK_Mapping", "count": 89}, ...],
    "media_types": [{"value": "image", "count": 60}, ...],
    "locations": [{"value": "Gaza", "count": 45}, ...],
    "entities": [{"value": "Iran", "count": 120, "type": "GPE"}, ...]
  }
  ```
  Accepts same filter params as `/feed/` so facets update as you filter (like Splunk's sidebar)
- **Add `total_count` response header** or wrap response in `{ items: [...], total: N, page: N }` for proper pagination display

#### Frontend Changes (`FeedTimeline.tsx`, `FeedFilters.tsx`, `feedStore.ts`)
- **Move ALL filtering server-side**: Pass filter params in API request instead of client-side `.filter()`
- **FeedFilters.tsx** — expand sidebar with new filter sections:
  - **Sources**: existing checkboxes (keep) + counts from facets API
  - **Author**: searchable dropdown populated from facets
  - **Media**: checkbox group (Has Image / Has Video / Has Document)
  - **Location**: searchable dropdown of known locations from facets
  - **Entity Mentions**: searchable entity picker (typeahead from `/entities?search=`)
  - **Authenticity**: range slider (0.0–1.0) for posts with authenticity scores
- **FeedTimeline.tsx** — remove client-side filter logic, re-fetch from API when filters change (debounced 300ms)
- **feedStore.ts** — extend `FeedFilters` interface with new fields, add `totalCount` state
- **Pagination indicator**: "Showing 1–50 of 1,247 posts" in timeline header
- **Active filter pills**: Show active filters as dismissible chips above the timeline

#### Files to modify:
- `backend/app/routers/feed.py` — extend params + new facets endpoint
- `backend/app/schemas/feed.py` — extend FeedFilter schema
- `frontend/src/stores/feedStore.ts` — extend filter state
- `frontend/src/components/feed/FeedFilters.tsx` — rebuild with new fields
- `frontend/src/components/feed/FeedTimeline.tsx` — remove client-side filtering, re-fetch on filter change
- `frontend/src/styles/feed.css` — new filter component styles

---

### Phase 2: Structured Query Language (1 agent — `agent-query-engine`)

Build a query bar that accepts structured queries against all Orthanc data, with autocomplete and syntax highlighting.

#### Query Syntax (OQL — Orthanc Query Language)
Simple, Splunk-inspired syntax:
```
source_type=telegram author="AMK*" content="drone strike"
| where timestamp > now() - 24h
| stats count by author
| sort -count
```

**Operators**:
- `field=value` — exact match
- `field="wildcard*"` — ILIKE match
- `field>value`, `field<value`, `field>=value` — comparison
- `field IN (a, b, c)` — set membership
- `NOT field=value` — negation
- `AND` / `OR` — boolean logic (AND is implicit between terms)

**Pipes** (post-processing):
- `| where CONDITION` — additional filter
- `| stats FUNC by FIELD` — aggregate (count, avg, sum, min, max, distinct_count)
- `| sort [-]FIELD` — sort (- for descending)
- `| top N FIELD` — top N values by count
- `| timechart span=1h count by source_type` — time-bucketed aggregation
- `| head N` — limit results
- `| table FIELD1, FIELD2, ...` — select specific fields for output

**Target tables** (optional prefix):
- `posts:` (default) — search posts
- `entities:` — search entities
- `events:` — search geo events
- `alerts:` — search triggered alerts

**Examples**:
```
source_type=telegram | stats count by author | sort -count
content="nuclear" | timechart span=6h count
entities: type=PERSON | top 20 name
events: place_name="Gaza" | stats count by source_type
source_type IN (rss, x) content="Iran" | stats count by source_type
```

#### Backend
- **New router**: `backend/app/routers/oql.py`
  - `POST /oql/execute` — parse OQL string, translate to SQL, execute, return results
  - `POST /oql/explain` — parse OQL, return the SQL it would execute (for debugging)
  - `GET /oql/schema` — return searchable fields with types for autocomplete
  - `GET /oql/history` — saved query history per user
  - `POST /oql/save` — save a named query
- **New service**: `backend/app/services/oql_parser.py`
  - Tokenizer + recursive descent parser for OQL syntax
  - Translates to SQLAlchemy queries (NOT raw SQL — prevents injection)
  - Validates field names against known schema
  - Handles pipes as post-processing transforms
  - `timechart` uses `date_trunc()` for bucketing
  - Returns typed result: `{ columns: [...], rows: [...], total: N, query_time_ms: N }`
- **Migration**: `014_saved_queries.py`
  - `saved_queries` table (id, user_id, name, query_text, description, visualization_config JSONB, is_pinned, created_at, updated_at)
  - `query_history` table (id, user_id, query_text, executed_at, row_count, duration_ms)

#### Frontend
- **Query bar component**: `frontend/src/components/query/QueryBar.tsx`
  - Full-width input with monospaced font
  - Syntax highlighting (field names blue, operators grey, values green, pipes orange)
  - Autocomplete dropdown: field names, operators, known values (from facets)
  - `Ctrl+Enter` to execute, `↑`/`↓` for history navigation
  - Error display with position indicator for syntax errors
- **Results panel**: `frontend/src/components/query/QueryResults.tsx`
  - **Table view** (default): sortable columns, row click → detail view
  - **JSON view**: raw JSON toggle for power users
  - Result count + query execution time
  - Export: CSV, JSON download
  - "Visualize" button → opens visualization builder (Phase 3)

#### Files:
- `backend/app/routers/oql.py` (~300 lines)
- `backend/app/services/oql_parser.py` (~500 lines)
- `backend/alembic/versions/014_saved_queries.py`
- `backend/app/models/query.py`
- `frontend/src/components/query/QueryBar.tsx`
- `frontend/src/components/query/QueryResults.tsx`
- `frontend/src/styles/oql.css`

---

### Phase 3: Visualization Builder (1 agent — `agent-viz-builder`)

Turn any query result into a chart, and optionally pin it to the dashboard.

#### Visualization Types
All rendered with raw SVG/Canvas (no external chart libs per project rules):

1. **Time Series** — line/area chart, `timechart` results
   - X axis: time buckets, Y axis: count/value
   - Multiple series support (e.g., count by source_type)
   - Hover tooltip with values
2. **Bar Chart** — horizontal/vertical bars from `stats count by FIELD`
   - Clickable bars → drill down to filtered results
3. **Pie/Donut** — proportion breakdown (e.g., posts by source_type)
4. **Stat Card** — single big number (e.g., `| stats count`)
   - With sparkline trend from last 7 periods
5. **Data Table** — enhanced sortable table with pagination
6. **Map** — if results have lat/lng, plot on MapLibre

#### Backend
- **Extend `POST /oql/execute`** response with `visualization_hint`:
  - If query uses `timechart` → suggest "timeseries"
  - If query uses `stats count by` → suggest "bar"
  - If query uses `top N` → suggest "bar" or "pie"
  - If results have lat/lng columns → suggest "map"
  - Otherwise → "table"

#### Frontend
- **Viz builder component**: `frontend/src/components/query/VizBuilder.tsx`
  - Viz type selector (icons: 📊 bar, 📈 line, 🍩 donut, 🔢 stat, 📋 table, 🗺️ map)
  - Auto-selects based on `visualization_hint`
  - Field mapping: drag columns to X axis, Y axis, group-by, color
  - Live preview as you configure
- **Chart components** (all raw SVG):
  - `TimeSeriesChart.tsx` — responsive SVG, auto-scaling axes, hover crosshair
  - `BarChart.tsx` — horizontal/vertical, click-to-drill
  - `DonutChart.tsx` — animated segments with legend
  - `StatCard.tsx` — big number + sparkline
- **Save to dashboard**: "Pin to Dashboard" button
  - Saves query + visualization config to `saved_queries` with `is_pinned=true`
  - Dashboard renders pinned queries as live widgets that auto-refresh
- **Saved queries page**: `/queries` — list of saved queries with run/edit/delete

#### Files:
- `frontend/src/components/query/VizBuilder.tsx`
- `frontend/src/components/charts/TimeSeriesChart.tsx`
- `frontend/src/components/charts/BarChart.tsx`
- `frontend/src/components/charts/DonutChart.tsx`
- `frontend/src/components/charts/StatCard.tsx`
- `frontend/src/components/query/SavedQueries.tsx`
- `frontend/src/styles/charts.css`
- `frontend/src/styles/oql.css` (extend)

---

### Phase 4: Integration & Polish (1 agent — `agent-query-integration`)

Wire everything together across the platform.

#### Global Query Bar
- Add collapsible query bar to the top of every page (below the nav)
- `Ctrl+/` hotkey to focus query bar from anywhere
- Results open in a slide-out panel or navigate to `/query` page

#### Feed → Query Bidirectional
- "Open as Query" button on feed filters → translates current filter state to OQL string
- Query results with post data → "View in Feed" link per row

#### Dashboard Widget Queries
- Each dashboard widget backed by a saved OQL query
- Default widgets ship with built-in queries:
  - Velocity: `posts: | timechart span=1h count`
  - Source Health: `posts: | stats count, max(timestamp) by source_type`
  - Trending Entities: `entities: | sort -mention_count | head 10`
- Users can add custom widgets from saved queries

#### Entity/Map Integration
- Entity detail page: "Query mentions" button → `posts: entity="EntityName"`
- Map: "Query this area" → `events: lat>X lat<Y lng>A lng<B`

#### Files:
- `frontend/src/components/layout/GlobalQueryBar.tsx`
- `frontend/src/components/dashboard/DashboardView.tsx` (extend with pinned query widgets)
- Minor modifications across entity, map, feed views

---

### Agent Delegation Plan

| Order | Agent | Phase | Key Deliverables | Est. Files |
|-------|-------|-------|-----------------|------------|
| 1 | `agent-feed-filters` | Phase 1 | Server-side filtering, facets API, expanded filter sidebar | ~6 files |
| 2 | `agent-query-engine` | Phase 2 | OQL parser, execute/explain/schema endpoints, query bar + results | ~8 files |
| 3 | `agent-viz-builder` | Phase 3 | SVG chart components, viz type picker, save-to-dashboard | ~8 files |
| 4 | `agent-query-integration` | Phase 4 | Global query bar, feed↔query bridge, dashboard widgets | ~6 files |

**Dependency chain**: Phase 1 → independent. Phase 2 → independent. Phase 3 → depends on Phase 2 (needs OQL results). Phase 4 → depends on all.

**Parallel plan**: Phases 1 and 2 in parallel (Wave A), then Phase 3 (Wave B), then Phase 4 (Wave C).

---

### Schema Reference (searchable fields for OQL)

**Posts** (`posts:` prefix):
| Field | Type | Description |
|-------|------|-------------|
| id | uuid | Post ID |
| source_type | string | telegram, x, rss, reddit, discord, shodan, webhook, firms, flight, ais, cashtag, acled |
| source_id | string | Source-specific identifier |
| author | string | Post author/channel |
| content | text | Post content body |
| timestamp | datetime | Original post time |
| ingested_at | datetime | When Orthanc ingested it |
| media_type | string | image, video, document, null |
| authenticity_score | float | 0.0–1.0 AI authenticity score |
| external_id | string | External system ID (ACLED data_id, etc.) |

**Entities** (`entities:` prefix):
| Field | Type | Description |
|-------|------|-------------|
| id | uuid | Entity ID |
| name | string | Entity name |
| type | string | PERSON, ORG, GPE, NORP, EVENT |
| mention_count | int | Total mentions across all posts |
| first_seen | datetime | First mention timestamp |
| last_seen | datetime | Most recent mention |

**Events** (`events:` prefix):
| Field | Type | Description |
|-------|------|-------------|
| id | uuid | Event ID |
| lat | float | Latitude |
| lng | float | Longitude |
| place_name | string | Geocoded location name |
| confidence | float | Geocoding confidence |
| precision | string | exact, city, region, country, continent |
| post_id | uuid | Associated post |

---

## Current: Sprint 15 — Source Expansion & New Connectors

### Context
Source count went from 18 → 68 (25 RSS, 13 X, 6 Telegram, 6 Reddit added).
This sprint builds new connector types and data pipelines for sources that can't be ingested with existing collectors.

### Phase 1: YouTube Transcript Collector (1 agent — `agent-youtube`)

Ingest press conferences, military briefings, analyst commentary from YouTube channels.

**Architecture:**
- New collector: `backend/app/collectors/youtube_collector.py`
- Uses `yt-dlp` to fetch video metadata + auto-generated captions (no download of video files)
- Configurable YouTube channel IDs or playlist URLs as sources
- Polls every 30 minutes for new videos
- Stores transcript as `Post.content`, video URL as `Post.source_id`
- Source type: `youtube`
- Add `yt-dlp` to Docker image (`pip install yt-dlp`)

**Key channels to support:**
| Channel | Focus |
|---------|-------|
| CSIS (Center for Strategic & International Studies) | Geopolitical analysis |
| Brookings Institution | Policy briefings |
| RUSI (Royal United Services Institute) | UK defence/security |
| Pentagon Press Briefings | Official US DoD |
| NATO Channel | Alliance operations |
| Wilson Center | Policy analysis |
| Carnegie Endowment | Nuclear/geopolitics |

**Implementation:**
- `yt-dlp --write-auto-subs --sub-lang en --skip-download --dump-json URL`
- Parse JSON for title, upload_date, description, auto_subtitles
- Extract subtitle text from VTT/SRT format
- Entity extraction on transcript text
- Store with `source_type='youtube'`, `author=channel_name`

**Files:**
- `backend/app/collectors/youtube_collector.py` (~200 lines)
- `backend/app/collectors/orchestrator.py` (wire in)
- `Dockerfile` (add yt-dlp)
- Sources page: add 'youtube' to source type dropdown

---

### Phase 2: FAA NOTAMs & Airspace Restrictions (1 agent — `agent-notams`)

Track temporary flight restrictions, military airspace activations, and GPS jamming NOTAMs.

**Architecture:**
- New service: `backend/app/services/notam_service.py`
- FAA NOTAM API: `https://notams.aim.faa.gov/notamSearch/` (free, no key)
- ICAO API alternative: `https://applications.icao.int/dataservices/` (free registration)
- Poll every 15 minutes
- Parse NOTAM text for location (lat/lng from Q-line), altitude, time window
- Create geo events from NOTAM coordinates
- Source type: `notam`
- Map layer: NOTAM markers (yellow triangles) with popup showing restriction details

**NOTAM categories to track:**
- TFRs (Temporary Flight Restrictions) — often indicate military ops
- Military exercise areas (NOTAM type M)
- GPS interference/jamming advisories
- Drone/UAS restrictions

**Files:**
- `backend/app/services/notam_service.py` (~250 lines)
- `backend/app/routers/layers.py` (add `/layers/notams` endpoint)
- `frontend/src/components/map/MapView.tsx` (add NOTAM layer toggle)

---

### Phase 3: Satellite Imagery Change Detection (1 agent — `agent-sentinel`)

Detect changes at key military/infrastructure sites using free Sentinel-2 imagery.

**Architecture:**
- New service: `backend/app/services/sentinel_service.py`
- Copernicus Data Space API (free, registration required): `https://dataspace.copernicus.eu/`
- Define watchlist of coordinates (military bases, ports, nuclear sites)
- Poll for new Sentinel-2 images (5-day revisit cycle)
- Compare sequential images using pixel difference (numpy)
- Flag significant changes (>threshold) as alerts
- Store change detection thumbnails in media directory

**Watchlist categories:**
- Russian military bases (Crimea, Kaliningrad, Syria)
- Iranian nuclear sites (Natanz, Fordow, Isfahan)
- North Korean launch facilities
- Key ports (Sevastopol, Tartus, Bandar Abbas)
- Energy infrastructure (pipelines, refineries)

**Files:**
- `backend/app/services/sentinel_service.py` (~300 lines)
- `backend/app/models/watchpoint.py` (lat, lng, name, radius, last_checked)
- Migration `015_watchpoints.py`
- `frontend/src/components/map/MapView.tsx` (watchpoint markers)
- `frontend/src/components/settings/WatchpointsPage.tsx` (CRUD for sites)

---

### Phase 4: EU/UK Sanctions Lists (1 agent — `agent-sanctions-eu`)

Extend sanctions screening beyond OpenSanctions to include direct EU/UK list ingestion.

**Architecture:**
- EU Consolidated List: `https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content`
- UK OFSI List: `https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv`
- Parse XML/CSV, normalize to entity records
- Cross-reference with existing entity database
- Flag matches as sanctions hits
- Add "Sanctions" tab to entity detail page

**Files:**
- `backend/app/services/eu_sanctions_service.py` (~200 lines)
- `backend/app/services/uk_sanctions_service.py` (~150 lines)
- `backend/app/routers/sanctions.py` (extend existing)

---

### Phase 5: Enhanced AIS/Maritime Intelligence (1 agent — `agent-maritime`)

Build maritime domain awareness features on top of existing AIS collector.

**New capabilities:**
- **Dark ship detection**: Flag vessels that go AIS-dark (stop transmitting) in sensitive areas
- **Sanctions vessel crosscheck**: Match ship MMSI/IMO against sanctions lists
- **Port call tracking**: Log when tracked vessels enter/leave key ports
- **Ship-to-ship transfer detection**: Alert when two vessels are stationary within 500m
- **Route deviation alerts**: Flag vessels deviating from normal trade routes

**Architecture:**
- Extend `backend/app/collectors/ais_collector.py` with history tracking
- New table: `vessel_tracks` (mmsi, timestamp, lat, lng, speed, heading)
- Migration `016_vessel_tracks.py`
- Dark ship detection: compare current poll vs last known position; if >6h gap, flag
- STS transfer: spatial query for vessels within 500m of each other + both speed < 2kt

**Files:**
- `backend/app/services/maritime_intel_service.py` (~400 lines)
- `backend/alembic/versions/016_vessel_tracks.py`
- `backend/app/models/vessel.py`
- `frontend/src/components/map/MapView.tsx` (vessel track history lines)

---

### Phase 6: Bluesky/Mastodon Firehose (1 agent — `agent-fediverse`)

Ingest posts from decentralized social networks.

**Architecture:**
- **Bluesky**: AT Protocol firehose via `wss://bsky.network/xrpc/com.atproto.sync.subscribeRepos`
  - Filter by followed accounts or keyword matching
  - No API key needed for public firehose
- **Mastodon**: Streaming API `wss://instance/api/v1/streaming/public`
  - Instance-specific, configure per instance
  - No API key for public timeline

**Files:**
- `backend/app/collectors/bluesky_collector.py` (~200 lines)
- `backend/app/collectors/mastodon_collector.py` (~150 lines)
- `backend/app/collectors/orchestrator.py` (wire in)
- Sources page: add 'bluesky', 'mastodon' types

---

### Agent Delegation Plan

| Order | Agent | Phase | Dependency | Est. Effort |
|-------|-------|-------|------------|-------------|
| 1 | `agent-youtube` | 1 | None | Medium |
| 2 | `agent-notams` | 2 | None | Medium |
| 3 | `agent-maritime` | 5 | None | Large |
| 1-3 run in parallel (Wave A) ||||
| 4 | `agent-sentinel` | 3 | None | Large |
| 5 | `agent-sanctions-eu` | 4 | None | Medium |
| 4-5 run in parallel (Wave B) ||||
| 6 | `agent-fediverse` | 6 | None | Medium |

All phases are independent — max parallelism is 3 agents in Wave A.

---

## Sprint 16 — Narrative Intelligence Engine

### Vision
Build an automated narrative tracking system that clusters coverage of the same events across all sources, detects how different media ecosystems frame them, extracts specific claims, correlates claims against hard evidence (FIRMS, satellite, ACLED, flight data), and builds source bias profiles over time. No open-source platform does this today.

### Core Concepts

**Narrative** = A cluster of posts from multiple sources about the same real-world event or topic within a time window. Example: 47 posts across 12 sources about an Iranian facility explosion.

**Stance** = How a specific post/source frames the narrative. Classifications:
- `confirming` — presents event as fact
- `denying` — says it didn't happen or is exaggerated
- `attributing` — assigns responsibility to a specific actor
- `contextualizing` — adds background/nuance
- `deflecting` — shifts focus to a different topic
- `speculating` — presents unverified theories

**Claim** = A specific factual assertion extracted from a post that can potentially be verified. Example: "Explosion occurred at 32.7°N 51.7°E" (verifiable via satellite/FIRMS).

**Evidence** = Hard data from non-editorial sources (FIRMS thermal, satellite imagery, ACLED events, flight tracking, seismic data) that confirms or contradicts a claim.

**Source Group** = Configurable grouping of sources by editorial alignment:
- `western` — BBC, NYT, Reuters, Al Jazeera English, Defense One, etc.
- `russian` — TASS, Rybar, Two Majors, Legitimny, etc.
- `chinese` — Xinhua, SCMP, etc.
- `ukrainian` — Ukrinform, Kyiv Independent, DeepState UA, etc.
- `osint` — Bellingcat, @Osinttechnical, @GeoConfirmed, @christogrozev, etc.
- `independent` — War on the Rocks, Foreign Policy, think tanks, etc.
- Custom groups configurable via UI

**Bias Profile** = Per-source aggregate of stance patterns over 30 days, producing:
- Alignment score (–1.0 Western ↔ +1.0 Eastern)
- Reliability score (% of claims later confirmed by evidence)
- Coverage bias (what topics they amplify vs ignore)
- Speed rank (how fast they cover breaking events)

---

### Phase 1: Data Model & Embedding Pipeline (1 agent — `agent-narrative-model`)

#### Migration `017_narratives.py`

```sql
-- Narrative clusters
CREATE TABLE narratives (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,                    -- AI-generated title
    summary TEXT,                           -- AI-generated summary
    status VARCHAR(20) DEFAULT 'active',    -- active, resolved, stale
    first_seen TIMESTAMPTZ NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL,
    post_count INTEGER DEFAULT 0,
    source_count INTEGER DEFAULT 0,
    divergence_score FLOAT DEFAULT 0,       -- 0=consensus, 1=max disagreement
    evidence_score FLOAT DEFAULT 0,         -- 0=unverified, 1=fully confirmed
    consensus VARCHAR(50),                  -- confirmed, disputed, denied, unverified
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Posts belonging to narratives (M:N — a post can belong to multiple narratives)
CREATE TABLE narrative_posts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    narrative_id UUID REFERENCES narratives(id) ON DELETE CASCADE,
    post_id UUID REFERENCES posts(id) ON DELETE CASCADE,
    stance VARCHAR(30),                     -- confirming, denying, attributing, etc.
    stance_confidence FLOAT,                -- 0-1 AI confidence
    stance_summary TEXT,                    -- one-line AI summary of this post's take
    assigned_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(narrative_id, post_id)
);

-- Extracted claims
CREATE TABLE claims (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    narrative_id UUID REFERENCES narratives(id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,               -- "Explosion at Isfahan facility"
    claim_type VARCHAR(30),                 -- factual, attribution, prediction, opinion
    location_lat FLOAT,                     -- if claim has spatial component
    location_lng FLOAT,
    entity_names TEXT[],                    -- entities referenced
    status VARCHAR(20) DEFAULT 'unverified', -- unverified, confirmed, debunked, disputed
    evidence_count INTEGER DEFAULT 0,
    first_claimed_at TIMESTAMPTZ,
    first_claimed_by TEXT,                  -- source that first made this claim
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Evidence linking claims to hard data
CREATE TABLE claim_evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID REFERENCES claims(id) ON DELETE CASCADE,
    evidence_type VARCHAR(30),              -- firms, satellite, acled, flight, seismic, osint_image
    evidence_source TEXT,                   -- "NASA FIRMS", "Sentinel-2", "OpenSky", etc.
    evidence_data JSONB,                    -- structured evidence payload
    supports BOOLEAN,                       -- true=confirms, false=contradicts
    confidence FLOAT,                       -- 0-1
    detected_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Source group definitions
CREATE TABLE source_groups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(50) NOT NULL UNIQUE,       -- "western", "russian", "osint"
    display_name VARCHAR(100),              -- "Western Media"
    color VARCHAR(7),                       -- hex color for charts
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Source ↔ group mapping
CREATE TABLE source_group_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_group_id UUID REFERENCES source_groups(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    UNIQUE(source_group_id, source_id)
);

-- Source bias profiles (computed weekly)
CREATE TABLE source_bias_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    alignment_score FLOAT,                  -- -1.0 (western) ↔ +1.0 (eastern)
    reliability_score FLOAT,                -- 0-1 (% claims confirmed)
    coverage_bias JSONB,                    -- {topic: amplification_score}
    speed_rank FLOAT,                       -- avg hours after event before first post
    stance_distribution JSONB,              -- {confirming: 0.4, denying: 0.1, ...}
    total_narratives INTEGER,
    total_claims INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX ix_narrative_posts_narrative ON narrative_posts(narrative_id);
CREATE INDEX ix_narrative_posts_post ON narrative_posts(post_id);
CREATE INDEX ix_claims_narrative ON claims(narrative_id);
CREATE INDEX ix_claim_evidence_claim ON claim_evidence(claim_id);
CREATE INDEX ix_source_bias_source ON source_bias_profiles(source_id);
CREATE INDEX ix_narratives_status ON narratives(status);
```

#### Post Embedding Pipeline

Add a lightweight embedding step to the post ingestion pipeline:
- After entity extraction, compute a text embedding for each post
- Use OpenRouter API: `POST /api/v1/embeddings` with a small model (e.g., `openai/text-embedding-3-small`)
- Store embedding in a new `post_embeddings` table: `(post_id UUID, embedding vector(1536))`
- Use pgvector extension for similarity search (add `CREATE EXTENSION vector` to migration)
- If no OpenRouter key, fall back to TF-IDF with scikit-learn (no external API needed)

**Files:**
- `backend/alembic/versions/017_narratives.py`
- `backend/app/models/narrative.py` (Narrative, NarrativePost, Claim, ClaimEvidence, SourceGroup, SourceGroupMember, SourceBiasProfile)
- `backend/app/models/__init__.py` (register)
- `backend/app/services/embedding_service.py` (~100 lines) — compute embeddings via OpenRouter or TF-IDF fallback

#### Seed Default Source Groups

On first run, seed these groups and auto-assign existing sources:

```python
DEFAULT_GROUPS = {
    "western": {
        "display_name": "Western Media",
        "color": "#3b82f6",
        "sources": ["BBC World", "NYT World", "Al Jazeera", "Defense One", "Foreign Policy",
                     "Breaking Defense", "Defense News", "Stars and Stripes", "The Diplomat",
                     "War on the Rocks", "The War Zone", "Naval News", "Kyiv Independent",
                     "Ukrinform", "@sentdefender", "@CENTCOM", "@Mr_Andrew_Fox", "@ASPI_org"]
    },
    "russian": {
        "display_name": "Russian/Eastern Media",
        "color": "#ef4444",
        "sources": ["TASS English", "Rybar (RU mil mapping)", "Two Majors",
                     "Intel Slava Z", "South Front", "Legitimny"]
    },
    "osint": {
        "display_name": "OSINT Community",
        "color": "#10b981",
        "sources": ["Bellingcat", "@Osinttechnical", "@UAWeapons", "@DefMon3",
                     "@GeoConfirmed", "@IntelCrab", "@ELINTNews", "@RALee85",
                     "@christogrozev", "@EliotHiggins", "@AricToler",
                     "@TankerTrackers", "@SquawkMilitary", "@AircraftSpots",
                     "AMK_Mapping Telegram", "AMK Mapping", "MES", "CyberspecNews"]
    },
    "independent": {
        "display_name": "Independent Analysis",
        "color": "#f59e0b",
        "sources": ["Arms Control Assoc", "Bulletin Atomic Scientists", "IAEA News",
                     "UN ReliefWeb", "r/geopolitics", "r/CredibleDefense"]
    },
    "cyber": {
        "display_name": "Cyber Intelligence",
        "color": "#8b5cf6",
        "sources": ["The Record", "BleepingComputer", "Krebs on Security",
                     "CyberScoop", "Cyberspec News", "r/OSINT"]
    },
    "maritime": {
        "display_name": "Maritime/Logistics",
        "color": "#06b6d4",
        "sources": ["gCaptain", "FreightWaves", "Splash247", "OilPrice", "Rigzone"]
    }
}
```

---

### Phase 2: Narrative Clustering Engine (1 agent — `agent-narrative-cluster`)

#### Background Service: `backend/app/services/narrative_engine.py`

Runs as a background task (like fusion_service), polls every 10 minutes.

**Clustering algorithm:**
1. Fetch all posts from last 24 hours that aren't yet assigned to a narrative
2. Compute pairwise cosine similarity of embeddings
3. Group posts with similarity > 0.75 into candidate clusters
4. For clusters with ≥3 posts from ≥2 sources: create a Narrative
5. For existing active narratives: check new posts against narrative centroid embedding, add if similarity > 0.70
6. Mark narratives as `stale` if no new posts in 12 hours

**If no embeddings available** (no OpenRouter key), fall back to:
- TF-IDF vectorization on post content
- Entity overlap (posts sharing 2+ entities = candidate cluster)
- Keyword overlap (Jaccard similarity > 0.4)

**Title/summary generation:**
- After clustering, use AI (grok-3-mini or OpenRouter) to generate a one-line narrative title and 2-sentence summary from the top 5 posts
- Update title/summary when new posts join the cluster

**Divergence scoring:**
- For each narrative, count unique stances per source group
- `divergence_score = 1 - (max_group_agreement / total_stances)`
- 0.0 = all sources agree, 1.0 = every group has a different take

**Files:**
- `backend/app/services/narrative_engine.py` (~500 lines)
- `backend/app/main.py` (start in lifespan)

---

### Phase 3: Stance & Claim Extraction (1 agent — `agent-narrative-analysis`)

#### Stance Classification Service: `backend/app/services/stance_classifier.py`

When a post is added to a narrative, classify its stance using AI:

```python
STANCE_PROMPT = """You are analyzing how a news source covers a specific event.

NARRATIVE: {narrative_title} — {narrative_summary}

POST from {source_name} ({source_group}):
{post_content}

Classify this post's stance toward the narrative:
- confirming: presents the event as factual
- denying: disputes the event occurred or its severity
- attributing: assigns blame/credit to a specific actor
- contextualizing: adds historical or political context
- deflecting: redirects attention to a different topic
- speculating: presents unverified theories

Respond with JSON:
{
    "stance": "<classification>",
    "confidence": <0.0-1.0>,
    "summary": "<one sentence describing this source's take>",
    "claims": [
        {"text": "<specific factual claim>", "type": "factual|attribution|prediction|opinion",
         "entities": ["entity1", "entity2"],
         "lat": <optional>, "lng": <optional>}
    ]
}
"""
```

- Batch process: when a narrative reaches 5+ posts, classify all at once
- Rate limit: max 10 AI calls per minute to avoid burning API credits
- Cache results: don't re-classify a post that's already been classified

#### Claim Deduplication
- Compare new claims against existing claims in the narrative using string similarity
- Merge duplicates (e.g., "explosion at Isfahan" and "blast near Isfahan nuclear plant" → same claim)
- Track which source first made each claim + timestamp

**Files:**
- `backend/app/services/stance_classifier.py` (~300 lines)
- `backend/app/services/claim_extractor.py` (~200 lines)

---

### Phase 4: Evidence Correlation (1 agent — `agent-narrative-evidence`)

#### Evidence Linker Service: `backend/app/services/evidence_linker.py`

For each claim with spatial data (lat/lng), automatically search for corroborating evidence:

**Evidence sources (already in Orthanc):**
| Source | Check | Supports If |
|--------|-------|-------------|
| FIRMS thermal | Query `/layers/firms` within 50km of claim location | Thermal anomaly within 6h of claim |
| ACLED events | Query ACLED data near claim location | Conflict event recorded |
| Flight data | Query `/layers/flights` for unusual patterns | Military aircraft in area |
| Ship data | Query `/layers/ships` for AIS anomalies | Naval activity detected |
| USGS seismic | Check earthquake feed for tremors at location | Seismic event correlates with explosion claim |
| DeepState frontlines | Check frontline proximity | Claim location matches active conflict zone |
| Other OSINT posts | Search posts with geolocated media near claim | Independent verification exists |

**Evidence scoring per claim:**
```
evidence_score = weighted_sum([
    (firms_match * 0.3),      # hard sensor data
    (acled_match * 0.2),      # conflict database
    (flight_anomaly * 0.15),  # flight patterns
    (osint_images * 0.2),     # geolocated imagery
    (seismic_match * 0.15),   # seismic data
]) / total_weight_of_available_sources
```

**Narrative-level evidence score** = average across all claims.

**Consensus determination:**
- `confirmed` — evidence_score > 0.7 AND divergence < 0.3
- `disputed` — evidence_score > 0.3 AND divergence > 0.5
- `denied` — multiple denying stances from non-aligned sources
- `unverified` — evidence_score < 0.3

**Files:**
- `backend/app/services/evidence_linker.py` (~400 lines)

---

### Phase 5: API Endpoints (1 agent — `agent-narrative-api`)

#### Router: `backend/app/routers/narratives.py`

```
GET  /narratives/                    — list active narratives (paginated, filterable by status/date/divergence)
GET  /narratives/{id}                — full narrative detail with posts, stances, claims, evidence
GET  /narratives/{id}/timeline       — hourly post count by source group
GET  /narratives/{id}/stances        — stance breakdown by source group
GET  /narratives/{id}/claims         — claims with evidence status
GET  /narratives/trending            — top 5 narratives by post volume in last 6h
POST /narratives/{id}/refresh        — force re-cluster and re-classify

GET  /source-groups/                 — list source groups with members
POST /source-groups/                 — create custom group
PUT  /source-groups/{id}             — update group
POST /source-groups/{id}/members     — add source to group
DELETE /source-groups/{id}/members/{source_id}

GET  /bias/profiles                  — all source bias profiles
GET  /bias/profiles/{source_id}      — single source bias history
GET  /bias/compass                   — data for bias compass scatter plot
POST /bias/compute                   — force recompute all bias profiles
```

**Files:**
- `backend/app/routers/narratives.py` (~400 lines)
- `backend/app/schemas/narrative.py` (~100 lines)
- `backend/app/main.py` (register router)

---

### Phase 6: Frontend — Narratives Page (1 agent — `agent-narrative-ui`)

#### New page: `/narratives` — Narrative Intelligence Dashboard

**Layout:**

```
┌─────────────────────────────────────────────────────────────────┐
│  NARRATIVE INTELLIGENCE          [Active ▾] [24h ▾] [⟳ Refresh]│
├──────────────────────────────────────┬──────────────────────────┤
│                                      │                          │
│  ┌──────────────────────────────┐    │  NARRATIVE DETAIL        │
│  │ 🔴 Iranian Facility Attack   │    │                          │
│  │ 47 posts · 12 sources        │    │  Title + AI Summary      │
│  │ Divergence: ██████████ HIGH  │    │                          │
│  │ Evidence:   ████████░░ 0.8   │    │  ┌─ STANCE BREAKDOWN ──┐ │
│  │ 🕐 2h ago                    │    │  │ Western    ████ CONF │ │
│  └──────────────────────────────┘    │  │ Russian    ██░░ DENY │ │
│  ┌──────────────────────────────┐    │  │ OSINT      ████ EVID │ │
│  │ 🟡 Black Sea Naval Buildup   │    │  │ Chinese    ░░░░ SILE │ │
│  │ 23 posts · 8 sources         │    │  └────────────────────┘ │
│  │ Divergence: ████░░░░░░ MED  │    │                          │
│  │ Evidence:   ██████░░░░ 0.6   │    │  ┌─ CLAIMS ────────────┐│
│  │ 🕐 5h ago                    │    │  │ ✅ Explosion at site  ││
│  └──────────────────────────────┘    │  │ ⏳ "Israeli strike"   ││
│  ┌──────────────────────────────┐    │  │ ❌ "No casualties"    ││
│  │ 🟢 NATO Exercise Baltic      │    │  └─────────────────────┘│
│  │ 15 posts · 6 sources         │    │                          │
│  │ Divergence: ██░░░░░░░░ LOW  │    │  ┌─ TIMELINE ──────────┐│
│  │ Evidence:   ██████████ 1.0   │    │  │  ╱╲    [bar chart   ││
│  │ 🕐 12h ago                   │    │  │ ╱  ╲   by source    ││
│  └──────────────────────────────┘    │  │╱    ╲  group/hour]  ││
│                                      │  └─────────────────────┘│
│                                      │                          │
│                                      │  ┌─ EVIDENCE ──────────┐│
│                                      │  │ 🔥 FIRMS: thermal    ││
│                                      │  │ ✈ Flights: mil A/C   ││
│                                      │  │ 📡 Sentinel: change   ││
│                                      │  └─────────────────────┘│
├──────────────────────────────────────┴──────────────────────────┤
│  BIAS COMPASS                                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Reliable                                      │  │
│  │                 │                                          │  │
│  │  @GeoConfirmed ●│  ● Bellingcat                           │  │
│  │         BBC ●   │      ● NYT                              │  │
│  │                 │                                          │  │
│  │  Western ───────┼──────── Eastern                         │  │
│  │                 │                                          │  │
│  │                 │          ● TASS                          │  │
│  │                 │    ● Rybar                               │  │
│  │              Unreliable                                    │  │
│  └───────────────────────────────────────────────────────────┘  │
│  Sources positioned by alignment (X) and reliability (Y)         │
└──────────────────────────────────────────────────────────────────┘
```

#### Components:

**`NarrativesView.tsx`** — Main page layout
- Left panel: scrollable narrative card list with search/filter
- Right panel: selected narrative detail
- Bottom panel: bias compass (collapsible)

**`NarrativeCard.tsx`** — List item
- Title, post count, source count
- Divergence bar (green=consensus → red=divergence)
- Evidence bar (empty=unverified → full=confirmed)
- Time since last update
- Status badge (Active/Resolved/Stale)

**`NarrativeDetail.tsx`** — Full detail view
- Tabs: Overview | Stances | Claims | Timeline | Sources
- **Overview**: AI summary, consensus status, divergence/evidence scores
- **Stances**: Grouped by source group, each post's stance + one-line summary, color-coded
- **Claims**: Table of extracted claims with evidence status icons (✅❌⏳), click to see evidence
- **Timeline**: SVG stacked bar chart showing post volume per source group per hour
- **Sources**: Which sources covered this, which didn't (silence detection)

**`BiasCompass.tsx`** — SVG scatter plot
- X axis: –1.0 (Western-aligned) ↔ +1.0 (Eastern-aligned)
- Y axis: 0.0 (Unreliable) ↔ 1.0 (Reliable)
- Each source as a colored dot (color = source group)
- Hover shows source name, scores, stance distribution
- Click navigates to source's full bias profile

**`SourceBiasProfile.tsx`** — Source detail
- Historical alignment score over time (line chart)
- Stance distribution pie chart
- List of narratives this source has covered with their stances
- "Coverage gaps" — narratives they haven't covered

#### Styles: `frontend/src/styles/narratives.css`
- Narrative cards: subtle left border color by divergence level
- Stance badges: color-coded (green=confirming, red=denying, blue=contextualizing, orange=attributing, gray=deflecting, purple=speculating)
- Evidence icons: ✅ green, ❌ red, ⏳ amber
- Bias compass: quadrant labels, grid lines, source dots with group colors
- All CSS variables from globals.css

**Files:**
- `frontend/src/components/narratives/NarrativesView.tsx`
- `frontend/src/components/narratives/NarrativeCard.tsx`
- `frontend/src/components/narratives/NarrativeDetail.tsx`
- `frontend/src/components/narratives/BiasCompass.tsx`
- `frontend/src/components/narratives/SourceBiasProfile.tsx`
- `frontend/src/styles/narratives.css`
- `frontend/src/App.tsx` (add `/narratives` route)
- Sidebar: add "Narratives" nav item with 🔍 icon under ANALYSIS section

---

### Phase 7: Integration & Dashboard Widget (1 agent — `agent-narrative-integration`)

Wire narrative intelligence into the rest of the platform:

**Dashboard widget:**
- "Trending Narratives" card showing top 3 active narratives with divergence indicators
- Replaces or supplements existing "Trending Entities" widget

**Feed integration:**
- Each feed item shows a "📖 Part of: [Narrative Title]" link if it belongs to a narrative
- Click navigates to `/narratives?id=NARRATIVE_ID`

**Entity integration:**
- Entity detail page: "Narratives" tab showing all narratives mentioning this entity
- Stance breakdown for this entity across source groups

**Map integration:**
- Narrative layer: show narrative clusters on map where claims have lat/lng
- Color-coded by consensus status (green=confirmed, yellow=disputed, red=denied)

**Alert integration:**
- New alert condition: `narrative_divergence` — trigger when a narrative's divergence score exceeds threshold
- New alert condition: `source_silence` — trigger when a source group hasn't covered a narrative that others have

**OQL integration:**
- New target table: `narratives:` — query narratives by status, divergence, evidence_score
- Example: `narratives: divergence_score > 0.7 | sort -post_count`

**Files:**
- `frontend/src/components/dashboard/DashboardView.tsx` (add widget)
- `frontend/src/components/feed/FeedItem.tsx` (add narrative link)
- `frontend/src/components/entities/EntityDetail.tsx` (add Narratives tab)
- `frontend/src/components/map/MapView.tsx` (add narrative layer)
- `backend/app/services/correlation_engine.py` (add narrative alert conditions)
- `backend/app/services/oql_parser.py` (add narratives table)

---

### Agent Delegation Plan

| Order | Agent | Phase | Key Deliverables | Dependency |
|-------|-------|-------|-----------------|------------|
| 1 | `agent-narrative-model` | 1 | Migration, models, embedding service, seed groups | None |
| 2 | `agent-narrative-cluster` | 2 | Clustering engine, background task | Phase 1 |
| 3 | `agent-narrative-analysis` | 3 | Stance classifier, claim extractor | Phase 2 |
| 4 | `agent-narrative-evidence` | 4 | Evidence linker, scoring | Phase 3 |
| 5 | `agent-narrative-api` | 5 | REST endpoints, schemas | Phase 4 |
| 6 | `agent-narrative-ui` | 6 | Full frontend page, bias compass | Phase 5 |
| 7 | `agent-narrative-integration` | 7 | Dashboard, feed, map, alerts, OQL | Phase 6 |

**Execution**: Strictly sequential — each phase builds on the previous.
Phase 1 can start immediately. Estimated total: 7 agent runs.

**AI cost estimate**: Stance classification + claim extraction uses ~500 tokens per post. At 100 posts/narrative, ~50k tokens per narrative. With grok-3-mini at ~$0.001/1k tokens, ~$0.05 per narrative analyzed. Budget ~$5-10/day at full ingestion volume.

---

## Future Roadmap (Post Sprint 16)

- **Cyber OSINT**: VirusTotal, CVE/NVD, WHOIS/DNS — tie Shodan findings to vulnerabilities
- **SEC EDGAR**: Corporate filings, insider trades — extend financial intelligence
- **3D Globe**: CesiumJS for satellite/aircraft visualization
- **Email ingestion**: IMAP collector for tip lines
- **Plugin framework**: Standardized interface for community-contributed collectors
- **Multi-user teams**: Shared cases, role-based access
- **Narrative predictions**: Use historical narrative patterns to predict escalation
- **Counter-narrative detection**: Identify coordinated inauthentic messaging campaigns

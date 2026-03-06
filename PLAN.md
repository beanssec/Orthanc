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

## Future Roadmap (Post Sprint 13)

- **Cyber OSINT**: VirusTotal, CVE/NVD, WHOIS/DNS — tie Shodan findings to vulnerabilities
- **SEC EDGAR**: Corporate filings, insider trades — extend financial intelligence
- **3D Globe**: CesiumJS for satellite/aircraft visualization
- **Bluesky/Mastodon**: Open social protocol firehose ingestion
- **Email ingestion**: IMAP collector for tip lines
- **Plugin framework**: Standardized interface for community-contributed collectors
- **Multi-user teams**: Shared cases, role-based access

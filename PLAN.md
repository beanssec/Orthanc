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

---

## Current: Wave 3 — Advanced Features

### 3.1 Investigation/Case Management
- Analyst workspaces with pinned entities, posts, map views
- Case timeline with evidence chain
- Shareable case reports

### 3.2 Connector Plugin Framework
- Standardized plugin interface for community-contributed data sources
- Plugin registry, hot-reload, configuration schema

---

## Future Roadmap

- 3D globe (CesiumJS) for satellites and aircraft
- More connectors: YouTube transcripts, NOAA/FAA NOTAMs, paste sites
- Reverse image search integration
- Video frame analysis for authenticity
- Multi-user team features
- Email ingestion (IMAP)
- Custom API connectors (user-defined)

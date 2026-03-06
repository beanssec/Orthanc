# Orthanc — Product Specification

## Overview
A self-hosted OSINT intelligence platform for conflict analysts, traders, journalists and researchers. Aggregates feeds from Telegram, X, RSS/news, Reddit, Discord, Shodan, and more into a unified analyst workspace with geospatial mapping, entity analysis, AI-powered intelligence, financial correlation, media verification, and multi-level alerting.

**Owner:** Nick
**Status:** Active development — core platform complete, expanding features
**Location:** `/mnt/data/projects/overwatch`
**License:** MIT (open source)

---

## Core User Stories

1. As an analyst, I can see a live feed of posts from my configured sources, updating in near-real-time (SIEM-style)
2. As an analyst, I can see geolocated events plotted on an interactive tactical map with multiple intelligence layers
3. As an analyst, I can filter the feed and map by keyword, source, date range, and saved presets
4. As an analyst, I can configure multi-level alerts (keyword, velocity, correlation, geo-proximity, silence detection)
5. As an analyst, I can manage data sources with per-source configuration (media download settings, polling intervals)
6. As an analyst, I can ask natural language questions and get AI-analyzed answers from my intelligence data
7. As an analyst, I can track entities across sources, explore their relationships, and find connection paths
8. As an analyst, I can upload documents (PDF/DOCX/TXT) and have them automatically processed through the NER pipeline
9. As an analyst, I can verify media authenticity with AI-powered detection of generated/manipulated content
10. As an analyst, I can track financial instruments and correlate OSINT events with market movements
11. As an analyst, I can bookmark, tag, and annotate any item in the platform for future reference
12. As an analyst, I can generate AI intelligence briefs on demand or on schedule, and export them as PDF reports

---

## Data Sources

### Active Collectors (12)
| Source | Auth Required | Method |
|--------|--------------|--------|
| RSS/News | None | feedparser polling |
| X/Twitter | xAI API key | Grok chat completions |
| Telegram | API ID + hash + phone auth | Telethon (real-time + backfill) |
| Reddit | None | Public JSON API |
| Discord | Bot token | Gateway WebSocket |
| Shodan | API key | REST API polling |
| Webhooks | None | POST /webhook/ingest |
| Documents | None | Upload via UI (PDF/DOCX/TXT/MD/CSV) |
| FIRMS | None | NASA fire data |
| Flights | None | OpenSky Network |
| Ships/AIS | API key | aisstream.io |
| Satellites | None | CelesTrak TLEs + sgp4 |

### Additional Data Collectors
| Source | Method |
|--------|--------|
| Market data | Yahoo Finance (yfinance) |
| Cashtag monitoring | xAI Grok ($TICKER mentions) |

### Architecture Principle
Every source is a **collector** with a standard interface:
- `start(user_id, sources)` / `stop()`
- Outputs normalized `Post` objects
- Self-manages polling/streaming/auth
- User adds sources via UI, platform handles the rest
- Collectors run as in-process async tasks (not separate containers)

---

## Intelligence Features

### Entity Extraction & Analysis
- spaCy NER: PERSON, ORG, GPE, NORP, EVENT
- Entity deduplication and canonical name linking
- Entity timeline (chronological mention history)
- Link/path analysis (BFS shortest path via co-occurrence)
- Typed relationships (commands, funds, opposes, sanctions, allied_with, etc.) with confidence scoring
- Force-directed entity network graph with path highlighting
- Extensible entity properties (key-value)
- Entity-to-ticker mapping for financial correlation

### AI Intelligence
- Multi-model briefs (xAI Grok, Claude, GPT-4o, Gemini, Mistral, Llama via OpenRouter)
- Brief scheduling (hourly/daily/weekly) with history
- PDF intelligence report export (reportlab, classification banners)
- Natural language querying ("What's happening with Iran?") → structured results + AI summary
- Translation (auto-detect language + AI translate)

### Media Verification
- Opt-in media download from Telegram (separate image/video toggles, configurable size limits)
- EXIF metadata extraction (camera, GPS, software, timestamps)
- AI authenticity analysis via vision models (Grok Vision / GPT-4o)
- Authenticity scoring (0.0–1.0) with verdict and reasoning
- SHA256 file hashing, thumbnail generation

### Alerting (5 types)
1. **Keyword Match** — regex/keyword on ingest
2. **Entity Velocity** — mention rate exceeds baseline
3. **Multi-Stage Correlation** — OSSIM-style directives with time windows
4. **Geo-Proximity** — events within radius of location (haversine)
5. **Silence Detection** — entity/source goes quiet beyond expected interval
- Delivery: in-app, Telegram, webhook
- Severity: FLASH / URGENT / ROUTINE

### Financial Intelligence
- Portfolio tracking with live quotes (Yahoo Finance)
- Market watchlist (indices, commodities, forex, crypto)
- Cashtag ($TICKER) monitoring from X
- Opportunity scanner: entity spike detection → ticker mapping → AI signals
- Bloomberg Terminal aesthetic

### Collaboration
- Notes on any object (entity, post, event)
- Bookmarks across all data types
- User-defined tags (searchable)

---

## Map Layers

| Layer | Source | Auth |
|-------|--------|------|
| OSINT Events | Internal (geocoded posts) | None |
| Flights | OpenSky Network | None |
| Ships/AIS | aisstream.io | API key |
| FIRMS Thermal | NASA | None |
| Frontlines | DeepState, AMK, Suriyak, UA Control Map, Playfra, Radov | None |
| Satellites | CelesTrak + sgp4 | None |
| Sentiment Heatmap | Internal (keyword scoring) | None |

---

## UI Design

- Full screen — optimized for 4K monitors
- Dark professional theme (custom CSS, no frameworks)
- Dense information layout — analyst-grade
- Mobile responsive (tested on Pixel 7 Pro)
- Colour palette:
  - Background: #0a0e1a | Surface: #111827 | Border: #1f2937
  - Accent: #3b82f6 | Alert: #ef4444 | Success: #10b981
  - Text: #f9fafb / #9ca3af
- MapLibre GL with CartoDB dark-matter tiles (free, no API key)
- Monospaced font for financial numbers (JetBrains Mono / Fira Code)
- No inline styles (except dynamic values), no Tailwind/CSS-in-JS
- No external chart/graph libraries (raw SVG/Canvas)

### Pages (14)
Dashboard, Feed, Map, Entities, Briefs, Documents, Ask AI, Portfolio, Markets, Signals, Bookmarks, Sources, Credentials, Alerts

---

## Security Model

### Per-User Credential Encryption (Option C)
- No API keys in config files — entered via web UI
- Password → Argon2id key derivation → per-user encryption key
- All credentials encrypted at rest with Fernet
- On login: decrypted into memory for active collectors
- On logout/restart: keys wiped from memory
- JWT tokens in Zustand in-memory store only (not localStorage)
- Server restart = user must log back in (by design, not a bug)

---

## Stack

- **Backend:** Python 3.12 + FastAPI (async)
- **Database:** PostgreSQL 16 + PostGIS
- **Frontend:** React 18 + Vite + TypeScript
- **Maps:** MapLibre GL JS + CartoDB dark-matter tiles
- **NER:** spaCy en_core_web_sm
- **Geocoding:** Nominatim (free, rate-limited)
- **Satellites:** CelesTrak + sgp4
- **PDF:** reportlab
- **Media:** Pillow (thumbnails/EXIF)
- **Real-time:** WebSockets
- **Deployment:** Docker Compose (3 containers)

---

## Database

9 Alembic migrations, tables include:
- users, credentials, posts, sources, events, alerts, alert_hits
- entities, entity_mentions
- briefs
- holdings, quotes, entity_ticker_map, signals
- alert_rules, alert_events
- entity_relationships, entity_properties
- user_notes, user_bookmarks, user_tags

---

## Roadmap

- [ ] Investigation/case management (analyst workspaces)
- [ ] Connector plugin framework (community-extensible)
- [ ] 3D globe (CesiumJS)
- [ ] More connectors: YouTube, NOAA/FAA NOTAMs, paste sites
- [ ] Reverse image search
- [ ] Video frame analysis

# ▣ Orthanc

**Open source intelligence for everyone.**

Orthanc is a self-hosted OSINT intelligence platform that aggregates data from dozens of sources into a unified analyst workspace. Live feeds, geospatial mapping, entity extraction, AI-powered analysis, financial intelligence, media verification, sanctions matching, leaked data enrichment, cross-source fusion, and investigation workspaces — all running on your own hardware.

Named after the tower that held the Palantír. The seeing stone shouldn't be locked in a corporate vault.

![License](https://img.shields.io/badge/license-MIT-blue)
![Docker](https://img.shields.io/badge/docker-compose-blue)
![Python](https://img.shields.io/badge/python-3.12-green)
![React](https://img.shields.io/badge/react-18-blue)

---

## What It Does

### 📡 Multi-Source Intelligence Collection
- **RSS/News** — BBC, Al Jazeera, Reuters, any feed
- **X/Twitter** — Monitor accounts and hashtags via xAI API
- **Telegram** — Channel monitoring via Telethon with optional media capture
- **Reddit** — Subreddit tracking (no auth needed)
- **Discord** — Server/channel monitoring
- **Shodan** — Infrastructure scanning and exposure detection
- **Webhooks** — Ingest from any source via POST
- **Document Upload** — PDF, DOCX, TXT, MD, CSV ingestion with automatic NER
- **ACLED** — Armed conflict events (battles, protests, riots, violence) with structured actor data
- **FIRMS** — NASA thermal anomaly detection for conflict zones
- **Flight Tracking** — Live aircraft via OpenSky Network
- **Ship Tracking** — AIS vessel monitoring
- **Satellite Tracking** — ISS, military, weather satellites via CelesTrak

### 📰 Global Media Intelligence (GDELT)
- **Article search** — Query global news coverage across 65 languages via GDELT DOC API
- **Media attention heatmap** — Map layer showing where the world is talking about any topic
- **Entity enrichment** — "Global Media" tab on entities shows worldwide coverage
- Keyword presets: conflict, nuclear, terrorism, protest, cyber attack
- On-demand queries with 15-minute caching, no API key required

### 🔴 Sanctions & Watchlist Matching (OpenSanctions)
- **350k+ entities** from OFAC SDN, EU sanctions, UN sanctions, Interpol, PEPs
- **Automatic fuzzy matching** — trigram similarity against your extracted entities
- Strong match (≥90%), possible match (≥70%) with dataset attribution
- Bulk dataset download (~200MB), daily refresh, opt-in
- Entity detail shows sanctions badges with links to OpenSanctions profiles

### 🔎 Leaked Data & Corporate Intelligence
- **ICIJ Offshore Leaks** — Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks
- **OCCRP Aleph** — 1B+ records: corporate registries, court records, leaked documents
- "Investigations" tab on entities shows offshore connections and OCCRP records
- Color-coded dataset badges (Panama=red, Paradise=purple, Pandora=blue)
- No bulk download — on-demand queries cached 24 hours

### ◆ Cross-Source Intelligence Fusion
- **Automatic multi-source correlation** — detects when events from 2+ different sources occur within 50km and 6 hours
- Severity classification: 🔴 FLASH (4+ sources) / 🟠 URGENT (3 sources) / 🔵 ROUTINE (2 sources)
- Fused events appear as diamond markers on the map
- Background scanning every 5 minutes
- Dashboard widget shows recent corroborated events

### 🕵️ Investigation Workspaces
- **Case management** — create investigations with title, description, classification level
- **Evidence board** — pin posts, entities, notes, and map markers to a case
- **Case timeline** — automatic audit trail of all case mutations
- **Case map** — embedded map showing only case-related locations
- **"Add to Case"** — context action on feed items and entity details
- **PDF export** — export full case as intelligence report
- Status workflow: Open → Active → Closed → Archived

### 🔍 Global Search & Natural Language Querying
- **Unified search** across posts, entities, events, and briefs (Ctrl+K)
- **Natural language queries** — ask questions in plain English and get AI-analyzed answers
- Instant search dropdown with debounced results

### 🗺️ Tactical Map
- MapLibre GL with dark CartoDB tiles (free, no API key)
- **Base layer switcher** — Dark / 🛰️ Satellite / 🗺️ Hybrid (Esri World Imagery, free)
- Clustered OSINT events with precision filtering
- Click any cluster → browse events → click to inspect full detail in side panel

**9 intelligence layers (all toggleable):**

| Layer | What It Shows | Source | Auth Required | Default |
|-------|--------------|--------|---------------|---------|
| **OSINT Events** | Geolocated posts from your feeds | Internal (NER + geocoding) | No | ON |
| **Frontlines** | Ukraine territorial control + battle events | 6 mapping sources | No | ON |
| **Flights** | Live aircraft with military/civilian filtering | OpenSky Network | No | ON |
| **Ships** | Vessel positions with military/civilian filtering | AIS (aisstream.io) | API key | OFF |
| **FIRMS** | Thermal anomalies / fire hotspots | NASA FIRMS | No | ON |
| **Satellites** | ISS, military, weather satellite positions | CelesTrak + sgp4 | No | ON |
| **Sentiment** | Keyword-based sentiment heatmap | Internal | No | OFF |
| **Conflict Events** | ACLED battles, protests, riots, violence | ACLED | API key | OFF |
| **Media Attention** | GDELT global news heatmap by keyword | GDELT | No | OFF |
| **Fused Intelligence** | Multi-source corroborated events | Internal fusion engine | No | OFF |

### 🧠 AI Intelligence Briefs
- Generate structured intelligence briefs from collected data
- **Topic filtering** — scope briefs to "Ukraine", "cyber", "finance", etc.
- **Source filtering** — include only RSS, Telegram, ACLED, etc.
- **Custom prompts** — override the analyst persona ("You are a cyber threat analyst…")
- 9+ model support (xAI Grok, Claude, GPT-4o, Gemini, Mistral, Llama via OpenRouter)
- Scheduled briefs with full history and PDF export

### 🔗 Entity Extraction, Linking & Analysis
- Automatic NER via spaCy (PERSON, ORG, GPE, NORP, EVENT)
- **Entity timeline** — chronological view of all mentions
- **Link/path analysis** — BFS shortest-path between entities
- **Typed relationships** — commands, funds, allied_with, opposes, sanctions, member_of
- **Entity network graph** — force-directed canvas visualization
- **Sanctions tab** — automatic matching against 350k+ watchlist entries
- **Investigations tab** — ICIJ offshore leaks + OCCRP records
- **Global Media tab** — GDELT worldwide news coverage

### 📷 Media Capture & Verification
- **Opt-in media download** from Telegram — separate toggles for images vs videos
- **EXIF metadata extraction** — camera model, GPS, timestamps, software detection
- **AI-powered authenticity analysis** — GPT-4o / Grok Vision detect AI-generated content
- Authenticity badges: 🟢 Likely Real / 🟡 Uncertain / 🔴 Possibly AI-Generated

### 💰 Financial Intelligence
- Portfolio tracking with live market data (Yahoo Finance)
- Cashtag ($TICKER) monitoring from X/Twitter
- **OSINT → Market signal correlation** — entity spikes mapped to affected tickers
- Bloomberg Terminal aesthetic with monospaced numbers

### 🚨 Correlation Alert Engine
- **Keyword Match** — Regex/keyword match on ingest
- **Entity Velocity** — Entity mention rate exceeds baseline
- **Multi-Stage Correlation** — OSSIM-style with time windows
- **Geo-Proximity** — Events within configurable radius
- **Silence Detection** — Source/entity goes unexpectedly quiet

### 🔒 Security
- Per-user credential encryption (Argon2id + Fernet)
- Zero-knowledge design — server never stores encryption keys on disk
- JWT authentication with in-memory token storage

### 📱 Mobile Responsive
- Hamburger sidebar, bottom-sheet panels, touch targets
- Collapsible sidebar navigation (icon-only mode)

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- 2GB+ RAM recommended
- No API keys required to start (RSS + Reddit + flights + satellites work without auth)

### 1. Clone & Configure

```bash
git clone https://github.com/beanssec/Orthanc.git
cd Orthanc
cp .env.example .env
```

### 2. Launch

```bash
docker compose up -d
```

Three containers start:
- **orthanc-postgres** — PostgreSQL 16 + PostGIS (port 5433)
- **orthanc-backend** — FastAPI Python backend (port 8000)
- **orthanc-frontend** — React + Vite frontend (port 3001)

### 3. Open & Register

Navigate to `http://localhost:3001` → Register → Setup wizard.

### 4. Add Data Sources

Go to **Settings → Credentials** to add API keys:

| Provider | What You Get | Cost |
|----------|-------------|------|
| xAI (Grok) | X/Twitter monitoring + AI briefs | Free credits on signup |
| Telegram | Channel monitoring + media capture | Free (needs phone) |
| OpenRouter | 7+ AI models for briefs/queries/verification | Pay-per-use (~$0.01/brief) |
| ACLED | Structured conflict event data | Free (register at developer.acleddata.com) |
| OCCRP | 1B+ corporate/legal/leaked records | Free (register at aleph.occrp.org) |
| Shodan | Infrastructure scanning | Free tier: 100 queries/month |
| Discord | Server monitoring | Free (bot token) |
| AIS | Ship tracking | Free tier available |

**No API key needed:** RSS, Reddit, flights, satellites, FIRMS, GDELT, ICIJ, OpenSanctions, frontlines.

### 5. Optional: Enable Enrichment Sources

All enrichment sources default to **OFF**. Enable them in **Settings → Sources**:

| Source | What It Adds | Storage Impact |
|--------|-------------|----------------|
| ACLED | Conflict events on the map | ~500MB/year |
| GDELT | Global media attention heatmap | ~50MB cache |
| OpenSanctions | Sanctions matching on entities | ~500MB (bulk download) |
| ICIJ/OCCRP | Leaked data enrichment on entities | ~100MB cache |

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Frontend   │◄───►│   Backend    │◄───►│  PostgreSQL  │
│  React/Vite  │     │   FastAPI    │     │  + PostGIS   │
│  Port 3001   │     │  Port 8000   │     │  Port 5433   │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴───┐ ┌─────┴─────┐
        │ Collectors │ │Fusion │ │ Enrichment│
        │            │ │Engine │ │ Services  │
        │ RSS/X/TG   │ │       │ │           │
        │ Reddit     │ │ 5min  │ │ Sanctions │
        │ Discord    │ │ scan  │ │ GDELT     │
        │ Shodan     │ │       │ │ ICIJ      │
        │ ACLED      │ │ 50km  │ │ OCCRP     │
        │ FIRMS      │ │ 6hr   │ │           │
        │ Flights    │ │window │ │ On-demand │
        │ Ships/Sats │ │       │ │ + cached  │
        └───────────┘ └───────┘ └───────────┘
```

---

## Pages

| Page | Description |
|------|-------------|
| **Dashboard** | KPI strip, velocity chart, source health pills, trending entities, geo hotspots, alerts, fusion events |
| **Feed** | 3-column SIEM-style live timeline with WebSocket, infinite scroll, source/time filters |
| **Map** | Full-screen tactical map with 10 layer types, satellite imagery, frontlines |
| **Entities** | Entity table with detail view: timeline, relationships, graph, sanctions, investigations, media |
| **Briefs** | AI brief generation with topic/source filters, custom prompts, scheduling, PDF export |
| **Cases** | Investigation workspaces with evidence boards, timelines, case maps, PDF export |
| **Documents** | Drag-and-drop upload with automatic NER processing |
| **Ask AI** | Natural language query interface |
| **Portfolio** | Holdings tracker with live quotes |
| **Markets** | Watchlist with real-time data |
| **Signals** | OSINT→market correlation signals |
| **Bookmarks** | Saved items across all types |
| **Settings** | Sources, credentials, alerts |

---

## Database Migrations

13 Alembic migrations:

| # | Migration | What It Adds |
|---|-----------|-------------|
| 001 | `initial_schema` | Users, credentials, posts, sources, events, alerts |
| 002 | `entities` | Entities, entity_mentions |
| 003 | `briefs` | Intelligence briefs |
| 004 | `financial` | Holdings, quotes, entity_ticker_map, signals |
| 005 | `geo_precision` | Location precision scoring |
| 006 | `alert_rules` | Alert rules + events (correlation engine) |
| 007 | `alert_enhancements` | Geo-proximity + silence detection |
| 008 | `entity_relationships` | Typed relationships, notes, bookmarks, tags |
| 009 | `media_support` | Media columns, download settings |
| 010 | `acled` | External ID column for dedup |
| 011 | `sanctions` | Sanctions entities + matches, pg_trgm |
| 012 | `fused_events` | Cross-source fused intelligence events |
| 013 | `investigations` | Cases, case items, case timeline |

---

## Development

### Backend
```bash
cd backend
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Database Migrations
```bash
cd backend
alembic upgrade head
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgments

- [ACLED](https://acleddata.com) — Armed conflict event data
- [GDELT Project](https://gdeltproject.org) — Global media monitoring
- [OpenSanctions](https://opensanctions.org) — Sanctions and watchlist data
- [ICIJ](https://offshoreleaks.icij.org) — Offshore leaks database
- [OCCRP Aleph](https://aleph.occrp.org) — Organized crime and corruption data
- [DeepStateMap](https://deepstatemap.live) — Ukraine frontline data
- [OpenSky Network](https://opensky-network.org) — Flight tracking
- [CelesTrak](https://celestrak.org) — Satellite TLE data
- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) — Thermal anomaly data
- [Esri](https://www.arcgis.com) — Satellite imagery tiles
- [CartoDB](https://carto.com) — Dark matter map tiles
- [spaCy](https://spacy.io) — NLP/NER
- [Nominatim](https://nominatim.org) — Geocoding

---

*The seeing stone, open to all.*

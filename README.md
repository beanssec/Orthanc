# ▣ Orthanc

**Open source intelligence for everyone.**

Orthanc is a self-hosted OSINT intelligence platform that aggregates data from dozens of sources into a unified analyst workspace. Live feeds, geospatial mapping, entity extraction, AI-powered analysis, financial intelligence, media verification, and correlation-based alerting — all running on your own hardware.

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
- **FIRMS** — NASA thermal anomaly detection for conflict zones
- **Flight Tracking** — Live aircraft via OpenSky Network
- **Ship Tracking** — AIS vessel monitoring
- **Satellite Tracking** — ISS, military, weather satellites via CelesTrak

### 🔍 Global Search & Natural Language Querying
- **Unified search** across posts, entities, events, and briefs (Ctrl+K)
- **Natural language queries** — ask questions in plain English ("What's happening with Iran?") and get structured results + AI-generated analysis
- Instant search dropdown with debounced results
- Full search results page with filter tabs and keyword highlighting

### 🗺️ Tactical Map
- MapLibre GL with dark CartoDB tiles (free, no API key)
- Clustered OSINT events with precision filtering (city/exact only by default)
- Live flight/ship/satellite tracking layers
- **Multi-source Ukraine frontline data** from 6 mapping sources (DeepStateMap, AMK, Suriyak, UA Control Map, Playfra, Radov)
- FIRMS thermal hotspot overlay
- Sentiment heatmap layer (keyword-based scoring per region)
- Heatmap and cluster visualization modes

### 🧠 AI Intelligence Briefs
- Generate structured intelligence briefs from collected data
- 9+ model support (xAI Grok, Claude, GPT-4o, Gemini, Mistral, Llama via OpenRouter)
- Transparent per-brief cost estimates
- Scheduled briefs (hourly/daily/weekly) with full history
- PDF intelligence report export with classification banners

### 🔗 Entity Extraction, Linking & Analysis
- Automatic NER via spaCy (PERSON, ORG, GPE, NORP, EVENT)
- Entity deduplication and canonical name linking
- **Entity timeline** — chronological view of all mentions per entity
- **Link/path analysis** — BFS shortest-path between entities via co-occurrence
- **Typed relationships** — commands, funds, allied_with, opposes, sanctions, member_of, and more with confidence scoring
- **Entity network graph** — force-directed canvas visualization with path highlighting
- Custom properties (extensible key-value per entity)

### 📷 Media Capture & Verification
- **Opt-in media download** from Telegram — separate toggles for images vs videos with configurable size limits
- **EXIF metadata extraction** — camera model, GPS, timestamps, software detection
- **AI-powered authenticity analysis** — vision models (Grok Vision / GPT-4o) detect AI-generated content
- Authenticity badges: 🟢 Likely Real / 🟡 Uncertain / 🔴 Possibly AI-Generated
- SHA256 file hashing for deduplication
- Thumbnail generation for feed preview

### 💰 Financial Intelligence
- Portfolio tracking with live market data (Yahoo Finance)
- Watchlist: indices, commodities, forex, crypto
- Cashtag ($TICKER) monitoring from X/Twitter
- **OSINT → Market signal correlation** — entity spikes mapped to affected tickers
- AI-generated risk/opportunity signals
- Bloomberg Terminal aesthetic with monospaced numbers

### 🚨 Correlation Alert Engine
Five alert types:
- **Keyword Match** — Regex/keyword match on ingest
- **Entity Velocity** — Entity mention rate exceeds baseline threshold
- **Multi-Stage Correlation** — OSSIM-style directives with time windows ("if Iran spikes AND keyword 'strike' appears within 2 hours → escalate to URGENT")
- **Geo-Proximity** — Alert when events occur within configurable radius of a location
- **Silence Detection** — Alert when an entity or source goes unexpectedly quiet
- Delivery: in-app toast, Telegram bot, webhook
- Severity tiers: 🔴 FLASH / 🟠 URGENT / 🔵 ROUTINE

### 📝 Collaboration & Analysis Tools
- **Notes** — Add analyst notes to any entity, post, or event
- **Bookmarks** — Star and organize important items across all data types
- **Tags** — User-defined labels on any object, searchable across the platform
- **Translate** — Per-item AI translation with language detection

### 🌐 Translation
- Automatic language detection
- AI-powered translation via configured LLM
- Per-item translate button in feed

### 🔒 Security
- Per-user credential encryption (Argon2id key derivation + Fernet)
- Zero-knowledge design — server never stores encryption keys on disk
- Credentials decrypted into memory on login, wiped on restart
- JWT authentication with in-memory token storage (not localStorage)

### 📱 Mobile Responsive
- Hamburger sidebar navigation
- Bottom-sheet panels on map view
- Touch-optimized targets
- Tested on Pixel 7 Pro (412×915 viewport)

---

## Quick Start

### Prerequisites
- Docker & Docker Compose
- 2GB+ RAM recommended
- No API keys required to start (RSS + Reddit + flights + satellites work without auth)

### 1. Clone & Configure

```bash
git clone https://github.com/yourusername/orthanc.git
cd orthanc
cp .env.example .env
# Edit .env if you want to change defaults
```

### 2. Launch

```bash
docker compose up -d
```

This starts three containers:
- **orthanc-postgres** — PostgreSQL 16 + PostGIS (port 5433)
- **orthanc-backend** — FastAPI Python backend (port 8000)
- **orthanc-frontend** — React + Vite frontend (port 3001)

### 3. Open & Register

Navigate to `http://localhost:3001`

Register an account → the setup wizard walks you through adding your first sources.

### 4. Add More Sources

Go to **Settings → Credentials** to add API keys:

| Provider | What You Get | Free Tier |
|----------|-------------|-----------|
| xAI (Grok) | X/Twitter monitoring + AI briefs + media verification | Free credits on signup |
| Telegram | Channel monitoring + media capture | Free (needs phone number) |
| OpenRouter | 7+ AI models for briefs + NL queries | Pay-per-use, most models < $0.01/brief |
| Shodan | Infrastructure scanning | Free tier: 100 queries/month |
| Discord | Server monitoring | Free (bot token) |
| AIS | Ship tracking | Free tier available |

RSS feeds, Reddit, flight tracking, satellite tracking, and FIRMS thermal data require **no API keys**.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Frontend   │◄───►│   Backend    │◄───►│  PostgreSQL  │
│  React/Vite  │     │   FastAPI    │     │  + PostGIS   │
│  Port 3001   │     │  Port 8000   │     │  Port 5433   │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────┴───────┐
                    │  Collectors   │
                    │  (in-process) │
                    │               │
                    │ RSS • X/Twitter│
                    │ Telegram • Reddit│
                    │ Discord • Shodan│
                    │ FIRMS • Flights│
                    │ Ships • Satellites│
                    │ Market • Cashtag│
                    └───────────────┘
```

### Key Design Decisions
- **Collectors run in-process** as async tasks — simpler lifecycle with in-memory credential management
- **Per-user encryption** means credentials are only available when a user is logged in
- **MapLibre GL** (free fork of Mapbox GL) with CartoDB dark-matter tiles — no token needed
- **spaCy** for NER, **Nominatim** for geocoding — both free, self-contained
- **CelesTrak** + **sgp4** for satellite tracking — free TLE data
- **Vision models** for media authenticity — uses existing AI credentials, no extra APIs

---

## Pages

| Page | Description |
|------|-------------|
| **Dashboard** | KPI strip, velocity chart, source health, trending entities, geo hotspots, recent alerts |
| **Feed** | 3-column SIEM-style live timeline with WebSocket, infinite scroll, time presets |
| **Map** | Full-screen tactical map with 7 layer types, frontline data, clustering |
| **Entities** | Sortable entity table, detail view with timeline/relationships/graph/path analysis |
| **Briefs** | AI brief generation, scheduling, history, PDF export |
| **Documents** | Drag-and-drop upload with automatic NER processing |
| **Ask AI** | Natural language query interface with structured results |
| **Portfolio** | Holdings tracker with live quotes and P&L |
| **Markets** | Watchlist with real-time market data |
| **Signals** | OSINT→market correlation signals |
| **Bookmarks** | Saved items across all data types |
| **Sources** | Source management with per-source media settings |
| **Credentials** | API key management (encrypted at rest) |
| **Alerts** | 5-type rule builder with delivery configuration |

---

## Configuration

### Environment Variables

```bash
# Database (defaults work with docker-compose)
DATABASE_URL=postgresql+asyncpg://orthanc:orthanc_dev@postgres:5432/orthanc
JWT_SECRET=your-secret-key-change-this

# Optional: Telegram bot for alert delivery
TELEGRAM_BOT_TOKEN=your-bot-token

# Optional: Override ports
FRONTEND_PORT=3001
BACKEND_PORT=8000
POSTGRES_PORT=5433
```

### Data Storage

All persistent data lives in Docker volumes:
- PostgreSQL data: configurable via `docker-compose.yml`
- Telegram sessions: `./data/telegram_sessions/`
- Media files: `./data/media/` (when media download is enabled)

---

## Database Migrations

9 Alembic migrations:
1. `001_initial_schema` — users, credentials, posts, sources, events, alerts
2. `002_entities` — entities, entity_mentions
3. `003_briefs` — intelligence briefs
4. `004_financial` — holdings, quotes, entity_ticker_map, signals
5. `005_geo_precision` — location precision scoring on events
6. `006_alert_rules` — alert_rules, alert_events (correlation engine)
7. `007_alert_enhancements` — geo-proximity + silence detection fields
8. `008_entity_relationships` — typed relationships, properties, notes, bookmarks, tags
9. `009_media_support` — media columns on posts, download settings on sources

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

## Roadmap

- [ ] Investigation/case management — analyst workspaces with pinned items
- [ ] Connector plugin framework — community-extensible data sources
- [ ] 3D globe view (CesiumJS) for satellites and aircraft
- [ ] More connectors: YouTube transcripts, NOAA/FAA NOTAMs, paste sites
- [ ] Reverse image search integration
- [ ] Video frame analysis for authenticity

---

## Contributing

Contributions welcome. Open an issue first for large changes.

---

## License

MIT

---

## Acknowledgments

- [DeepStateMap](https://deepstatemap.live) — Ukraine frontline data
- [AMK Mapping](https://x.com/AMK_Mapping_), [Suriyakmaps](https://x.com/Suriyakmaps), [UA Control Map](https://uacontrolmap.com), [Playfra](https://playframap.github.io), Anatoly Radov — Additional frontline mapping sources
- [OpenSky Network](https://opensky-network.org) — Flight tracking data
- [CelesTrak](https://celestrak.org) — Satellite TLE data
- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) — Thermal anomaly data
- [CartoDB](https://carto.com) — Dark matter map tiles
- [spaCy](https://spacy.io) — NLP/NER
- [Nominatim](https://nominatim.org) — Geocoding

---

*The seeing stone, open to all.*

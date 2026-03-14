# ORTHANC — Open Source Intelligence Platform

> *"A window into many minds"* — Orthanc, the seeing-stone of Isengard.

Orthanc is a **self-hosted, open-source intelligence aggregation and analysis platform** built for analysts, researchers, and security professionals. It ingests data from dozens of sources, correlates events across time and geography, and surfaces intelligence through a Bloomberg Terminal-inspired dark UI.

![Orthanc Dashboard](docs/screenshots/01-dashboard.png)

---

## Table of Contents

1. [Overview](#overview)
2. [Features at a Glance](#features-at-a-glance)
3. [Architecture](#architecture)
4. [Getting Started](#getting-started)
5. [Data Sources](#data-sources)
6. [The Feed](#the-feed)
7. [Geospatial Map](#geospatial-map)
8. [Entity Intelligence](#entity-intelligence)
9. [Narrative Intelligence Engine](#narrative-intelligence-engine)
10. [AI Intelligence Briefs](#ai-intelligence-briefs)
11. [OQL — Orthanc Query Language](#oql--orthanc-query-language)
12. [Alert Engine](#alert-engine)
13. [Financial Intelligence](#financial-intelligence)
14. [Maritime Intelligence](#maritime-intelligence)
15. [Investigation Cases](#investigation-cases)
16. [Visualization Builder](#visualization-builder)
17. [Satellite Change Detection](#satellite-change-detection)
18. [Security & Encryption](#security--encryption)
19. [Configuration](#configuration)
20. [Development](#development)
21. [Roadmap](#roadmap)
22. [License](#license)

---

## Overview

Orthanc was built out of frustration with fragmented OSINT workflows — multiple browser tabs, manual correlation, and no memory between sessions. It brings everything into a single analyst workstation:

- **Ingest** from 15+ source types simultaneously
- **Correlate** events across sources, geography, and time
- **Analyse** narratives, entities, and bias automatically
- **Query** everything with a purpose-built intelligence query language
- **Alert** when patterns match, entities spike, or narratives diverge
- **Report** with AI-generated intelligence briefs and PDF exports

No cloud dependencies. No API keys required for core functionality. Runs entirely on your own hardware.

---

## Features at a Glance

| Category | Capabilities |
|----------|-------------|
| **Collection** | Telegram, X/Twitter, RSS, Reddit, Discord, Shodan, Webhooks, FIRMS, AIS/Ships, Flights, Satellites, YouTube, Bluesky, Mastodon |
| **Intelligence** | Entity extraction, geo-tagging, narrative clustering, stance classification, bias profiling |
| **Analysis** | OQL query language, correlation engine, fusion clustering, sentiment heatmaps |
| **Alerting** | Keyword alerts, entity spike detection, narrative divergence, correlation triggers |
| **Geospatial** | Live event map, FIRMS fire data, flight/ship/satellite tracking, DeepState frontlines |
| **Finance** | Portfolio tracking, market feeds, cashtag monitoring, signal detection |
| **Reporting** | AI intelligence briefs, PDF export, investigation workspaces |
| **Security** | Per-user Argon2id key derivation, Fernet encryption at rest, JWT auth |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   orthanc-frontend                   │
│            React 18 + Vite + MapLibre GL            │
│                    Port 3001                        │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP/REST
┌──────────────────────▼──────────────────────────────┐
│                   orthanc-backend                    │
│         FastAPI + SQLAlchemy + asyncpg              │
│                    Port 8000                        │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │Collectors│  │ Services │  │   Background      │  │
│  │(15+ src) │  │ (NLP,Geo)│  │   (cluster,alert) │  │
│  └──────────┘  └──────────┘  └──────────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                  orthanc-postgres                    │
│            PostgreSQL 16 + PostGIS                  │
│                    Port 5433                        │
│         /mnt/data/postgres/overwatch                │
└─────────────────────────────────────────────────────┘
```

**Stack:**
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Alembic, spaCy, Telethon
- **Frontend:** React 18, TypeScript, Vite, MapLibre GL, Zustand
- **Database:** PostgreSQL 16 with PostGIS extension
- **Infrastructure:** Docker Compose, single-host deployment

---

## Getting Started

### Prerequisites

- Docker & Docker Compose
- 4GB+ RAM (8GB recommended for full collection)
- 20GB+ disk space for media and database

### Quick Start

```bash
git clone https://github.com/beanssec/Orthanc.git
cd Orthanc

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials (see Configuration section)

# Start the stack
docker compose up -d

# Create your account at http://localhost:3001/register
```

The platform will be available at:
- **Frontend:** `http://localhost:3001`
- **Backend API:** `http://localhost:8000/docs`
- **Agent Access API:** [`docs/agent-api.md`](docs/agent-api.md) — machine-friendly endpoints + API key guide

### First Login

1. Navigate to `http://localhost:3001/register` and create an account
2. Go to **Settings → Credentials** and add your API keys
3. Go to **Settings → Sources** and enable the sources you want
4. Data starts flowing immediately — check the Feed within a few minutes

> **Note:** Your API credentials are encrypted with a key derived from your password using Argon2id. If the server restarts, log in again to resume collectors.

---

## Data Sources

Orthanc ingests from the following source types. Sources marked 🔑 require credentials.

### Social & Messaging
| Source | Type | Notes |
|--------|------|-------|
| **Telegram** | `telegram` | 🔑 Telethon API — channels, groups, media download |
| **X / Twitter** | `x` | 🔑 xAI/Grok API for timeline synthesis |
| **Reddit** | `reddit` | Public API — subreddit monitoring |
| **Bluesky** | `bluesky` | Public ATP API — no key required |
| **Mastodon** | `mastodon` | Public API — any instance |
| **Discord** | `discord` | 🔑 Bot token — server/channel monitoring |
| **YouTube** | `youtube` | yt-dlp — channel transcripts & captions |

### News & Documents
| Source | Type | Notes |
|--------|------|-------|
| **RSS/Atom** | `rss` | Any feed — supports 200+ pre-configured outlets |
| **Webhooks** | `webhook` | Push any JSON payload |
| **Documents** | `document` | PDF/text upload with entity extraction |

### Geospatial & Signals
| Source | Type | Notes |
|--------|------|-------|
| **FIRMS** | `firms` | NASA fire data — near-real-time thermal anomalies |
| **OpenSky/Flights** | `flight` | ADS-B flight tracking — no key required |
| **AIS/Ships** | `ship` | 🔑 AISHub API — vessel tracking |
| **CelesTrak** | `satellite` | Satellite TLE data — no key required |
| **Shodan** | `shodan` | 🔑 Internet-connected device intelligence |
| **ACLED** | `acled` | 🔑 Armed conflict event database |

### Financial
| Source | Type | Notes |
|--------|------|-------|
| **Cashtag** | `cashtag` | yfinance — equity, crypto, commodity tracking |

### Configure a Source

Go to **Settings → Sources → Add Source** and select the source type. For most social sources, you'll need to add credentials first at **Settings → Credentials**.

```
Source types: telegram, x, rss, reddit, discord, bluesky, mastodon,
              youtube, firms, flight, ship, satellite, shodan, acled,
              webhook, document, cashtag
```

---

## The Feed

The Feed is the primary real-time view of all ingested content. Every post, report, signal, and alert flows through here.

**Capabilities:**
- Filter by source type, time range, sentiment, or keyword
- Full-text search across all content
- Click any post to see full detail: entities extracted, geo-tagged location, media (if downloaded), AI translations, and linked narratives
- Sentiment coloring: red (negative) → green (positive)
- Source badges colour-coded by type
- Media thumbnails for Telegram image posts with authenticity metadata (EXIF, AI-generation detection)

**Media Authenticity:**
When Telegram media is downloaded (opt-in per source), Orthanc extracts EXIF data, checks for AI-generation software signatures in metadata, and flags synthetic imagery.

---

## Geospatial Map

The map provides a live geospatial picture of all events extracted from ingested content.

**Layers available:**
| Layer | Description |
|-------|-------------|
| **Events** | All geo-tagged posts (coloured by source type) |
| **FIRMS** | NASA thermal anomalies — fires, explosions |
| **Flights** | Live ADS-B flight positions |
| **Ships** | AIS vessel positions |
| **Satellites** | CelesTrak orbital positions |
| **Frontlines** | DeepState live conflict frontlines (Ukraine) |
| **Sentiment** | Heatmap of sentiment by location |
| **ACLED** | Armed conflict events |
| **Fusion** | Multi-source event clusters |
| **NOTAMs** | FAA/aviation Notices to Airmen |
| **Watchpoints** | Sentinel-2 satellite change detection sites |
| **Maritime Events** | Dark ships, STS transfers, port calls |
| **Narratives** | Geolocated narrative claims |

**Map controls:**
- Toggle layers individually with live post counts
- Click any marker for full detail popup
- Dark-matter CartoDB basemap (no API key required)
- Satellite overlay option (Esri World Imagery)

---

## Entity Intelligence

Orthanc automatically extracts named entities from every ingested post using spaCy NLP:

- **People** (PER) — political figures, military commanders, analysts
- **Organisations** (ORG) — governments, militaries, companies, NGOs
- **Locations** (GPE/LOC) — countries, cities, regions, coordinates
- **Events** (EVENT) — operations, conflicts, summits

**Entity features:**
- Auto-geocoding via Nominatim (rate-limited, queued)
- Mention trending over 6h/24h/7d windows
- Spike detection: alerts when an entity's mentions exceed 2× their 7-day average
- Entity detail view: all posts mentioning an entity, timeline chart, co-occurrence network
- Cross-source entity linking (same entity mentioned across Telegram, X, RSS)
- Fusion enrichment: entities linked to ACLED events, sanctions lists, ICIJ data

---

## Narrative Intelligence Engine

The Narrative Intelligence Engine automatically detects emerging narratives across all sources and tracks how different source groups frame them.

### How it Works

1. **Embedding** — Every post is embedded into a 128-dimensional semantic vector (hash-based, no API key required; upgrades to OpenRouter `text-embedding-3-small` when configured)
2. **Clustering** — Posts with cosine similarity ≥0.75 are grouped into narratives (minimum 3 posts from 2+ source types)
3. **Stance Classification** — Each post's stance toward the narrative is classified: `confirming`, `denying`, `attributing`, `contextualizing`, `deflecting`, or `speculating`
4. **Evidence Correlation** — Claims are cross-referenced against FIRMS fire data, ACLED events, flight/maritime intelligence, and OSINT corroboration
5. **Bias Scoring** — Source groups are positioned on a Western↔Eastern × Reliable↕Unreliable compass

### Source Groups

Sources are automatically assigned to groups based on content patterns:

| Group | Description | Examples |
|-------|-------------|---------|
| **Western Media** | NATO-aligned outlets | BBC, Reuters, AP, WSJ |
| **Russian/Eastern** | Pro-Kremlin or Eastern sources | RT, Tass-aligned channels |
| **Ukrainian Sources** | UA government & OSINT | Official UA channels |
| **OSINT Community** | Open-source trackers | Bellingcat, GeoConfirmed |
| **Independent** | Non-aligned analysis | Think tanks, academics |
| **Cyber Intelligence** | Security feeds | Threat intel, CERT feeds |
| **Maritime/Logistics** | Shipping intelligence | Port monitors, tanker trackers |

### Narrative Views

- **Card list** — All active narratives with divergence score, post count, consensus status
- **Detail panel** — Full post list, stance distribution by source group, evidence timeline
- **Bias Compass** — SVG scatter plot positioning each source group
- **Timeline** — Hourly post volume by source group
- **Claims** — Extracted factual claims with corroboration status

### Divergence Score

The divergence score (0–1) measures how differently Western and Russian source groups are framing a narrative. High divergence (>0.7) triggers an alert.

---

## AI Intelligence Briefs

Orthanc generates AI-powered intelligence briefs on demand or on a schedule.

**Brief types:**
- **Situation Report (SITREP)** — Current operational picture from all active sources
- **Entity Profile** — Deep-dive on a specific person, organisation, or location
- **Narrative Analysis** — How a specific narrative is evolving and where it diverges
- **Custom** — Any prompt against the current intelligence corpus

**Models supported** (via OpenRouter):
- `x-ai/grok-3-mini` (default, fast)
- `anthropic/claude-opus-4` (deep analysis)
- `google/gemini-2.0-flash` (large context)
- Any OpenRouter-compatible model

Briefs are stored with full provenance, exportable as PDF via reportlab.

---

## OQL — Orthanc Query Language

OQL is a purpose-built query language for intelligence analysis. It compiles to safe SQLAlchemy ORM queries — no raw SQL, no injection risk.

### Syntax

```
<target>: [filters] [| pipe operations]
```

### Targets

| Target | Description |
|--------|-------------|
| `posts:` | All ingested content |
| `entities:` | Extracted named entities |
| `alerts:` | Alert history |
| `narratives:` | Detected narratives |
| `briefs:` | AI briefs |

### Examples

```oql
# Posts about Iran from Telegram in the last 6 hours
posts: source_type=telegram content~"Iran" date_from=-6h

# Top entities by mention count
entities: | stats count by name | sort -count | head 20

# Active narratives with high divergence
narratives: status=active divergence_score>0.7 | sort -post_count

# Hourly post volume by source type
posts: date_from=-24h | timechart 1h by source_type

# Entity spikes in the last 24h
entities: | stats count by name, type | sort -count | head 10
```

### Pipe Operations

| Operation | Example | Description |
|-----------|---------|-------------|
| `\| stats count by <field>` | `\| stats count by source_type` | Aggregate counts |
| `\| timechart <interval> by <field>` | `\| timechart 1h by source_type` | Time-series bucketing |
| `\| sort [-]<field>` | `\| sort -count` | Sort ascending/descending |
| `\| head <n>` | `\| head 20` | Limit results |

Results auto-render as tables, bar charts, or time-series based on the query shape — no manual chart configuration needed.

---

## Alert Engine

Alerts fire when configured conditions are met. Three alert types:

### Keyword Alerts
Trigger when a keyword or phrase appears in ingested content.
```
Pattern: "nuclear" OR "missile strike"
Sources: telegram, x, rss
```

### Entity Spike Alerts
Trigger when a named entity's mention count exceeds a threshold relative to its baseline.
```
Entity: Iran
Window: 6h
Threshold: 2× 7-day average
```

### Correlation Alerts
Trigger when multiple source types simultaneously report on related events within a time/geo window.
```
Sources: ≥3 source types
Window: 6h
Cluster radius: 50km
Severity: FLASH (4+ sources), URGENT (3), ROUTINE (2)
```

Alerts appear in the dashboard panel, the alerts feed, and can be configured to send notifications.

---

## Financial Intelligence

The Finance module tracks equities, commodities, cryptocurrencies, and geopolitical price signals.

**Features:**
- Portfolio tracking with P&L and allocation charts
- Live market data via yfinance (delayed 15min)
- Cashtag monitoring — tracks `$TICKER` mentions across all social sources
- Correlation signals: price moves correlated with news events
- Configurable watchlists

**Supported instruments:** Equities (global), ETFs, Crypto (BTC, ETH, etc.), Commodities (WTI, Brent, Gold, Silver)

---

## Maritime Intelligence

**Vessel tracking** (requires AISHub API key):
- Live AIS position updates for tracked vessels
- Speed/heading/destination monitoring
- Port call detection

**Dark ship detection** — vessels that disable AIS transmitters near sanctioned ports or during STS (ship-to-ship) transfers are flagged.

**Monitored ports:** Bandar Abbas, Tartus, Latakia, Sevastopol, Novorossiysk, Kaliningrad, Port Sudan, Kharg Island, Basra, Aden.

**Sanctions cross-reference:** Vessels are checked against EU and UK OFSI sanctions lists.

---

## Investigation Cases

Cases are persistent investigation workspaces that link posts, entities, documents, and notes.

**Features:**
- Create cases for specific investigations
- Add posts, entities, and documents from anywhere in the platform
- Annotate with investigator notes
- Export case dossiers as PDF
- Share cases between users

Cases are accessible at **Analysis → Cases** in the sidebar.

---

## Visualization Builder

The Viz Builder turns OQL query results into interactive charts automatically, or lets you configure them manually.

**Chart types:**
- **Time Series** — trend lines, post velocity
- **Bar Charts** — entity counts, source distribution
- **Heatmaps** — sentiment by location/time
- **Tables** — raw query results with sorting

Charts are built from raw SVG/Canvas — no external chart libraries.

---

## Satellite Change Detection

Orthanc monitors specific geographic watchpoints using Copernicus Sentinel-2 imagery.

**How it works:**
1. Every 6 hours, the latest Sentinel-2 imagery is fetched for each watchpoint (via CDSE OData API — free, no auth required)
2. A pixel-hash comparison detects visual changes between images
3. Changes above the configured threshold trigger a `CHANGE DETECTED` alert with the cloud cover and date

**Default watchpoints (12):**
- Sevastopol Naval Base, Tartus Naval Base (Syria)
- Bandar Abbas, Natanz, Fordow, Isfahan (Iran nuclear sites)
- Kaliningrad (Russia), Khmeimim Airbase (Syria)
- Yongbyon, Sohae (North Korea)
- Strait of Hormuz, Bab el-Mandeb (chokepoints)

Custom watchpoints can be added via **Settings → Watchpoints** or the API.

---

## Security & Encryption

Orthanc uses **per-user password-derived encryption** (Option C) for all stored credentials:

1. **Key derivation** — Argon2id (time=2, memory=65536, parallelism=2) derives a 256-bit key from your password
2. **Encryption** — All API keys and credentials encrypted with Fernet (AES-128-CBC + HMAC-SHA256)
3. **At-rest** — Only ciphertext is stored in the database; plaintext only exists in memory during an active session
4. **JWT** — Authentication tokens stored in Zustand in-memory store only (never localStorage)
5. **Collector resumption** — After a server restart, collectors resume only after the user logs in and re-derives their key

This means: **if the database is compromised, no credentials are exposed.**

---

## Configuration

All configuration is done via environment variables in `.env`:

```env
# Database
DATABASE_URL=postgresql+asyncpg://overwatch:overwatch_dev@postgres:5432/overwatch

# Security
SECRET_KEY=<generate with: openssl rand -hex 32>
ARGON2_TIME_COST=2
ARGON2_MEMORY_COST=65536

# Optional: OpenRouter (enables AI briefs, embeddings, stance classification)
OPENROUTER_API_KEY=sk-or-...

# Optional: Override default ports
BACKEND_PORT=8000
FRONTEND_PORT=3001
POSTGRES_PORT=5433
```

**Credentials** (API keys for sources) are stored **per-user** in the encrypted credentials table, not in environment variables. Configure them at **Settings → Credentials** after logging in.

---

## Development

### Running locally (without Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

### Database migrations

```bash
# Apply all migrations
docker exec orthanc-backend alembic upgrade head

# Create a new migration
docker exec orthanc-backend alembic revision --autogenerate -m "description"
```

### Frontend build

```bash
# Rebuild production bundle (required after frontend changes)
docker exec orthanc-frontend sh -c "cd /app && npm run build"
docker compose restart frontend
```

### Adding a new collector

1. Create `backend/app/collectors/<name>_collector.py`
2. Implement the async `start()` method that polls and inserts `Post` records
3. Register in `backend/app/collectors/orchestrator.py`
4. Add source type to the frontend dropdown in `frontend/src/components/sources/SourcesPage.tsx`
5. Add a source colour in `FeedView.tsx` and `DashboardView.tsx`

---

## Roadmap

### Near-term
- [ ] Fix `last_polled` updates for all collectors (Telegram, Reddit, Discord currently missing)
- [ ] Dashboard drill-downs: click velocity bars → filtered feed
- [ ] Narrative title improvement (currently uses top word-frequency)
- [ ] Frontline snapshot storage + date slider playback (historical frontlines)

### Medium-term
- [ ] Multi-user collaboration on cases
- [ ] Scheduled brief delivery (email/Telegram)
- [ ] GDELT integration for event coverage
- [ ] DeepState historical API (conflict frontline history)
- [ ] Source health monitoring with auto-disable on repeated failure

### Long-term
- [ ] Graph database for entity relationship mapping
- [ ] OSINT automation playbooks
- [ ] Mobile-optimised view
- [ ] Federated instance support (share collections between Orthanc deployments)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

Orthanc is free to use, self-host, modify, and distribute. If you build something with it, a star on GitHub is appreciated.

---

## Acknowledgements

Built on the shoulders of:
- [FastAPI](https://fastapi.tiangolo.com/) — async Python web framework
- [Telethon](https://github.com/LonamiWebs/Telethon) — Telegram MTProto client
- [spaCy](https://spacy.io/) — industrial NLP
- [MapLibre GL](https://maplibre.org/) — open-source map rendering
- [CartoDB](https://carto.com/) — dark-matter basemap tiles
- [OpenSky Network](https://opensky-network.org/) — free ADS-B flight data
- [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) — fire/thermal data
- [CelesTrak](https://celestrak.org/) — satellite orbital data
- [Copernicus/ESA](https://dataspace.copernicus.eu/) — Sentinel-2 imagery

---

*Orthanc — named for the tower in Isengard that housed the seeing-stone (Palantír) in Tolkien's Middle-earth. A deliberate nod to [Palantir Technologies](https://www.palantir.com/) — the goal is to build something in that spirit, but open.*

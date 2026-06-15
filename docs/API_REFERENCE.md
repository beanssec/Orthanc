# Orthanc API Reference

> Generated from router source files — Sprint 32 Checkpoint 4.

All endpoints are available at two path prefixes:
- **Unversioned** (legacy): `/<path>` — includes `Deprecation: true` header
- **Versioned** (recommended): `/api/v1/<path>`

## Authentication

Most endpoints require a valid **JWT Bearer token** obtained from `/auth/login`.  
Machine clients may use an **API key** (see [Agent API](#agent) and [API Keys](#api-keys) sections).

```
Authorization: Bearer <jwt_token>
# or for API keys:
X-API-Key: ow_<api_key>
```

Rate limits: 100 requests/minute per user (configurable via `RATE_LIMIT_PER_MINUTE` env var).

---

## Auth

**Prefix:** `/auth`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/auth/login` | Obtain JWT access + refresh tokens | No |
| POST | `/auth/refresh` | Refresh access token | No (refresh token in body) |
| POST | `/auth/register` | Register new user | No |
| GET | `/auth/me` | Get current user info | Yes |
| POST | `/auth/logout` | Invalidate session | Yes |

**Login request:**
```json
{ "username": "string", "password": "string" }
```
**Login response:**
```json
{ "access_token": "string", "refresh_token": "string", "token_type": "bearer" }
```

---

## Sources

**Prefix:** `/sources`  **Auth:** JWT required

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| GET | `/sources/` | `type` (query, optional) | List all sources for current user |
| POST | `/sources/` | Body: SourceCreate | Create a new source |
| GET | `/sources/health` | — | Per-source health status |
| GET | `/sources/{source_id}` | `source_id` (UUID) | Get single source |
| PUT | `/sources/{source_id}` | `source_id` + Body: SourceUpdate | Update source |
| DELETE | `/sources/{source_id}` | `source_id` (UUID) | Delete source |
| POST | `/sources/{source_id}/reliability/score` | `source_id` | Trigger reliability scoring |
| PATCH | `/sources/{source_id}/reliability/override` | `source_id` + Body | Set analyst override |
| POST | `/sources/reliability/score-all` | — | Bulk-score all user sources |

**SourceCreate fields:**
```json
{
  "type": "rss|telegram|reddit|youtube|bluesky|mastodon|x|discord|official|scraper",
  "handle": "string",
  "display_name": "string",
  "config_json": {},
  "download_images": false,
  "download_videos": false,
  "max_image_size_mb": 10.0,
  "max_video_size_mb": 100.0,
  "poll_interval_seconds": null,
  "filter_keywords": null,
  "filter_mode": null
}
```

---

## Feed

**Prefix:** (no prefix — routes under `/feed/`, `/ws/feed`)  **Auth:** JWT required

| Method | Path | Parameters | Description |
|--------|------|-----------|-------------|
| GET | `/feed/` | `source_type`, `keywords`, `since`, `until`, `limit`, `offset` | Paginated post feed |
| GET | `/feed/facets` | — | Aggregated facets (source types, date ranges) |
| GET | `/feed/{post_id}` | `post_id` (UUID) | Get single post |
| WS | `/ws/feed` | JWT via query `?token=<jwt>` | Real-time post WebSocket |

---

## Alerts

**Prefix:** `/alerts`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/alerts/` | List alert events |
| GET | `/alerts/{alert_id}` | Get single alert |
| DELETE | `/alerts/{alert_id}` | Dismiss alert |
| GET | `/alerts/hits` | Alert rule hit history |
| GET | `/alerts/events/` | All alert events |
| GET | `/alerts/rules/` | List alert rules |
| POST | `/alerts/rules/` | Create alert rule |
| GET | `/alerts/rules/{rule_id}` | Get alert rule |
| PUT | `/alerts/rules/{rule_id}` | Update alert rule |
| DELETE | `/alerts/rules/{rule_id}` | Delete alert rule |

---

## Entities

**Prefix:** `/entities`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/entities/` | List entities (supports `query`, `type`, `limit`) |
| POST | `/entities/` | Create entity |
| GET | `/entities/{entity_id}` | Get entity detail |
| PUT | `/entities/{entity_id}` | Update entity |
| DELETE | `/entities/{entity_id}` | Delete entity |
| GET | `/entities/{entity_id}/timeline` | Entity event timeline |
| GET | `/entities/{entity_id}/relationships` | Entity relationships |
| GET | `/entities/{entity_id}/connections` | Graph connections |
| GET | `/entities/{entity_id}/merge-candidates` | Suggested duplicates |
| POST | `/entities/{entity_id}/merge` | Merge into another entity |
| GET | `/entities/merge-candidates` | All merge candidates |
| GET | `/entities/normalization/summary` | Normalisation summary |
| GET | `/entities/relationship-types` | Available relationship types |

---

## Narratives

**Prefix:** `/narratives`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/narratives/` | List narratives |
| GET | `/narratives/{narrative_id}` | Get narrative |
| GET | `/narratives/{narrative_id}/claims` | Claims in narrative |
| GET | `/narratives/{narrative_id}/timeline` | Narrative timeline |
| GET | `/narratives/history` | Narrative change history |
| GET | `/narratives/bias/profiles` | Source bias profiles |
| GET | `/narratives/bias/compass` | Bias compass view |

---

## Briefs

**Prefix:** `/briefs`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/briefs/` | List generated briefs |
| POST | `/briefs/` | Generate a new brief |
| GET | `/briefs/{brief_id}` | Get brief |
| DELETE | `/briefs/{brief_id}` | Delete brief |
| GET | `/briefs/{brief_id}/pdf` | Download brief as PDF |

---

## Scheduled Briefs

**Prefix:** `/scheduled-briefs`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/scheduled-briefs/` | List scheduled briefs |
| POST | `/scheduled-briefs/` | Create scheduled brief |
| GET | `/scheduled-briefs/{id}` | Get scheduled brief |
| PATCH | `/scheduled-briefs/{id}` | Update scheduled brief |
| DELETE | `/scheduled-briefs/{id}` | Delete scheduled brief |
| GET | `/scheduled-briefs/{id}/runs` | Run history |
| GET | `/scheduled-briefs/{id}/deliveries` | Webhook delivery history |

---

## Cases

**Prefix:** `/cases`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/cases/` | List cases |
| POST | `/cases/` | Create case |
| GET | `/cases/{case_id}` | Get case |
| DELETE | `/cases/{case_id}` | Delete case |
| GET | `/cases/{case_id}/timeline` | Case timeline |
| GET | `/cases/{case_id}/export/pdf` | Export case as PDF |
| GET | `/cases/notes/{target_type}/{target_id}` | Get notes |
| POST | `/cases/notes` | Add note |
| DELETE | `/cases/notes/{note_id}` | Delete note |
| GET | `/cases/bookmarks/` | List bookmarks |
| POST | `/cases/bookmarks` | Add bookmark |
| DELETE | `/cases/bookmarks/{target_type}/{target_id}` | Remove bookmark |
| GET | `/cases/tags/{target_type}/{target_id}` | Get tags |
| POST | `/cases/tags` | Add tag |
| DELETE | `/cases/tags/{target_type}/{target_id}/{tag}` | Remove tag |
| DELETE | `/cases/{case_id}/items/{item_id}` | Remove item from case |

---

## Sanctions

**Prefix:** `/sanctions`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sanctions/matches/{entity_id}` | Sanctions matches for entity |
| GET | `/sanctions/eu/search` | EU FSF sanctions search |
| GET | `/sanctions/eu/stats` | EU sanctions stats |
| GET | `/sanctions/icij/search` | ICIJ database search |
| GET | `/sanctions/occrp/search` | OCCRP search |

---

## Maritime

**Prefix:** (no fixed prefix — routes under `/maritime/`)  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/maritime/events` | Maritime events |
| GET | `/maritime/tracks/{mmsi}` | AIS track for MMSI |
| GET | `/maritime/ports` | Port data |
| GET | `/maritime/watchlist` | Maritime watchlist |
| POST | `/maritime/watchlist` | Add to watchlist |
| DELETE | `/maritime/watchlist/{item_id}` | Remove from watchlist |

---

## Finance

**Prefix:** `/finance`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/finance/quotes/{ticker}` | Price quotes for ticker |
| GET | `/finance/quotes` | Multi-ticker quotes |
| GET | `/finance/cashtags` | All tracked cashtags |
| GET | `/finance/cashtags/{ticker}` | Cashtag posts |
| GET | `/finance/portfolio` | Portfolio holdings |
| POST | `/finance/portfolio` | Add holding |
| DELETE | `/finance/portfolio/{holding_id}` | Remove holding |

---

## Models

**Prefix:** `/models`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/models/` | List available LLM models |
| GET | `/models/providers` | Configured providers |
| POST | `/models/providers` | Register provider |
| DELETE | `/models/providers/{provider}` | Remove provider |
| GET | `/models/tasks/{task}` | Task model override |
| POST | `/models/tasks/{task}` | Set task model override |
| DELETE | `/models/tasks/{task}` | Clear task model override |
| GET | `/models/performance` | Model performance metrics |
| GET | `/models/history` | Model usage history |

---

## API Keys

**Prefix:** `/api-keys`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api-keys/` | List API keys for user |
| POST | `/api-keys/` | Create new API key (returns raw key once) |
| DELETE | `/api-keys/{key_id}` | Revoke API key |

**Create request:**
```json
{ "name": "my-agent-key", "scopes": ["agent:read"], "scope": "read_only" }
```
**Create response:**
```json
{ "id": "uuid", "name": "...", "prefix": "ow_xxxxxxxx", "raw_key": "ow_...", "scopes": [...], "scope": "read_only" }
```
> ⚠️ `raw_key` is returned only once at creation. Store it securely.

---

## Agent

**Prefix:** `/agent`  **Auth:** JWT or API key (`X-API-Key: ow_...`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agent/sitrep` | Situation report (recent posts, alerts, entities) |
| GET | `/agent/feed/compact` | Compact feed for machine clients |
| GET | `/agent/entities/{entity_id}/dossier` | Full entity dossier |
| GET | `/agent/alerts` | Recent alerts |
| GET | `/agent/narratives` | Current narratives |
| GET | `/agent/events` | Recent geo-events |

Required scope: `agent:read`

---

## Graph

**Prefix:** `/graph`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/graph/` | Entity relationship graph |
| GET | `/graph/path` | Shortest path between entities |

---

## Dashboard

**Prefix:** `/dashboard`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dashboard/` | Dashboard summary stats |
| GET | `/dashboard/geo-hotspots` | Geospatial hotspots |

---

## Layers

**Prefix:** (no fixed prefix)  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/layers/acled` | ACLED conflict events |
| GET | `/layers/firms` | FIRMS fire hotspots |
| GET | `/layers/flights` | Live flight data |
| GET | `/layers/ships` | AIS ship positions |
| GET | `/layers/satellites` | Satellite imagery layers |
| GET | `/layers/frontlines` | Frontline positions |
| GET | `/layers/frontlines/sources` | Frontline data sources |
| GET | `/layers/narratives` | Narrative layer for map |
| GET | `/layers/notams` | NOTAMs (airspace notices) |
| GET | `/layers/maritime-events` | Maritime event layer |
| GET | `/layers/sentiment` | Sentiment heat layer |
| GET | `/layers/fusion` | Fused intelligence events |
| GET | `/layers/watchpoints` | Watchpoint locations |

---

## Search

**Prefix:** (no fixed prefix)  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/search/` | Full-text + faceted search |
| GET | `/search/saved` | Saved searches |
| POST | `/search/saved` | Save a search |
| DELETE | `/search/saved/{query_id}` | Delete saved search |

---

## Investigations

**Prefix:** `/investigations`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/investigations/` | List investigations |
| POST | `/investigations/` | Create investigation |
| GET | `/investigations/{id}` | Get investigation |
| PUT | `/investigations/{id}` | Update investigation |
| DELETE | `/investigations/{id}` | Delete investigation |

---

## Fusion

**Prefix:** `/fusion`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/fusion/` | Fused intelligence events |
| GET | `/fusion/layers/fusion` | Fusion map layer |
| GET | `/fusion/combined` | Combined intelligence view |

---

## OQL (Orthanc Query Language)

**Prefix:** `/oql`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/oql/` | Execute OQL query |
| GET | `/oql/articles` | OQL article search |
| GET | `/oql/entities` | OQL entity search |
| GET | `/oql/events` | OQL event search |
| GET | `/oql/geo` | OQL geospatial query |

---

## Natural Language Query

**Prefix:** (no fixed prefix)  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| POST | `/nlquery/` | Natural language to OQL translation + execution |
| GET | `/nlquery/history` | Query history |

---

## Frontlines

**Prefix:** `/frontlines`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/frontlines/` | Frontline snapshots |
| GET | `/frontlines/dates` | Available snapshot dates |
| GET | `/frontlines/mappings` | Source mappings |
| POST | `/frontlines/mappings` | Add mapping |
| DELETE | `/frontlines/mappings/{mapping_id}` | Remove mapping |

---

## Digests

**Prefix:** `/digests`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/digests/` | List digests |
| POST | `/digests/generate` | Generate digest |
| DELETE | `/digests/schedule` | Cancel scheduled digest |

---

## GDELT

**Prefix:** `/gdelt`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/gdelt/` | GDELT event search |
| GET | `/gdelt/geo` | GDELT geospatial results |

---

## Collaboration

**Prefix:** (no fixed prefix)  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/collab/rooms` | Collaboration rooms |
| POST | `/collab/rooms` | Create room |
| WS | `/ws/collab/{room_id}` | Collaboration WebSocket |

---

## Webhook

**Prefix:** `/webhook`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/webhook/` | List webhook configurations |
| POST | `/webhook/` | Register webhook |
| DELETE | `/webhook/{id}` | Remove webhook |

---

## Credentials

**Prefix:** `/credentials`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/credentials/` | List credential slots (names only, values encrypted) |
| POST | `/credentials/` | Store credential |
| DELETE | `/credentials/{name}` | Delete credential |

---

## Media

**Prefix:** `/media`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/media/` | List downloaded media |
| GET | `/media/{post_id}` | Media for a post |

---

## Health

**Prefix:** (no fixed prefix)  **Auth:** No

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Basic liveness check |
| GET | `/health/ready` | Readiness (DB connectivity) |
| GET | `/health/dependencies` | Service dependency status |

---

## Metrics

**Prefix:** (no fixed prefix)  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Prometheus-format metrics |

---

## Telegram Auth

**Prefix:** `/telegram/auth`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| POST | `/telegram/auth/` | Initiate Telegram account auth |
| GET | `/telegram/auth/status` | Auth status |

---

## Watchpoints

**Prefix:** `/watchpoints`  **Auth:** JWT required

| Method | Path | Description |
|--------|------|-------------|
| GET | `/watchpoints/` | List watchpoints |
| POST | `/watchpoints/` | Create watchpoint |
| GET | `/watchpoints/{id}` | Get watchpoint |
| PUT | `/watchpoints/{id}` | Update watchpoint |
| DELETE | `/watchpoints/{id}` | Delete watchpoint |

---

## Error Codes

| Status | Meaning |
|--------|---------|
| 400 | Bad request / validation error |
| 401 | Missing or invalid authentication |
| 403 | Insufficient scope (read-only key on write endpoint) |
| 404 | Resource not found |
| 422 | Unprocessable entity (Pydantic validation failure) |
| 429 | Rate limit exceeded |
| 500 | Internal server error |

---

*Last updated: Sprint 32 Checkpoint 4 — see `docs/AGENT_API.md` for machine-client examples.*

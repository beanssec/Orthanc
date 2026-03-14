# Agent Access API

> **Sprint 30 — practical reference for agents and automated clients.**

Orthanc exposes a machine-friendly API surface under `/agent/*` and `/api-keys/*`.  
This document covers everything you need to authenticate and start pulling data.

---

## Table of contents

1. [Authentication overview](#1-authentication-overview)
2. [Creating an API key](#2-creating-an-api-key)
3. [Using an API key](#3-using-an-api-key)
4. [Endpoint reference](#4-endpoint-reference)
   - [GET /agent/sitrep](#get-agentsitrep)
   - [GET /agent/entities/{id}/dossier](#get-agententitiesiddossier)
   - [GET /agent/feed/compact](#get-agentfeedcompact)
5. [Key management](#5-key-management)
6. [Error reference](#6-error-reference)

---

## 1. Authentication overview

All `/agent/*` routes require a valid credential.  
Two methods are accepted:

| Method | Header | When to use |
|--------|--------|-------------|
| API key | `Authorization: Bearer ow_<token>` | Agents, scripts, automation |
| JWT session token | `Authorization: Bearer <jwt>` | Browser / logged-in sessions |

API keys have the format `ow_<43-char-url-safe-base64>`, e.g.:

```
ow_Abc123XyZ_someRandomTokenGoesHere1234567890abc
```

The `ow_` prefix is part of the key — include it in the header.

---

## 2. Creating an API key

**You need a valid JWT session token to create an API key.**  
Log in via `POST /auth/login` first, then call:

```
POST /api-keys
Authorization: Bearer <your-jwt-token>
Content-Type: application/json

{
  "name": "my-agent-key",
  "scopes": []
}
```

`scopes` is a list of permission labels. An empty array grants full read access (the safe default for most agents). Future scope values follow the pattern `read:<resource>`.

### Response (201 Created)

```json
{
  "key": "ow_Abc123XyZ_someRandomTokenGoesHere1234567890abc",
  "api_key": {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "my-agent-key",
    "prefix": "ow_Abc123X",
    "scopes": [],
    "created_at": "2026-03-14T23:00:00+00:00",
    "last_used_at": null,
    "revoked_at": null,
    "is_active": true
  }
}
```

> ⚠️ **The full key is returned exactly once.** Copy and store it securely — it cannot be retrieved again. Only the prefix (`ow_Abc123X`) is ever shown after creation.

---

## 3. Using an API key

Pass the key in the `Authorization` header as a Bearer token:

```
GET /agent/sitrep
Authorization: Bearer ow_Abc123XyZ_someRandomTokenGoesHere1234567890abc
```

### curl example

```bash
API_KEY="ow_Abc123XyZ_someRandomTokenGoesHere1234567890abc"
BASE="http://localhost:8000"

curl -s -H "Authorization: Bearer $API_KEY" \
  "$BASE/agent/sitrep?hours=12" | jq .meta
```

### Python example

```python
import httpx

API_KEY = "ow_Abc123XyZ_someRandomTokenGoesHere1234567890abc"
BASE = "http://localhost:8000"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

r = httpx.get(f"{BASE}/agent/sitrep", headers=HEADERS, params={"hours": 24})
r.raise_for_status()
sitrep = r.json()
print(sitrep["meta"])
```

---

## 4. Endpoint reference

All endpoints return `application/json`. All timestamps are ISO 8601 UTC.

---

### GET /agent/sitrep

Returns a dense situation report — the single best "what's happening right now" snapshot for an agent to consume.

#### Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hours` | int | `24` | Lookback window (1–168) |
| `narrative_limit` | int | `10` | Max narratives to return (1–50) |
| `entity_limit` | int | `15` | Max entities to return (1–100) |
| `alert_limit` | int | `20` | Max alert events to return (1–100) |

#### Request

```
GET /agent/sitrep?hours=6&narrative_limit=5
Authorization: Bearer ow_...
```

#### Response

```json
{
  "meta": {
    "generated_at": "2026-03-14T23:15:00+00:00",
    "window_hours": 6,
    "endpoint": "sitrep"
  },
  "narratives": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Artillery strikes in eastern region",
      "claim": "Heavy artillery reported near Avdiivka",
      "status": "active",
      "type": "conflict",
      "confirmation": "corroborated",
      "post_count": 47,
      "source_count": 8,
      "divergence_score": 0.12,
      "evidence_score": 0.83,
      "confidence": "high",
      "consensus": "Multiple sources confirm escalation",
      "keywords": ["artillery", "Avdiivka", "shelling"],
      "first_seen": "2026-03-14T18:00:00+00:00",
      "last_updated": "2026-03-14T23:10:00+00:00"
    }
  ],
  "alerts": [
    {
      "id": "aaa00000-0000-0000-0000-000000000001",
      "rule_name": "Flash: Frontline movement",
      "severity": "flash",
      "rule_type": "keyword",
      "summary": "Confirmed advance near grid ref 1234",
      "triggered_at": "2026-03-14T22:55:00+00:00",
      "post_count": 12,
      "entity_names": ["Wagner Group", "Avdiivka"]
    }
  ],
  "entities": [
    {
      "id": "bbbb0000-0000-0000-0000-000000000002",
      "name": "Wagner Group",
      "type": "ORG",
      "mention_count": 312,
      "first_seen": "2026-01-01T00:00:00+00:00",
      "last_seen": "2026-03-14T23:05:00+00:00"
    }
  ],
  "sources": [
    {
      "name": "DeepState Map",
      "type": "frontline",
      "last_polled": "2026-03-14T23:10:00+00:00",
      "health": "ok"
    }
  ],
  "feed_pulse": {
    "window_hours": 6,
    "total_posts": 1843,
    "by_source_type": {
      "telegram": 910,
      "rss": 421,
      "reddit": 312,
      "x": 200
    }
  }
}
```

#### Field notes

- `confidence` — derived label: `"high"` ≥ 0.80, `"medium"` ≥ 0.50, `"low"` < 0.50
- `alerts` — sorted flash → urgent → routine regardless of time
- `sources[].health` — `"ok"` (polled < 2h ago), `"stale"` (> 2h), `"pending"` (never polled)
- `feed_pulse.by_source_type` — keys are the `source_type` values used throughout the system

---

### GET /agent/entities/{id}/dossier

Returns a full entity profile: core identity, known aliases, recent posts that mention it, related narratives, and co-occurrence relationships.

#### Path parameter

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity_id` | UUID | Entity ID (from sitrep `entities[].id` or entity search) |

#### Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mention_limit` | int | `20` | Recent mentions to include (1–100) |
| `narrative_limit` | int | `10` | Related narratives to include (1–50) |
| `relationship_limit` | int | `20` | Top relationships to include (1–100) |

#### Request

```
GET /agent/entities/bbbb0000-0000-0000-0000-000000000002/dossier
Authorization: Bearer ow_...
```

#### Response

```json
{
  "meta": {
    "generated_at": "2026-03-14T23:20:00+00:00",
    "endpoint": "entity_dossier",
    "entity_id": "bbbb0000-0000-0000-0000-000000000002"
  },
  "entity": {
    "id": "bbbb0000-0000-0000-0000-000000000002",
    "name": "Wagner Group",
    "canonical_name": "Wagner Group",
    "type": "ORG",
    "mention_count": 312,
    "first_seen": "2026-01-01T00:00:00+00:00",
    "last_seen": "2026-03-14T23:05:00+00:00"
  },
  "aliases": [
    {
      "text": "PMC Wagner",
      "confidence": 0.95,
      "source": "entity_extractor"
    },
    {
      "text": "Vagner",
      "confidence": 0.72,
      "source": "alias_detector"
    }
  ],
  "recent_mentions": [
    {
      "post_id": "cccc0000-0000-0000-0000-000000000003",
      "source_type": "telegram",
      "author": "@militarymaps",
      "timestamp": "2026-03-14T23:05:00+00:00",
      "ingested_at": "2026-03-14T23:05:45+00:00",
      "snippet": "Wagner units reportedly advancing south of Bakhmut..."
    }
  ],
  "related_narratives": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Artillery strikes in eastern region",
      "claim": "Heavy artillery reported near Avdiivka",
      "status": "active",
      "type": "conflict",
      "evidence_score": 0.83,
      "confidence": "high",
      "post_count": 47,
      "last_updated": "2026-03-14T23:10:00+00:00"
    }
  ],
  "relationships": [
    {
      "peer_entity_id": "dddd0000-0000-0000-0000-000000000004",
      "peer_name": "Yevgeny Prigozhin",
      "peer_type": "PERSON",
      "relationship_type": "co-occurrence",
      "weight": 0.91,
      "confidence": 0.88,
      "first_seen": "2026-01-15T00:00:00+00:00",
      "last_seen": "2026-03-14T20:00:00+00:00"
    }
  ]
}
```

#### Field notes

- `aliases` — sorted by confidence descending
- `recent_mentions[].snippet` — up to 300 chars from `context_snippet`, falling back to post content
- `relationships[].weight` — co-occurrence weight (higher = more frequently co-mentioned)

---

### GET /agent/feed/compact

A stripped-down, agent-friendly post list. Use this when you want raw signal without entity/narrative enrichment.

#### Query parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `hours` | int | `6` | Lookback window (1–72) |
| `source_type` | string | `null` | Filter by source type (e.g. `telegram`, `rss`, `reddit`) |
| `limit` | int | `50` | Max posts to return (1–500) |

#### Request

```
GET /agent/feed/compact?hours=2&source_type=telegram&limit=100
Authorization: Bearer ow_...
```

#### Response

```json
{
  "meta": {
    "generated_at": "2026-03-14T23:25:00+00:00",
    "window_hours": 2,
    "source_type_filter": "telegram",
    "returned": 73,
    "endpoint": "feed_compact"
  },
  "posts": [
    {
      "id": "eeee0000-0000-0000-0000-000000000005",
      "source_type": "telegram",
      "source_id": "src-uuid-here",
      "author": "@militarymaps",
      "timestamp": "2026-03-14T23:22:00+00:00",
      "ingested_at": "2026-03-14T23:22:30+00:00",
      "snippet": "FLASH: Confirmed contact south of grid 447...",
      "authenticity_score": 0.87,
      "media_type": null
    }
  ]
}
```

#### Field notes

- `snippet` — first 500 characters of `content`; `null` if no text content
- `authenticity_score` — 0.0–1.0; `null` if not yet analyzed
- `media_type` — e.g. `"image"`, `"video"`, or `null`

---

## 5. Key management

### List your keys

```
GET /api-keys
Authorization: Bearer <jwt-token>
```

Response: array of `ApiKeyResponse` objects (no hashes, no plaintext keys).

```json
[
  {
    "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "name": "my-agent-key",
    "prefix": "ow_Abc123X",
    "scopes": [],
    "created_at": "2026-03-14T23:00:00+00:00",
    "last_used_at": "2026-03-14T23:25:00+00:00",
    "revoked_at": null,
    "is_active": true
  }
]
```

### Revoke a key

```
DELETE /api-keys/{key_id}
Authorization: Bearer <jwt-token>
```

Response:

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "revoked": true,
  "message": "API key revoked successfully"
}
```

Revoked keys return `401` immediately on any subsequent request.

---

## 6. Error reference

| HTTP status | Meaning |
|-------------|---------|
| `401 Unauthorized` | Missing or invalid credential |
| `403 Forbidden` | Valid key but insufficient scope |
| `404 Not Found` | Entity ID does not exist (`/dossier`) |
| `422 Unprocessable Entity` | Invalid query parameter value |

All errors return a standard FastAPI JSON body:

```json
{
  "detail": "Could not validate credentials"
}
```

---

## Quick start for an AI agent

Here is the minimal flow to get usable intelligence into an agent context:

```python
import httpx

BASE = "http://localhost:8000"
API_KEY = "ow_..."   # from POST /api-keys

headers = {"Authorization": f"Bearer {API_KEY}"}

# 1. Grab the current situation
sitrep = httpx.get(f"{BASE}/agent/sitrep", headers=headers, params={"hours": 24}).json()

# 2. Pull dossier for the top entity
top_entity_id = sitrep["entities"][0]["id"]
dossier = httpx.get(f"{BASE}/agent/entities/{top_entity_id}/dossier", headers=headers).json()

# 3. Grab recent raw signal
feed = httpx.get(f"{BASE}/agent/feed/compact", headers=headers, params={"hours": 2, "limit": 100}).json()

# 4. Build a prompt
context = f"""
SITREP ({sitrep['meta']['window_hours']}h window):
- Active narratives: {len(sitrep['narratives'])}
- Flash alerts: {sum(1 for a in sitrep['alerts'] if a['severity'] == 'flash')}
- Total posts ingested: {sitrep['feed_pulse']['total_posts']}

Top entity dossier: {dossier['entity']['canonical_name']} ({dossier['entity']['type']})
- Mention count: {dossier['entity']['mention_count']}
- Active in {len(dossier['related_narratives'])} narratives
"""
```

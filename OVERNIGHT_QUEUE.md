# Overnight Task Queue — 2026-03-16

**Purpose:** Long-running improvement tasks for overnight execution
**Started:** 2026-03-16T10:14Z
**Model:** Default (hunter-alpha via OpenRouter while free)
**Total tasks:** 100

---

## Bug Fixes & Stability (1-15)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 01 | Fix startup race condition — providers register before embedding calls | High | 10m | ⏳ |
| 02 | Fix Postgres timezone arithmetic (now() - 86400 → interval) | High | 5m | ⏳ |
| 03 | Collector resilience audit — add try/except + backoff to all collectors | High | 20m | ⏳ |
| 04 | RSS feed health audit — flag feeds with >50% failure rate | Med | 15m | ⏳ |
| 05 | Error log noise reduction — suppress repetitive error patterns | Med | 10m | ⏳ |
| 06 | Fix Shodan collector graceful degradation on API errors | Med | 10m | ⏳ |
| 07 | Fix OpenSky rate limit backoff — should exponential back off | Med | 10m | ⏳ |
| 08 | Fix X/Twitter collector deduplication on tweet ID collision | Med | 10m | ⏳ |
| 09 | Fix Telegram collector reconnect on session expiry | Med | 15m | ⏳ |
| 10 | Fix market collector error handling on API timeout | Low | 10m | ⏳ |
| 11 | Fix flight collector NaN handling on missing altitude data | Low | 10m | ⏳ |
| 12 | Fix satellite collector error on cloud cover >100% edge case | Low | 10m | ⏳ |
| 13 | Fix cashtag collector crash on empty ticker response | Med | 10m | ⏳ |
| 14 | Fix co-occurrence engine timeout on very large entity sets | Med | 15m | ⏳ |
| 15 | Fix narrative engine stale lock on unclean shutdown | High | 15m | ⏳ |

## Frontend — Spec Compliance (16-25)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 16 | Frontend inline style audit — move static styles to CSS (SPEC.md:139) | Med | 20m | ⏳ |
| 17 | FeedView: move remaining inline styles to feed.css | Med | 10m | ⏳ |
| 18 | EntityDetail: move inline styles to entity-detail.css | Med | 10m | ⏳ |
| 19 | DashboardView: move inline styles to dashboard.css | Med | 10m | ⏳ |
| 20 | MapView: move inline styles to map.css | Med | 10m | ⏳ |
| 21 | Settings pages: audit all settings views for inline styles | Med | 15m | ⏳ |
| 22 | BriefsView: move inline styles to briefs.css | Low | 10m | ⏳ |
| 23 | AlertsPage: move inline styles to alerts.css | Low | 10m | ⏳ |
| 24 | ScheduledBriefsView: move inline styles to scheduled-briefs.css | Low | 10m | ⏳ |
| 25 | CasesView: move inline styles to cases.css | Low | 10m | ⏳ |

## Frontend — UX Improvements (26-40)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 26 | Feed: remove 1000-post store cap, use backend pagination | Med | 15m | ⏳ |
| 27 | Feed: add date range picker (24h, 7d, 30d, custom) | Med | 20m | ⏳ |
| 28 | Feed: show total count prominently | Low | 5m | ⏳ |
| 29 | Feed: better empty state messaging per filter | Low | 10m | ⏳ |
| 30 | Entities: add "show related" quick action on entity cards | Med | 15m | ⏳ |
| 31 | Narratives: add timeline visualization | Med | 20m | ⏳ |
| 32 | Narratives: add "export as brief" button | Low | 10m | ⏳ |
| 33 | Cases: add case activity timeline | Med | 15m | ⏳ |
| 34 | Dashboard: add source reliability summary widget | Med | 15m | ⏳ |
| 35 | Dashboard: add narrative velocity chart | Low | 15m | ⏳ |
| 36 | Dashboard: better mobile card layout | Low | 15m | ⏳ |
| 37 | Map: improve layer panel — collapsible categories | Med | 20m | ⏳ |
| 38 | Map: add fullscreen toggle | Low | 10m | ⏳ |
| 39 | Briefs: show confidence score per claim in generated briefs | Med | 15m | ⏳ |
| 40 | Loading skeletons for all views (replace "Loading..." text) | Med | 20m | ⏳ |

## Backend — Core Improvements (41-55)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 41 | Entity merge backend — POST /entities/{id}/merge + candidates API | High | 30m | ⏳ |
| 42 | Entity merge migration — merged_into, merge_date columns | High | 10m | ⏳ |
| 43 | Source health dashboard — error_count, last_error, uptime % | Med | 15m | ⏳ |
| 44 | Source auto-disable after N consecutive failures | Med | 15m | ⏳ |
| 45 | Feed pagination — remove any backend page size caps | Med | 10m | ⏳ |
| 46 | Add source_class and reliability to source list API response | Med | 10m | ⏳ |
| 47 | Rate limit auth endpoints (login, register) | High | 15m | ⏳ |
| 48 | Add request logging middleware (structured JSON) | Med | 15m | ⏳ |
| 49 | Database connection pool tuning | Med | 10m | ⏳ |
| 50 | Add graceful shutdown — cancel all tasks on SIGTERM | Med | 15m | ⏳ |
| 51 | Add /metrics Prometheus endpoint | Low | 20m | ⏳ |
| 52 | Backup script improvements — compression, rotation | Med | 15m | ⏳ |
| 53 | Add database migration rollback safety checks | Med | 10m | ⏳ |
| 54 | Add per-user rate limiting on API endpoints | Med | 20m | ⏳ |
| 55 | Add health check for external API dependencies | Low | 15m | ⏳ |

## Model Router & AI (56-65)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 56 | Add model usage tracking — log every LLM call to DB | Med | 20m | ⏳ |
| 57 | Add cost estimation per task based on token counts | Low | 15m | ⏳ |
| 58 | Add model fallback health check — skip unhealthy providers | Med | 15m | ⏳ |
| 59 | Add embedding cache — cache vectors for repeated text | Med | 20m | ⏳ |
| 60 | Add structured output support for compatible models | Low | 15m | ⏳ |
| 61 | Improve model router error messages — more actionable | Low | 10m | ⏳ |
| 62 | Add per-task timeout configuration | Med | 10m | ⏳ |
| 63 | Add model performance tracking (latency, error rate) | Low | 15m | ⏳ |
| 64 | Add support for thinking/reasoning models (Claude, Gemini) | Low | 20m | ⏳ |
| 65 | Add streaming support for brief generation | Low | 25m | ⏳ |

## Entity & Narrative Intelligence (66-75)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 66 | Entity merge workflow — safe merge with mention reassignment | High | 30m | ⏳ |
| 67 | Entity aliases — show in entity detail UI | Med | 15m | ⏳ |
| 68 | Entity merge suggestions — show in entity detail | Med | 15m | ⏳ |
| 69 | Entity timeline — show mention frequency over time | Med | 20m | ⏳ |
| 70 | Entity co-occurrence detail — show top related entities | Med | 15m | ⏳ |
| 71 | Narrative detail — related narratives (shared entities) | Med | 20m | ⏳ |
| 72 | Narrative detail — post volume sparkline | Low | 15m | ⏳ |
| 73 | Narrative lifecycle — auto-resolve stale after TTL | Med | 15m | ⏳ |
| 74 | Narrative merging — detect and merge duplicate narratives | Med | 25m | ⏳ |
| 75 | Tracked narrative matching improvements | Med | 20m | ⏳ |

## Source Expansion (76-85)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 76 | Sprint 33 CP1a — Ransomware leak blog clearnet mirrors | Med | 25m | ⏳ |
| 77 | Sprint 33 CP1b — Paste site monitoring (Pastebin, Rentry) | Med | 20m | ⏳ |
| 78 | Sprint 33 CP1c — Have I Been Pwned API integration | Med | 15m | ⏳ |
| 79 | Sprint 33 CP1d — Ahmia.fi dark web search integration | Low | 20m | ⏳ |
| 80 | Source reliability auto-scoring — track claim corroboration | Med | 25m | ⏳ |
| 81 | Add more Telegram Wave 2 channels (vetted list) | Med | 15m | ⏳ |
| 82 | Add additional diplomatic RSS feeds (UK FCDO, Israeli MFA) | Low | 15m | ⏳ |
| 83 | Add additional maritime intelligence sources | Low | 15m | ⏳ |
| 84 | Source scheduling — per-source poll interval configuration | Low | 20m | ⏳ |
| 85 | Source content filtering — pre-ingest keyword/type filters | Low | 20m | ⏳ |

## API & Developer Experience (86-92)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 86 | API documentation — markdown reference of all endpoints | Low | 20m | ⏳ |
| 87 | API versioning — add /api/v1 prefix | Low | 15m | ⏳ |
| 88 | API response consistency — standardize error format | Med | 15m | ⏳ |
| 89 | API pagination — consistent limit/offset across all list endpoints | Med | 20m | ⏳ |
| 90 | Webhook delivery confirmation — track webhook delivery status | Low | 15m | ⏳ |
| 91 | API key scoping — allow read-only API keys | Low | 20m | ⏳ |
| 92 | Agent API docs — expand agent endpoint documentation | Low | 15m | ⏳ |

## Testing & Quality (93-100)

| # | Task | Priority | Est. | Status |
|---|------|----------|------|--------|
| 93 | Set up pytest infrastructure + test database fixture | High | 20m | ⏳ |
| 94 | Auth flow tests — login, session, token validation | High | 20m | ⏳ |
| 95 | Entity search tests — pagination, filtering, alias-aware search | Med | 20m | ⏳ |
| 96 | Narrative engine tests — clustering, labeling, confidence | Med | 25m | ⏳ |
| 97 | Model router tests — provider routing, fallback, capability flags | Med | 20m | ⏳ |
| 98 | Collector tests — mock external APIs, test error handling | Med | 25m | ⏳ |
| 99 | API endpoint smoke tests — all public endpoints return 200 | Med | 20m | ⏳ |
| 100 | CI-ready test runner config + README update | Low | 10m | ⏳ |

---

## Status Tracker

| Task | Status | Started | Completed | Notes |
|------|--------|---------|-----------|-------|
| 01 | ✅ Done | 10:14 | 10:16 | Added 120s startup delay to narrative engine |
| 02 | ✅ Done | 10:14 | 10:16 | No bug found — codebase already uses correct interval syntax |
| 03 | ✅ Done | 10:16 | 10:21 | Exponential backoff added to rss_collector |
| 04 | ✅ Done | 10:16 | 10:21 | RSS health tracking + State Dept _Entry.get() bug fix |
| 05 | ✅ Done | 10:16 | 10:21 | Log noise: OPEC 403 suppressed, Nominatim 429 rate-limited |
| 06 | ✅ Done | 10:16 | 10:22 | Shodan: permanently disabled on 401/403 |
| 07 | ✅ Done | 10:16 | 10:22 | OpenSky: exponential backoff 60s→900s |
| 08 | ✅ Done | 10:16 | 10:22 | Telegram: session expiry reconnect with 10s delay |
| 09 | ✅ Done | 10:16 | 10:22 | Market: 30s timeout on yfinance calls |
| 10 | ✅ Done | 10:16 | 10:22 | Cashtag: defensive empty response parsing |
| 11 | ✅ Done | 10:21 | 10:25 | Flight: NaN handling via _safe_float helper |
| 12 | ✅ Done | 10:21 | 10:25 | Satellite: cloud cover clamped to 0-100 |
| 13 | ✅ Done | 10:21 | 10:25 | Cashtag: empty ticker list guard |
| 14 | ✅ Done | 10:21 | 10:25 | Co-occurrence: batch processing + 30s timeout |
| 15 | ✅ Done | 10:21 | 10:25 | Narrative engine: file-based lock with 5min TTL |
| 16-25 | 🔄 Running | 10:24 | — | Frontend inline style audit |
| 26-30 | ✅ Done | 10:22 | 10:30 | Feed cap removed, date picker, total count, empty state, entity related |
| 31-40 | 🔄 Running | 10:25 | — | Frontend features |
| 41-50 | ✅ Done | 10:25 | 10:38 | Entity merge backend, candidates API, source health, auto-disable, auth rate limit, request logging, DB pool tuning, graceful shutdown |
| 51-60 | ✅ Done | 10:26 | 10:33 | /metrics, backup script, migration safety, rate limiting, health deps, usage tracking, cost est, fallback health, embedding cache, task timeouts |
| 61-70 | 🔄 Running | 10:30 | — | Model router features + entity/narrative UI |
| 71-80 | 🔄 Running | 10:33 | — | Narrative merging + briefs + dark web + API consistency |
| 81-92 | 🔄 Running | 10:38 | — | Sources + API + webhooks + frontend |
| 93-100 | ⏳ Queued | — | — | Testing & quality — waiting for slot |

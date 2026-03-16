# Sprint Plan — Orthanc OSINT Platform

**Status:** Active
**Last updated:** 2026-03-16
**Sprints completed:** 1–32 + Stability Sprint

---

## Completed Sprints (committed)

| Sprint | Commit | Description |
|--------|--------|-------------|
| 1–16 | various | Core platform (feed, narratives, entities, map, briefs, auth, Docker) |
| 17 | `736b452` | LLM Provider Framework (model router, Ollama, OpenAI-compat) |
| 19–20 | `7543bec` | Frontline history + Entity relationship graph |
| 22 | | Production hardening (health, rate limit, backup scripts) |
| 25–28 | `6ee38d0` | Narrative intelligence, tracked narratives, entity resolution |
| 29 | `aed36b4` | Source reliability and confidence layer |
| 30 | `0887645` | Agent access API |
| 31 | `f535829` | Scheduled delivery and automation |
| 32 | `17e4267` | Source expansion (official, sanctions, maritime, Telegram Wave 1) |
| Stability | `ea915ea` | Embedding fix, X API v2, geo/rate-limit/RSS fixes |

---

## Remaining / Incomplete Sprints

### Sprint 25 CP4 — Frontend Narrative Display
**Status:** ~80% complete — only frontend display remains
- [ ] Narratives view: show `canonical_title` instead of `raw_title` when available
- [ ] Show `narrative_type` badge (state_action, military, diplomatic, etc.)
- [ ] Show `label_confidence` indicator (subtle, not noisy)
- [ ] Show `confirmation_status` where present
- [ ] Narrative detail view: show canonical claim
- [ ] Graceful fallback when canonical fields are null

### Sprint 26 — Tracked Narratives Expansion
**Status:** ~0% complete
- [ ] Richer tracked narrative fields (hypothesis, description, entity_ids, keywords, claim_patterns, status, model_policy)
- [ ] Versioning of criteria
- [ ] Evidence classification (supports / contradicts / contextual / unclear)
- [ ] Evidence timeline and source-group divergence
- [ ] Create/edit/review UI for tracked narratives
- [ ] Longitudinal evolution view

### Sprint 27 — Entity Merge Workflow
**Status:** ~25% complete (entity aliases done)
- [ ] Merge candidates API (confidence + rationale)
- [ ] Manual merge endpoint: reassign mentions, preserve aliases, retain canonical
- [ ] Safe merge — no destructive blind deletes
- [ ] Downstream resolution after merge (graph, narratives, search)
- [ ] Entity detail: show aliases, merge suggestions

### Sprint 28 — Frontend Entity Polish
**Status:** ~60% complete (backend search done)
- [ ] Entity browser: pagination, real totals ("1–50 of 5,318")
- [ ] Entity pickers/dropdowns use backend search, not local cache
- [ ] Remove misleading "500/500" counts

---

## New Sprints (not started)

### Sprint 33 — Dark/Deep Web Sources
**Approved:** 2026-03-16

#### CP1: Clearnet dark/deep web
- Ransomware leak blog clearnet mirrors (RansomHub, LockBit, Cl0p, Medusa, Play, ALPHV)
- Paste site monitoring (Pastebin, Rentry.co, ghostbin, justpaste.it)
- Breach indices (Have I Been Pwned API, IntelX)
- Ahmia.fi topic search

#### CP2: Tor proxy integration
- Tor daemon (Docker container, SOCKS5 proxy)
- Route httpx through `socks5://tor:9050`
- Onion-accessible ransomware leak blogs
- Dark web indices

#### CP3: Source class and reliability model
- `dark_web` source class with low reliability prior
- Provenance always captured
- Risk notes per source
- Reliability priors flowing into confidence logic

#### CP4: UI surfacing
- Dark web sources visible in Sources UI
- Reliability badges
- Confidence adjustments in briefs

---

## Known Issues / Tech Debt

| Issue | Severity | Notes |
|-------|----------|-------|
| Startup race condition | Low | Embedding calls before provider registration — works after startup, ~13 empty vectors on restart |
| PLAN.md out of date | Low | This file — needs periodic refresh |
| State Dept RSS | Medium | Feed has malformed XML, regex fallback works but is fragile |
| OPEC 403 | Medium | May still block server IPs regardless of headers |
| Postgres timezone query | Low | SQL `now() - 86400` fails (needs `interval '1 day'` cast) |

---

## Priority Order

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| 🔴 High | Sprint 25 CP4 (narrative frontend) | Small | Completes 80%-done sprint |
| 🔴 High | Sprint 28 (entity polish) | Small | Completes 60%-done sprint |
| 🟡 Medium | Sprint 27 (entity merge) | Medium | Clean data model |
| 🟡 Medium | Sprint 33 CP1 (clearnet dark/deep) | Medium | New source coverage |
| 🟢 Lower | Sprint 26 (tracked narratives) | Large | Rich analyst workflow |
| 🟢 Lower | Sprint 33 CP2 (Tor integration) | Medium | Requires Tor proxy |

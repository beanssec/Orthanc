# Sprint Plan — Claim Extraction & SOAR-like Narrative Intelligence

**Status:** Planning
**Created:** 2026-03-16
**Goal:** Transform narratives from topic clusters into claim-tracking incidents with evidence correlation

---

## Architecture

### Existing infrastructure (reused)
- Narrative clustering → incident creation (already working)
- Entity co-occurrence → evidence graph (already working)
- Embedding similarity → claim matching (already working)
- Model router → task-based model selection (already working)
- Ollama provider → local model support (already working)
- Tracked narratives → playbook rules (already working)

### New addition
- Claim extraction enrichment layer on narrative clusters
- Support/contradict evidence classification
- Triage workflow for analysts
- New task constant: `TASK_CLAIM_EXTRACTION`

---

## Checkpoint 1: Claim extraction enrichment layer
**Effort:** ~2 subagent runs

### Backend
- Add `TASK_CLAIM_EXTRACTION` to model_router defaults
  - Default: `qwen3:9b` (Ollama local) or `openai/gpt-4o-mini` (OpenRouter)
  - Add to task-model-override DB table + frontend settings
- Add claim fields to Narrative model:
  - `claim_text` (text, nullable) — extracted claim assertion
  - `claimant` (text, nullable) — who's making the claim
  - `claim_type` (text, nullable) — victory_declaration, attribution, threat, prediction, denial, denial_of_service, other
  - `claim_confidence` (float, nullable) — LLM confidence in extraction
  - `claim_extracted_at` (timestamp, nullable)
- Migration: add columns (chain from 038)
- Add `claim_extractor.py` service:
  - `extract_claim(narrative_id, posts_summary) → {claim_text, claimant, claim_type, confidence}`
  - Takes the narrative cluster summary (top posts, entity names, canonical title)
  - Sends to model_router with TASK_CLAIM_EXTRACTION
  - Parses structured JSON response
  - Called once per narrative cycle, only for narratives with ≥5 posts
  - Cheap model only — gpt-4o-mini or local qwen3:9b
- Wire into narrative engine: after clustering, call claim extractor for narratives without claims

### Frontend
- NarrativeCard: show claim_text when present, with claimant label
- NarrativeDetail: show claim prominently — "Claim: [text] — [claimant]"
- Claim type badge

### Migration
- New migration (039 or next available) adding claim fields to narratives

---

## Checkpoint 2: Evidence classification
**Effort:** ~1-2 subagent runs

### Backend
- Add evidence relationship fields to NarrativePost (the join table):
  - `evidence_role` (text, nullable) — supports, contradicts, contextual, unclear
  - `evidence_confidence` (float, nullable)
  - `evidence_classified_at` (timestamp, nullable)
- Migration: add columns
- Add `evidence_classifier.py` service:
  - `classify_evidence(narrative_claim, posts) → [{post_id, role, confidence}]`
  - Batches posts (up to 20) into a single LLM call
  - Uses the same TASK_CLAIM_EXTRACTION model (cheap)
  - Only classifies posts that haven't been classified yet
  - Called after claim extraction, runs in the narrative engine cycle
- Update narrative engine cycle:
  1. Cluster posts (existing)
  2. Extract claim if missing (new)
  3. Classify new post evidence against claim (new)
  4. Update support/contradict counts on narrative

### Frontend
- NarrativeDetail: group posts by evidence role (supports / contradicts / contextual)
- Show support vs contradict ratio as a visual indicator
- Color-coded tabs or sections

---

## Checkpoint 3: Triage workflow
**Effort:** ~1 subagent run

### Backend
- Add `triage_status` field to narratives:
  - `detected` (default) — newly extracted claim
  - `under_review` — analyst is reviewing
  - `confirmed` — claim is tracked
  - `contradicted` — claim has been debunked
  - `archived` — no longer relevant
- Add triage API endpoints:
  - `POST /narratives/{id}/triage` — update triage status
  - `POST /narratives/{id}/confirm-claim` — confirm with optional note
  - `POST /narratives/{id}/contradict-claim` — contradict with evidence note
  - `POST /narratives/{id}/merge-claims` — merge two claim narratives
- Add `triage_notes` field (text, nullable) for analyst notes

### Frontend
- NarrativesView: filter by triage_status (detected, under_review, confirmed, contradicted, archived)
- NarrativeDetail: triage action buttons (Confirm, Contradict, Archive, Merge)
- Dashboard: "Claims awaiting review" count
- Narratives needing review shown with a highlighted border or badge

---

## Checkpoint 4: Dashboard + tracked narrative playbook integration
**Effort:** ~1 subagent run

### Dashboard
- New widget: "Claims Summary"
  - Total active claims
  - Claims awaiting review
  - Most contradicted claims this week
  - Top claimants
- Update "Trending Narratives" to show claim_text and support/contradict ratio

### Tracked narratives as playbook rules
- When a tracked narrative matches new posts, auto-extract claim from the matched content
- Tracked narrative keywords become the "detection rule"
- Matched posts are auto-classified as evidence

### Brief integration
- Brief generator includes claim context:
  - "Active claims in this period: [list]"
  - "Most contradicted claim: [claim] (X contradicting posts)"
- Adds claim-awareness to intelligence briefs

---

## Task queue entry for local model usage

### Recommended model assignment

| Task | Default Model | Why |
|---|---|---|
| TASK_CLAIM_EXTRACTION | `qwen3:9b` (Ollama) or `openai/gpt-4o-mini` | Fast, cheap, capable of structured JSON |
| TASK_EVIDENCE_CLASSIFY | `qwen3:9b` (Ollama) or `openai/gpt-4o-mini` | Same — batch classification is simple |
| TASK_NARRATIVE_LABEL | `openai/gpt-4o` or `anthropic/claude-sonnet-4` | Needs better reasoning for titles |
| TASK_BRIEF | `anthropic/claude-sonnet-4` | Needs strong writing |
| TASK_EMBED | `openai/text-embedding-3-small` | Already set |

Users can configure all of these via Settings → Models → Task Assignments.

---

## Data model summary (new/modified fields)

### Narratives table (modified)
```sql
ALTER TABLE narratives ADD COLUMN claim_text TEXT;
ALTER TABLE narratives ADD COLUMN claimant TEXT;
ALTER TABLE narratives ADD COLUMN claim_type TEXT; -- victory_declaration, attribution, threat, prediction, denial, other
ALTER TABLE narratives ADD COLUMN claim_confidence FLOAT;
ALTER TABLE narratives ADD COLUMN claim_extracted_at TIMESTAMPTZ;
ALTER TABLE narratives ADD COLUMN triage_status TEXT DEFAULT 'detected'; -- detected, under_review, confirmed, contradicted, archived
ALTER TABLE narratives ADD COLUMN triage_notes TEXT;
```

### narrative_posts table (modified)
```sql
ALTER TABLE narrative_posts ADD COLUMN evidence_role TEXT; -- supports, contradicts, contextual, unclear
ALTER TABLE narrative_posts ADD COLUMN evidence_confidence FLOAT;
ALTER TABLE narrative_posts ADD COLUMN evidence_classified_at TIMESTAMPTZ;
```

---

## Progress

| Checkpoint | Status | Subagent | Notes |
|---|---|---|---|
| CP1 — Claim extraction backend | ✅ Done | claim-cp1-extraction | migration 039, claim_extractor service, wired into engine |
| CP2 — Evidence classification | ✅ Done | claim-cp2-evidence | migration 041, evidence_classifier, engine integration, API counts |
| CP3 — Triage workflow | ✅ Done | claim-cp3-triage | migration 040, 3 endpoints, filter added |
| CP4 — Dashboard + playbook | 🔄 Running | claim-cp4-dashboard | |
| Phase 3 — Deploy | ⏳ Queued | — | Waiting for CP4 |

## Estimated total effort
- Checkpoint 1: ~30 min (claim extraction + migration + frontend)
- Checkpoint 2: ~25 min (evidence classification + frontend)
- Checkpoint 3: ~20 min (triage workflow + API + frontend)
- Checkpoint 4: ~20 min (dashboard + brief integration)

Total: ~90 minutes of elapsed time, 4-6 subagent runs

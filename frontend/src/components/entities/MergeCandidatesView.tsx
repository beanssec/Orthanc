/**
 * MergeCandidatesView — Sprint 27 Checkpoint 4
 *
 * Minimal UI to review and action entity merge candidates surfaced by the
 * backend deduplication engine.  An analyst can:
 *   1. Browse candidate pairs with confidence + signal reasons.
 *   2. Confirm-then-merge a pair (POST /{primary_id}/merge).
 *   3. Skip/dismiss a pair (client-side only — no persisted skip flag yet).
 *
 * Deliberately lightweight: no pagination, no editing, no bulk ops.
 */

import { useCallback, useEffect, useState } from 'react';
import api from '../../services/api';

// ── Types ──────────────────────────────────────────────────────────────────────
interface MergeCandidateEntity {
  id: string;
  name: string;
  type: string;
  canonical_name: string;
  mention_count: number;
}

interface MergeCandidate {
  primary: MergeCandidateEntity;
  duplicate: MergeCandidateEntity;
  confidence: number;
  reasons: string[];
}

interface MergeCandidateResponse {
  candidates: MergeCandidate[];
  total: number;
  min_confidence: number;
  same_type_only: boolean;
}

interface MergeResult {
  status: string;
  primary_id: string;
  merged_ids: string[];
  mentions_reassigned: number;
  aliases_added: number;
  aliases_skipped_duplicate: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function confidenceColor(conf: number): string {
  if (conf >= 0.85) return '#10b981';
  if (conf >= 0.65) return '#f59e0b';
  return '#ef4444';
}

function confidenceLabel(conf: number): string {
  if (conf >= 0.85) return 'HIGH';
  if (conf >= 0.65) return 'MED';
  return 'LOW';
}

function reasonLabel(reason: string): string {
  const map: Record<string, string> = {
    exact_canonical_match: 'Exact canonical name',
    alias_canonical_overlap: 'Alias ↔ canonical match',
    alias_alias_overlap: 'Shared alias',
  };
  return map[reason] ?? reason.replace(/_/g, ' ');
}

function entityTypeClass(type: string): string {
  const map: Record<string, string> = {
    PERSON: 'person', ORG: 'org', GPE: 'gpe', EVENT: 'event', NORP: 'norp',
  };
  return map[type?.toUpperCase()] ?? 'norp';
}

// ── Confirmation modal ────────────────────────────────────────────────────────
interface ConfirmMergeModalProps {
  candidate: MergeCandidate;
  onConfirm: () => void;
  onCancel: () => void;
  merging: boolean;
  error: string | null;
}

function ConfirmMergeModal({ candidate, onConfirm, onCancel, merging, error }: ConfirmMergeModalProps) {
  return (
    <div className="merge-modal-backdrop" onClick={onCancel}>
      <div className="merge-modal" onClick={e => e.stopPropagation()}>
        <div className="merge-modal__header">
          <span className="merge-modal__title">⚠ Confirm Entity Merge</span>
          <button className="merge-modal__close" onClick={onCancel} disabled={merging}>✕</button>
        </div>

        <div className="merge-modal__body">
          <p className="merge-modal__warning">
            This action is <strong>irreversible</strong>. The duplicate entity will be
            absorbed into the primary and deleted.
          </p>

          <div className="merge-modal__pair">
            <div className="merge-modal__entity merge-modal__entity--primary">
              <div className="merge-modal__entity-role">KEEP (primary)</div>
              <span className={`badge badge--${entityTypeClass(candidate.primary.type)}`}>
                {candidate.primary.type}
              </span>
              <span className="merge-modal__entity-name">{candidate.primary.name}</span>
              <span className="merge-modal__entity-meta">
                {candidate.primary.mention_count.toLocaleString()} mentions
              </span>
            </div>

            <div className="merge-modal__arrow">↓ absorbs</div>

            <div className="merge-modal__entity merge-modal__entity--duplicate">
              <div className="merge-modal__entity-role">REMOVE (duplicate)</div>
              <span className={`badge badge--${entityTypeClass(candidate.duplicate.type)}`}>
                {candidate.duplicate.type}
              </span>
              <span className="merge-modal__entity-name">{candidate.duplicate.name}</span>
              <span className="merge-modal__entity-meta">
                {candidate.duplicate.mention_count.toLocaleString()} mentions → reassigned
              </span>
            </div>
          </div>

          <div className="merge-modal__signals">
            <span className="merge-modal__signals-label">Signals:</span>
            {candidate.reasons.map(r => (
              <span key={r} className="merge-modal__reason-pill">{reasonLabel(r)}</span>
            ))}
            <span
              className="merge-modal__confidence-badge"
              style={{ color: confidenceColor(candidate.confidence) }}
            >
              {Math.round(candidate.confidence * 100)}% {confidenceLabel(candidate.confidence)}
            </span>
          </div>

          {error && (
            <div className="merge-modal__error">⚠ {error}</div>
          )}

          <div className="merge-modal__actions">
            <button className="btn btn-secondary" onClick={onCancel} disabled={merging}>
              Cancel
            </button>
            <button
              className="btn btn-danger"
              onClick={onConfirm}
              disabled={merging}
            >
              {merging ? 'Merging…' : '🔀 Merge Entities'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
interface MergeCandidatesViewProps {
  /** Called after a successful merge so the parent can refresh entity lists */
  onMergeComplete?: () => void;
}

export function MergeCandidatesView({ onMergeComplete }: MergeCandidatesViewProps) {
  const [candidates, setCandidates] = useState<MergeCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [minConfidence, setMinConfidence] = useState(0.5);
  const [sameTypeOnly, setSameTypeOnly] = useState(false);

  // Merge flow state
  const [confirmCandidate, setConfirmCandidate] = useState<MergeCandidate | null>(null);
  const [merging, setMerging] = useState(false);
  const [mergeError, setMergeError] = useState<string | null>(null);

  // Success flash
  const [lastMerged, setLastMerged] = useState<MergeResult | null>(null);

  const fetchCandidates = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get<MergeCandidateResponse>('/entities/merge-candidates', {
        params: { min_confidence: minConfidence, same_type_only: sameTypeOnly, limit: 100 },
      })
      .then(res => {
        setCandidates(res.data.candidates);
        setSkipped(new Set()); // reset skips on reload
      })
      .catch(err => {
        const msg = (err as { message?: string })?.message ?? 'Failed to load merge candidates';
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [minConfidence, sameTypeOnly]);

  useEffect(() => {
    fetchCandidates();
  }, [fetchCandidates]);

  const handleMergeConfirm = useCallback(async () => {
    if (!confirmCandidate) return;
    setMerging(true);
    setMergeError(null);
    try {
      const result = await api.post<MergeResult>(
        `/entities/${confirmCandidate.primary.id}/merge`,
        { secondary_ids: [confirmCandidate.duplicate.id], preserve_aliases: true }
      );
      setLastMerged(result.data);
      // Remove the merged pair from the visible list
      const pairKey = `${confirmCandidate.primary.id}:${confirmCandidate.duplicate.id}`;
      setCandidates(prev =>
        prev.filter(c =>
          `${c.primary.id}:${c.duplicate.id}` !== pairKey
        )
      );
      setConfirmCandidate(null);
      onMergeComplete?.();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMergeError(detail ?? 'Merge failed — check the console for details');
    } finally {
      setMerging(false);
    }
  }, [confirmCandidate, onMergeComplete]);

  const handleSkip = (candidate: MergeCandidate) => {
    const key = `${candidate.primary.id}:${candidate.duplicate.id}`;
    setSkipped(prev => new Set([...prev, key]));
  };

  const visible = candidates.filter(
    c => !skipped.has(`${c.primary.id}:${c.duplicate.id}`)
  );

  return (
    <div className="merge-candidates">
      {/* ── Toolbar ── */}
      <div className="merge-candidates__toolbar">
        <div className="merge-candidates__toolbar-left">
          <span className="merge-candidates__title">🔀 Merge Review</span>
          {!loading && (
            <span className="merge-candidates__count">
              {visible.length} candidate{visible.length !== 1 ? 's' : ''}
              {skipped.size > 0 && (
                <span className="merge-candidates__skipped-count"> · {skipped.size} skipped</span>
              )}
            </span>
          )}
        </div>

        <div className="merge-candidates__toolbar-right">
          {/* Min confidence filter */}
          <div className="merge-candidates__filter">
            <label className="merge-candidates__filter-label">Min confidence</label>
            <select
              className="select select--sm"
              value={minConfidence}
              onChange={e => setMinConfidence(Number(e.target.value))}
            >
              <option value={0.5}>≥ 50%</option>
              <option value={0.65}>≥ 65%</option>
              <option value={0.8}>≥ 80%</option>
              <option value={0.9}>≥ 90%</option>
            </select>
          </div>

          {/* Same-type filter */}
          <label className="merge-candidates__filter merge-candidates__filter--toggle">
            <input
              type="checkbox"
              checked={sameTypeOnly}
              onChange={e => setSameTypeOnly(e.target.checked)}
            />
            <span>Same type only</span>
          </label>

          <button
            className="btn btn-secondary btn-sm"
            onClick={fetchCandidates}
            disabled={loading}
          >
            {loading ? 'Loading…' : '⟳ Refresh'}
          </button>
        </div>
      </div>

      {/* ── Success flash ── */}
      {lastMerged && (
        <div className="merge-candidates__success-banner">
          ✓ Merge complete — {lastMerged.mentions_reassigned.toLocaleString()} mentions
          reassigned, {lastMerged.aliases_added} alias{lastMerged.aliases_added !== 1 ? 'es' : ''} added.{' '}
          <button
            className="merge-candidates__dismiss-btn"
            onClick={() => setLastMerged(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* ── Body ── */}
      {loading ? (
        <div className="entities-loading">
          <span className="spinner" />
          Scanning for duplicate entities…
        </div>
      ) : error ? (
        <div className="entities-error">⚠ {error}</div>
      ) : visible.length === 0 ? (
        <div className="merge-candidates__empty">
          <span className="merge-candidates__empty-icon">✅</span>
          <span className="merge-candidates__empty-title">No merge candidates</span>
          <span className="merge-candidates__empty-sub">
            {skipped.size > 0
              ? `All candidates skipped. Adjust filters or refresh to reload.`
              : `No duplicate entity pairs found at ≥${Math.round(minConfidence * 100)}% confidence.`}
          </span>
        </div>
      ) : (
        <div className="merge-candidates__list">
          {visible.map((c, idx) => {
            const confColor = confidenceColor(c.confidence);
            const confPct = Math.round(c.confidence * 100);
            return (
              <div key={`${c.primary.id}:${c.duplicate.id}`} className="merge-card">
                {/* Index badge */}
                <div className="merge-card__index">{idx + 1}</div>

                {/* Entities */}
                <div className="merge-card__pair">
                  {/* Primary */}
                  <div className="merge-card__entity merge-card__entity--primary">
                    <div className="merge-card__entity-role">PRIMARY (keep)</div>
                    <div className="merge-card__entity-body">
                      <span className={`badge badge--${entityTypeClass(c.primary.type)}`}>
                        {c.primary.type}
                      </span>
                      <span className="merge-card__entity-name">{c.primary.name}</span>
                    </div>
                    {c.primary.canonical_name && c.primary.canonical_name !== c.primary.name && (
                      <div className="merge-card__canonical">
                        canonical: <em>{c.primary.canonical_name}</em>
                      </div>
                    )}
                    <div className="merge-card__mentions">
                      {c.primary.mention_count.toLocaleString()} mentions
                    </div>
                  </div>

                  {/* Arrow */}
                  <div className="merge-card__arrow">↔</div>

                  {/* Duplicate */}
                  <div className="merge-card__entity merge-card__entity--duplicate">
                    <div className="merge-card__entity-role">DUPLICATE (remove)</div>
                    <div className="merge-card__entity-body">
                      <span className={`badge badge--${entityTypeClass(c.duplicate.type)}`}>
                        {c.duplicate.type}
                      </span>
                      <span className="merge-card__entity-name">{c.duplicate.name}</span>
                    </div>
                    {c.duplicate.canonical_name && c.duplicate.canonical_name !== c.duplicate.name && (
                      <div className="merge-card__canonical">
                        canonical: <em>{c.duplicate.canonical_name}</em>
                      </div>
                    )}
                    <div className="merge-card__mentions">
                      {c.duplicate.mention_count.toLocaleString()} mentions
                    </div>
                  </div>
                </div>

                {/* Signals + confidence */}
                <div className="merge-card__meta">
                  <div className="merge-card__reasons">
                    {c.reasons.map(r => (
                      <span key={r} className="merge-card__reason-pill">{reasonLabel(r)}</span>
                    ))}
                  </div>
                  <div
                    className="merge-card__confidence"
                    style={{ color: confColor }}
                  >
                    <span className="merge-card__confidence-pct">{confPct}%</span>
                    <span className="merge-card__confidence-label">
                      {confidenceLabel(c.confidence)}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="merge-card__actions">
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleSkip(c)}
                    title="Skip this pair for now"
                  >
                    Skip
                  </button>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => { setConfirmCandidate(c); setMergeError(null); }}
                    title="Merge duplicate into primary"
                  >
                    🔀 Merge
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Confirmation modal ── */}
      {confirmCandidate && (
        <ConfirmMergeModal
          candidate={confirmCandidate}
          onConfirm={handleMergeConfirm}
          onCancel={() => { if (!merging) setConfirmCandidate(null); }}
          merging={merging}
          error={mergeError}
        />
      )}
    </div>
  );
}

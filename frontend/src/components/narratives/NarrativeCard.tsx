import type { Narrative } from './types';
import { timeAgo, divergenceClass, pct } from './utils';

interface NarrativeCardProps {
  narrative: Narrative;
  selected: boolean;
  onClick: () => void;
}

/** Thin pill for narrative_type — only renders when a type is present. */
function NarrativeTypePill({ type }: { type: string | null }) {
  if (!type) return null;
  return (
    <span className="narrative-type-pill">
      {type.replace(/_/g, ' ')}
    </span>
  );
}

/** Small colored dot indicating label confidence. Only shown when confidence is present. */
function ConfidenceDot({ confidence }: { confidence: number | null }) {
  if (confidence == null) return null;
  const cls = confidence > 0.7 ? 'high' : confidence > 0.4 ? 'mid' : 'low';
  return <span className={`narrative-confidence-dot ${cls}`} title={`Label confidence: ${Math.round(confidence * 100)}%`} />;
}

export function NarrativeCard({ narrative, selected, onClick }: NarrativeCardProps) {
  const divClass = divergenceClass(narrative.divergence_score);
  // Prefer canonical_title when available; fall back to legacy title
  const displayTitle = narrative.canonical_title ?? narrative.title;
  // Truncate claim_text to ~80 chars for the card subtitle
  const claimPreview = narrative.claim_text
    ? narrative.claim_text.length > 80
      ? narrative.claim_text.slice(0, 79) + '…'
      : narrative.claim_text
    : null;

  return (
    <div
      className={`narrative-card ${divClass}${selected ? ' selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      <div className="narrative-card-title">{displayTitle}</div>

      {/* Claim info — shown when claim extraction has run */}
      {claimPreview && (
        <div className="narrative-card-claim">
          <span className="narrative-card-claim__text">{claimPreview}</span>
          {narrative.claimant && (
            <span className="narrative-card-claim__claimant">{narrative.claimant}</span>
          )}
        </div>
      )}

      <div className="narrative-card-meta">
        <span>
          {narrative.post_count} posts
          {narrative.source_count != null && narrative.source_count > 0 && (
            <> · {narrative.source_count} sources</>
          )}
        </span>
        <NarrativeTypePill type={narrative.narrative_type} />
      </div>

      <div className="narrative-bar-row">
        <span className="narrative-bar-label">Divergence</span>
        <div className="narrative-bar">
          <div
            className="narrative-bar-fill divergence"
            style={{ width: pct(narrative.divergence_score) }}
          />
        </div>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', width: '32px', textAlign: 'right' }}>
          {pct(narrative.divergence_score)}
        </span>
      </div>

      <div className="narrative-bar-row">
        <span className="narrative-bar-label">Evidence</span>
        <div className="narrative-bar">
          <div
            className="narrative-bar-fill evidence"
            style={{ width: pct(narrative.evidence_score) }}
          />
        </div>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', width: '32px', textAlign: 'right' }}>
          {pct(narrative.evidence_score)}
        </span>
      </div>

      <div className="narrative-card-footer">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <span className="narrative-card-time">Updated {timeAgo(narrative.last_updated)}</span>
          <ConfidenceDot confidence={narrative.label_confidence} />
        </div>
        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
          {/* Prefer confirmation_status; fall back to legacy consensus. Never show "pending". */}
          {narrative.confirmation_status && narrative.confirmation_status !== 'pending' && (
            <span className={`confirmation-badge ${narrative.confirmation_status}`}>
              {narrative.confirmation_status.replace(/_/g, ' ')}
            </span>
          )}
          {!narrative.confirmation_status && narrative.consensus && (
            <span className={`consensus-badge ${narrative.consensus}`}>
              {narrative.consensus}
            </span>
          )}
          {narrative.triage_status && (
            <span className={`triage-badge triage-badge--${narrative.triage_status.replace(/_/g, '-')}`}>
              {narrative.triage_status.replace(/_/g, ' ')}
            </span>
          )}
          <span className={`narrative-status-badge ${narrative.status}`}>
            {narrative.status}
          </span>
        </div>
      </div>
    </div>
  );
}

export default NarrativeCard;

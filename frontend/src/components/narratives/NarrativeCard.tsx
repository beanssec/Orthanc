import { Narrative } from './types';
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

export function NarrativeCard({ narrative, selected, onClick }: NarrativeCardProps) {
  const divClass = divergenceClass(narrative.divergence_score);
  // Prefer canonical_title when available; fall back to legacy title
  const displayTitle = narrative.canonical_title ?? narrative.title;

  return (
    <div
      className={`narrative-card ${divClass}${selected ? ' selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      <div className="narrative-card-title">{displayTitle}</div>

      <div className="narrative-card-meta">
        <span>{narrative.post_count} posts</span>
        <span>{narrative.source_count} sources</span>
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
        <span className="narrative-card-time">Updated {timeAgo(narrative.last_updated)}</span>
        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
          {/* Prefer confirmation_status; fall back to legacy consensus */}
          {narrative.confirmation_status && (
            <span className={`confirmation-badge ${narrative.confirmation_status}`}>
              {narrative.confirmation_status.replace(/_/g, ' ')}
            </span>
          )}
          {!narrative.confirmation_status && narrative.consensus && (
            <span className={`consensus-badge ${narrative.consensus}`}>
              {narrative.consensus}
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

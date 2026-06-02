import type { NarrativeArc } from './types';
import { timeAgo } from './utils';

interface ArcCardProps {
  arc: NarrativeArc;
  selected: boolean;
  onClick: () => void;
}

function ArcTypePill({ type }: { type: string | null }) {
  if (!type) return null;
  return (
    <span className="narrative-type-pill">
      {type.replace(/_/g, ' ')}
    </span>
  );
}

export function ArcCard({ arc, selected, onClick }: ArcCardProps) {
  const summaryPreview = arc.summary
    ? arc.summary.length > 100
      ? arc.summary.slice(0, 99) + '…'
      : arc.summary
    : null;

  return (
    <div
      className={`narrative-card arc-card${selected ? ' selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
    >
      <div className="narrative-card-title">{arc.title}</div>

      {summaryPreview && (
        <div className="arc-card-summary">{summaryPreview}</div>
      )}

      <div className="arc-card-meta">
        <span>{arc.narrative_count} events</span>
        <span>{arc.total_post_count} posts</span>
        <span>{timeAgo(arc.last_updated)}</span>
      </div>

      <ArcTypePill type={arc.arc_type} />
    </div>
  );
}

export default ArcCard;

/**
 * Skeleton — reusable pulsing placeholder for loading states.
 * CSS-only animation via .skeleton-pulse class (defined in shared.css or skeleton.css).
 */

interface SkeletonProps {
  rows?: number;
  type?: 'list' | 'card' | 'table' | 'inline';
  className?: string;
}

export function Skeleton({ rows = 5, type = 'list', className = '' }: SkeletonProps) {
  if (type === 'card') {
    return (
      <div className={`skeleton-wrap ${className}`}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton-card">
            <div className="skeleton-pulse" style={{ width: '40%', height: '0.8rem' }} />
            <div className="skeleton-pulse" style={{ width: '100%', height: '0.75rem' }} />
            <div className="skeleton-pulse" style={{ width: '75%', height: '0.75rem' }} />
          </div>
        ))}
      </div>
    );
  }

  if (type === 'table') {
    return (
      <div className={`skeleton-wrap ${className}`}>
        <div className="skeleton-table-header">
          {[20, 30, 25, 15].map((w, i) => (
            <div key={i} className="skeleton-pulse" style={{ width: `${w}%`, height: '0.65rem', opacity: 0.5 }} />
          ))}
        </div>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton-table-row">
            <div className="skeleton-pulse" style={{ width: '20%' }} />
            <div className="skeleton-pulse" style={{ width: '30%' }} />
            <div className="skeleton-pulse" style={{ width: `${20 + (i % 3) * 10}%` }} />
            <div className="skeleton-pulse" style={{ width: '10%' }} />
          </div>
        ))}
      </div>
    );
  }

  if (type === 'inline') {
    return <div className={`skeleton-pulse ${className}`} style={{ display: 'inline-block', width: '6rem', height: '0.75rem', verticalAlign: 'middle' }} />;
  }

  // Default: list
  return (
    <div className={`skeleton-wrap ${className}`}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-list-row">
          <div className="skeleton-pulse" style={{ width: `${55 + (i % 4) * 10}%`, height: '0.85rem' }} />
          <div className="skeleton-pulse" style={{ width: `${30 + (i % 3) * 15}%`, height: '0.65rem', opacity: 0.6 }} />
        </div>
      ))}
    </div>
  );
}

export default Skeleton;

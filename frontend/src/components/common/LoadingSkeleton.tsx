export function LoadingSkeleton({
  rows = 5,
  type = 'list',
}: {
  rows?: number;
  type?: 'list' | 'card' | 'table';
}) {
  if (type === 'card') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="skeleton-card">
            <div className="skeleton-line" style={{ width: '40%' }} />
            <div className="skeleton-line" style={{ width: '100%' }} />
            <div className="skeleton-line" style={{ width: '75%' }} />
          </div>
        ))}
      </div>
    );
  }

  if (type === 'table') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {/* Header row */}
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.25rem' }}>
          <div className="skeleton-line" style={{ width: '20%', height: '0.75rem', opacity: 0.5 }} />
          <div className="skeleton-line" style={{ width: '30%', height: '0.75rem', opacity: 0.5 }} />
          <div className="skeleton-line" style={{ width: '25%', height: '0.75rem', opacity: 0.5 }} />
          <div className="skeleton-line" style={{ width: '15%', height: '0.75rem', opacity: 0.5 }} />
        </div>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <div className="skeleton-line" style={{ width: '20%' }} />
            <div className="skeleton-line" style={{ width: '30%' }} />
            <div className="skeleton-line" style={{ width: `${20 + (i % 3) * 10}%` }} />
            <div className="skeleton-line" style={{ width: '10%' }} />
          </div>
        ))}
      </div>
    );
  }

  // Default: list
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
          <div className="skeleton-line" style={{ width: `${55 + (i % 4) * 10}%` }} />
          <div className="skeleton-line" style={{ width: `${30 + (i % 3) * 15}%`, height: '0.75rem', opacity: 0.6 }} />
        </div>
      ))}
    </div>
  );
}

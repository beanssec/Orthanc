// Narrative Intelligence — utility functions

/**
 * Returns a relative time string ("2h ago", "5m ago", "3d ago")
 */
export function timeAgo(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;

  if (isNaN(diffMs)) return '—';

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

/**
 * Returns CSS class suffix for divergence score
 */
export function divergenceClass(score: number): string {
  if (score >= 0.66) return 'high-divergence';
  if (score >= 0.33) return 'medium-divergence';
  return 'low-divergence';
}

/**
 * Format a score (0-1) as a percentage string
 */
export function pct(score: number): string {
  return `${Math.round(score * 100)}%`;
}

/**
 * Map claim status to emoji icon
 */
export function claimStatusIcon(status: string): string {
  switch (status) {
    case 'confirmed': return '✅';
    case 'debunked':  return '❌';
    case 'disputed':  return '⚠️';
    default:          return '⏳';
  }
}

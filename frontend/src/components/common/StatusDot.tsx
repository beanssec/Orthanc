interface StatusDotProps {
  status: 'active' | 'warning' | 'error' | 'muted';
  title?: string;
}

export function StatusDot({ status, title }: StatusDotProps) {
  const cls = {
    active: 'status-dot status-dot-active',
    warning: 'status-dot status-dot-warning',
    error: 'status-dot status-dot-error',
    muted: 'status-dot status-dot-muted',
  }[status];

  return <span className={cls} title={title} />;
}

import React from 'react';

interface EmptyStateProps {
  icon?: string;
  message: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon = '📭', message, description, action }: EmptyStateProps) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '48px 24px',
      gap: '8px',
    }}>
      <span style={{ fontSize: '32px', lineHeight: 1 }}>{icon}</span>
      <p style={{ color: 'var(--text-secondary)', fontWeight: 500, marginTop: '8px' }}>{message}</p>
      {description && (
        <p style={{ color: 'var(--text-muted)', fontSize: '12px', textAlign: 'center' }}>{description}</p>
      )}
      {action && (
        <div style={{ marginTop: '12px' }}>{action}</div>
      )}
    </div>
  );
}

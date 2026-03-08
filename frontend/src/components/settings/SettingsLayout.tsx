import { NavLink, Outlet } from 'react-router-dom';

const TABS = [
  { to: '/settings/sources', label: 'Sources' },
  { to: '/settings/credentials', label: 'Credentials' },
  { to: '/settings/alerts', label: 'Alerts' },
  { to: '/settings/telegram', label: 'Telegram' },
  { to: '/settings/models', label: 'Models' },
];

export function SettingsLayout() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Tab nav */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border)',
        backgroundColor: 'var(--bg-surface)',
        flexShrink: 0,
        padding: '0 20px',
      }}>
        {TABS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => ({
              padding: '12px 16px',
              fontSize: '12px',
              fontWeight: 600,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              color: isActive ? 'var(--accent)' : 'var(--text-muted)',
              textDecoration: 'none',
              borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              marginBottom: '-1px',
              transition: 'color 0.1s',
              whiteSpace: 'nowrap',
            })}
          >
            {label}
          </NavLink>
        ))}
      </div>

      {/* Page content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '20px' }}>
        <Outlet />
      </div>
    </div>
  );
}

import { NavLink, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/authStore';
import { useAlertStore } from '../../stores/alertStore';
import '../../styles/alerts.css';

const NAV_LINKS = [
  { to: '/dashboard', icon: '📊', label: 'Dashboard' },
  { to: '/feed', icon: '📰', label: 'Feed' },
  { to: '/map', icon: '🗺️', label: 'Map' },
  { to: '/entities', icon: '🔗', label: 'Entities' },
  { to: '/briefs', icon: '📋', label: 'Briefs' },
  { to: '/bookmarks', icon: '⭐', label: 'Bookmarks' },
  { to: '/settings/sources', icon: '⚙️', label: 'Settings' },
];

const ANALYSIS_LINKS = [
  { to: '/documents', icon: '📄', label: 'Documents' },
  { to: '/query', icon: '🧠', label: 'Ask AI' },
];

const FINANCE_LINKS = [
  { to: '/finance/portfolio', icon: '📊', label: 'Portfolio' },
  { to: '/finance/markets', icon: '📈', label: 'Markets' },
  { to: '/finance/signals', icon: '🔔', label: 'Signals' },
];

interface SidebarProps {
  open?: boolean;
  onClose?: () => void;
}

export function Sidebar({ open = false, onClose }: SidebarProps) {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const unacknowledgedCount = useAlertStore((s) => s.unacknowledgedCount);

  const handleLogout = async () => {
    onClose?.();
    await logout();
    navigate('/login');
  };

  const handleNavClick = () => {
    onClose?.();
  };

  return (
    <aside className={`app-sidebar${open ? ' app-sidebar--open' : ''}`}>
      {/* Logo */}
      <div style={{
        padding: '18px 16px 14px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <span style={{
          fontSize: '12px',
          fontWeight: 700,
          letterSpacing: '0.2em',
          color: 'var(--accent)',
          textTransform: 'uppercase',
        }}>
          ▣ ORTHANC
        </span>
        {/* Mobile close button — only visible on mobile via CSS */}
        <button
          className="sidebar-close-btn"
          onClick={onClose}
          aria-label="Close navigation"
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            fontSize: '18px',
            cursor: 'pointer',
            padding: '4px',
            lineHeight: 1,
            display: 'none', // shown via media query in responsive.css
          }}
        >
          ✕
        </button>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: '8px 0', overflowY: 'auto' }}>
        {NAV_LINKS.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={handleNavClick}
            className="sidebar-nav-link"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              padding: '9px 16px',
              fontSize: '13px',
              fontWeight: 500,
              color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
              textDecoration: 'none',
              backgroundColor: isActive ? 'var(--bg-surface-hover)' : 'transparent',
              borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'background-color 0.1s, color 0.1s',
              minHeight: '44px',
            })}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              if (!el.getAttribute('aria-current')) {
                el.style.backgroundColor = 'var(--bg-surface-hover)';
                el.style.color = 'var(--text-primary)';
              }
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              if (!el.getAttribute('aria-current')) {
                el.style.backgroundColor = 'transparent';
                el.style.color = 'var(--text-secondary)';
              }
            }}
          >
            <span style={{ fontSize: '15px', lineHeight: 1 }}>{icon}</span>
            <span style={{ flex: 1 }}>{label}</span>
            {to === '/settings/sources' && unacknowledgedCount > 0 && (
              <span className="alert-bell-count" style={{ position: 'static', minWidth: '16px', height: '16px' }}>
                {unacknowledgedCount > 99 ? '99+' : unacknowledgedCount}
              </span>
            )}
          </NavLink>
        ))}

        {/* Analysis section */}
        <div style={{
          margin: '8px 16px 4px',
          paddingTop: '8px',
          borderTop: '1px solid var(--border)',
          fontSize: '10px',
          fontWeight: 700,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
        }}>
          Analysis
        </div>
        {ANALYSIS_LINKS.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={handleNavClick}
            className="sidebar-nav-link"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              padding: '9px 16px',
              fontSize: '13px',
              fontWeight: 500,
              color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
              textDecoration: 'none',
              backgroundColor: isActive ? 'var(--bg-surface-hover)' : 'transparent',
              borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'background-color 0.1s, color 0.1s',
              minHeight: '44px',
            })}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              if (!el.getAttribute('aria-current')) {
                el.style.backgroundColor = 'var(--bg-surface-hover)';
                el.style.color = 'var(--text-primary)';
              }
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              if (!el.getAttribute('aria-current')) {
                el.style.backgroundColor = 'transparent';
                el.style.color = 'var(--text-secondary)';
              }
            }}
          >
            <span style={{ fontSize: '15px', lineHeight: 1 }}>{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}

        {/* Finance section */}
        <div style={{
          margin: '8px 16px 4px',
          paddingTop: '8px',
          borderTop: '1px solid var(--border)',
          fontSize: '10px',
          fontWeight: 700,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
        }}>
          Finance
        </div>
        {FINANCE_LINKS.map(({ to, icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={handleNavClick}
            className="sidebar-nav-link"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              padding: '9px 16px',
              fontSize: '13px',
              fontWeight: 500,
              color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
              textDecoration: 'none',
              backgroundColor: isActive ? 'var(--bg-surface-hover)' : 'transparent',
              borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'background-color 0.1s, color 0.1s',
              minHeight: '44px',
            })}
            onMouseEnter={(e) => {
              const el = e.currentTarget;
              if (!el.getAttribute('aria-current')) {
                el.style.backgroundColor = 'var(--bg-surface-hover)';
                el.style.color = 'var(--text-primary)';
              }
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget;
              if (!el.getAttribute('aria-current')) {
                el.style.backgroundColor = 'transparent';
                el.style.color = 'var(--text-secondary)';
              }
            }}
          >
            <span style={{ fontSize: '15px', lineHeight: 1 }}>{icon}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* User info + logout */}
      <div style={{
        padding: '12px 16px',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}>
        <div style={{
          fontSize: '12px',
          color: 'var(--text-muted)',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}>
          <span style={{
            width: '20px', height: '20px',
            borderRadius: '50%',
            backgroundColor: 'var(--accent)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '10px',
            fontWeight: 700,
            color: '#fff',
            flexShrink: 0,
          }}>
            {user?.username?.[0]?.toUpperCase() ?? '?'}
          </span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {user?.username ?? 'Unknown'}
          </span>
        </div>
        <button
          className="btn btn-ghost"
          style={{ width: '100%', justifyContent: 'flex-start', fontSize: '12px' }}
          onClick={handleLogout}
        >
          ↪ Logout
        </button>
      </div>
    </aside>
  );
}

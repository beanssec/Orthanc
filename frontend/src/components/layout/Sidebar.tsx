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
  { to: '/cases', icon: '🕵️', label: 'Cases' },
  { to: '/documents', icon: '📄', label: 'Documents' },
  { to: '/narratives', icon: '📖', label: 'Narratives' },
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
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export function Sidebar({ open = false, onClose, collapsed = false, onToggleCollapse }: SidebarProps) {
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
    <aside className={`app-sidebar${open ? ' app-sidebar--open' : ''}${collapsed ? ' app-sidebar--collapsed' : ''}`}>
      {/* Logo + collapse toggle */}
      <div className="sidebar-header">
        {!collapsed && (
          <span className="sidebar-logo">▣ ORTHANC</span>
        )}
        {collapsed && (
          <span className="sidebar-logo sidebar-logo--icon">▣</span>
        )}
        <div className="sidebar-header__actions">
          {/* Mobile close button — only visible on mobile via CSS */}
          <button
            className="sidebar-close-btn"
            onClick={onClose}
            aria-label="Close navigation"
          >
            ✕
          </button>
          {/* Collapse toggle — desktop only */}
          <button
            className="sidebar-collapse-btn"
            onClick={onToggleCollapse}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? '»' : '«'}
          </button>
        </div>
      </div>

      {/* Nav */}
      <nav className="sidebar-nav">
        {NAV_LINKS.map(({ to, icon, label }) => (
          <NavLink key={to} to={to} onClick={handleNavClick} className={({ isActive }) => `sidebar-nav-link${isActive ? ' sidebar-nav-link--active' : ''}`} title={collapsed ? label : undefined}>
            <span className="sidebar-nav-link__icon">{icon}</span>
            {!collapsed && <span className="sidebar-nav-link__label">{label}</span>}
            {!collapsed && to === '/settings/sources' && unacknowledgedCount > 0 && (
              <span className="alert-bell-count" style={{ position: 'static', minWidth: '16px', height: '16px' }}>
                {unacknowledgedCount > 99 ? '99+' : unacknowledgedCount}
              </span>
            )}
          </NavLink>
        ))}

        {!collapsed && <div className="sidebar-section-label">Analysis</div>}
        {collapsed && <div className="sidebar-section-divider" />}
        {ANALYSIS_LINKS.map(({ to, icon, label }) => (
          <NavLink key={to} to={to} onClick={handleNavClick} className={({ isActive }) => `sidebar-nav-link${isActive ? ' sidebar-nav-link--active' : ''}`} title={collapsed ? label : undefined}>
            <span className="sidebar-nav-link__icon">{icon}</span>
            {!collapsed && <span className="sidebar-nav-link__label">{label}</span>}
          </NavLink>
        ))}

        {!collapsed && <div className="sidebar-section-label">Finance</div>}
        {collapsed && <div className="sidebar-section-divider" />}
        {FINANCE_LINKS.map(({ to, icon, label }) => (
          <NavLink key={to} to={to} onClick={handleNavClick} className={({ isActive }) => `sidebar-nav-link${isActive ? ' sidebar-nav-link--active' : ''}`} title={collapsed ? label : undefined}>
            <span className="sidebar-nav-link__icon">{icon}</span>
            {!collapsed && <span className="sidebar-nav-link__label">{label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* User info + logout */}
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <span className="sidebar-user__avatar">
            {user?.username?.[0]?.toUpperCase() ?? '?'}
          </span>
          {!collapsed && (
            <span className="sidebar-user__name">
              {user?.username ?? 'Unknown'}
            </span>
          )}
        </div>
        {!collapsed ? (
          <button className="btn btn-ghost sidebar-logout-btn" onClick={handleLogout}>
            ↪ Logout
          </button>
        ) : (
          <button className="btn btn-ghost sidebar-logout-btn sidebar-logout-btn--icon" onClick={handleLogout} title="Logout">
            ↪
          </button>
        )}
      </div>
    </aside>
  );
}

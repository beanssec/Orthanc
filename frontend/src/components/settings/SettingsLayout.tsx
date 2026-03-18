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
    <div className="settings-layout">
      {/* Tab nav */}
      <div className="settings-nav">
        {TABS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `settings-nav__link${isActive ? ' active' : ''}`
            }
          >
            {label}
          </NavLink>
        ))}
      </div>

      {/* Page content */}
      <div className="settings-content">
        <Outlet />
      </div>
    </div>
  );
}

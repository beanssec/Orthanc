import { useState } from 'react';
import { Link, Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { AlertToastContainer } from '../common/AlertToast';
import { GlobalSearch } from '../search/GlobalSearch';
import { useWebSocket } from '../../hooks/useWebSocket';
import { useAlertStore } from '../../stores/alertStore';
import { StatusDot } from '../common/StatusDot';
import '../../styles/alerts.css';
import '../../styles/search.css';

function GlobalTopBar() {
  const { connected, reconnecting } = useWebSocket();
  const unacknowledgedCount = useAlertStore((s) => s.unacknowledgedCount);
  const wsStatus = connected ? 'active' : reconnecting ? 'warning' : 'error';
  const wsLabel = connected ? 'Live' : reconnecting ? 'Reconnecting...' : 'Disconnected';

  return (
    <div className="app-shell__topbar">
      {/* Center: Global search */}
      <div style={{ flex: 1, display: 'flex', justifyContent: 'center', maxWidth: '600px' }}>
        <GlobalSearch />
      </div>

      {/* Right: WS status + alerts */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
        <Link to="/settings/alerts" className="alert-bell" title="Alert Rules" style={{ textDecoration: 'none' }}>
          🔔
          {unacknowledgedCount > 0 && (
            <span className="alert-bell-count">
              {unacknowledgedCount > 99 ? '99+' : unacknowledgedCount}
            </span>
          )}
        </Link>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-muted)' }}>
          <StatusDot status={wsStatus} />
          <span style={{ whiteSpace: 'nowrap' }}>{wsLabel}</span>
        </div>
      </div>
    </div>
  );
}

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="app-shell">
      {/* Global top bar with search — always visible */}
      <GlobalTopBar />

      {/* Mobile-only hamburger row */}
      <header className="app-shell__mobile-header">
        <button
          className="app-shell__hamburger"
          onClick={() => setSidebarOpen(true)}
          aria-label="Open navigation"
        >
          ☰
        </button>
        <span className="app-shell__mobile-title">▣ ORTHANC</span>
      </header>

      {/* Dim backdrop when sidebar is open on mobile */}
      <div
        className={`sidebar-backdrop${sidebarOpen ? ' sidebar-backdrop--visible' : ''}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <main className="app-shell__main">
        <Outlet />
      </main>

      <AlertToastContainer />
    </div>
  );
}

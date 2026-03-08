import { useEffect, useState } from 'react';
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { useAuthStore } from './stores/authStore';
import { AppShell } from './components/layout/AppShell';
import { LoginPage } from './components/auth/LoginPage';
import { RegisterPage } from './components/auth/RegisterPage';
import { SetupWizard } from './components/setup/SetupWizard';
import { SettingsLayout } from './components/settings/SettingsLayout';
import { SourcesPage } from './components/settings/SourcesPage';
import { CredentialsPage } from './components/settings/CredentialsPage';
import { AlertsPage } from './components/settings/AlertsPage';
import { TelegramSetup } from './components/settings/TelegramSetup';
import { ModelsView } from './components/settings/ModelsView';
import { FeedView } from './components/feed/FeedView';
import { MapView } from './components/map/MapView';
import { DashboardView } from './components/dashboard/DashboardView';
import { EntitiesView } from './components/entities/EntitiesView';
import { BriefsView } from './components/briefs/BriefsView';
import { DocumentsView } from './components/documents/DocumentsView';
import { PortfolioView } from './components/finance/PortfolioView';
import { MarketsView } from './components/finance/MarketsView';
import { SignalsView } from './components/finance/SignalsView';
import { SearchResults } from './components/search/SearchResults';
import { BookmarksView } from './components/bookmarks/BookmarksView';
import { QueryView } from './components/query/QueryView';
import { CasesView } from './components/cases/CasesView';
import { CaseDetail } from './components/cases/CaseDetail';
import { NarrativesView } from './components/narratives/NarrativesView';
import api from './services/api';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
}

/**
 * After login, check if user needs the setup wizard.
 * - If wizardDismissed is set in localStorage → go to dashboard
 * - If user has 0 sources (setup not complete) → go to /setup
 * - Otherwise → go to /dashboard
 */
function RootRedirect() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (!isAuthenticated) {
      setChecking(false);
      return;
    }

    const dismissed = localStorage.getItem('wizardDismissed');
    if (dismissed) {
      navigate('/dashboard', { replace: true });
      return;
    }

    // Check setup status
    api
      .get('/dashboard/setup-status')
      .then((res) => {
        const { setup_complete } = res.data as { setup_complete: boolean };
        if (setup_complete) {
          navigate('/dashboard', { replace: true });
        } else {
          navigate('/setup', { replace: true });
        }
      })
      .catch(() => {
        // On error, fall back to dashboard
        navigate('/dashboard', { replace: true });
      })
      .finally(() => setChecking(false));
  }, [isAuthenticated, navigate]);

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // Brief loading state while we check
  if (checking) {
    return (
      <div
        style={{
          minHeight: '100vh',
          backgroundColor: 'var(--bg-primary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-muted)',
          fontSize: '13px',
        }}
      >
        Loading…
      </div>
    );
  }

  return null;
}

export default function App() {
  return (
    <Routes>
      {/* Public routes */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      {/* Setup wizard — protected but outside AppShell */}
      <Route
        path="/setup"
        element={
          <ProtectedRoute>
            <SetupWizard />
          </ProtectedRoute>
        }
      />

      {/* Protected routes */}
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<RootRedirect />} />
        <Route path="dashboard" element={<DashboardView />} />
        <Route path="feed" element={<FeedView />} />
        <Route path="map" element={<MapView />} />
        <Route path="entities" element={<EntitiesView />} />
        <Route path="entities/:id" element={<EntitiesView />} />
        <Route path="briefs" element={<BriefsView />} />
        <Route path="documents" element={<DocumentsView />} />
        <Route path="search" element={<SearchResults />} />
        <Route path="bookmarks" element={<BookmarksView />} />
        <Route path="query" element={<QueryView />} />
        <Route path="cases" element={<CasesView />} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="narratives" element={<NarrativesView />} />
        <Route path="finance/portfolio" element={<PortfolioView />} />
        <Route path="finance/markets" element={<MarketsView />} />
        <Route path="finance/signals" element={<SignalsView />} />
        <Route path="settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="/settings/sources" replace />} />
          <Route path="sources" element={<SourcesPage />} />
          <Route path="credentials" element={<CredentialsPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="telegram" element={<TelegramSetup />} />
          <Route path="models" element={<ModelsView />} />
        </Route>
      </Route>

      {/* Fallback */}
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  );
}

import { useEffect, useState, useCallback } from 'react';
import api from '../../services/api';
import { Narrative } from './types';
import { NarrativeCard } from './NarrativeCard';
import { NarrativeDetail } from './NarrativeDetail';
import { BiasCompass } from './BiasCompass';
import '../../styles/narratives.css';

export function NarrativesView() {
  const [narratives, setNarratives] = useState<Narrative[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('active');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCompass, setShowCompass] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const fetchNarratives = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number> = {
        limit: 50,
        offset: 0,
      };
      if (statusFilter !== 'all') {
        params.status = statusFilter;
      }
      const res = await api.get('/narratives/', { params });
      const data = res.data;
      // Support both {items, total} and plain array
      if (Array.isArray(data)) {
        setNarratives(data);
        setTotal(data.length);
      } else {
        setNarratives(data.items ?? []);
        setTotal(data.total ?? 0);
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load narratives';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchNarratives();
  }, [fetchNarratives]);

  const handleRefresh = () => {
    setRefreshKey((k) => k + 1);
  };

  return (
    <div className="narratives-page">
      {/* Header */}
      <div className="narratives-header">
        <h2>📖 Narrative Intelligence</h2>
        <div className="narratives-filters">
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setSelectedId(null);
            }}
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="stale">Stale</option>
            <option value="resolved">Resolved</option>
          </select>

          <button onClick={() => setShowCompass((v) => !v)}>
            {showCompass ? 'Hide Compass' : '🧭 Bias Compass'}
          </button>

          <button onClick={handleRefresh} title="Refresh narratives">
            ↻ Refresh
          </button>

          {total > 0 && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
              {total} total
            </span>
          )}
        </div>
      </div>

      {/* Main content */}
      <div className="narratives-content">
        {/* Left: narrative list */}
        <div className="narratives-list">
          {loading && (
            <div className="narratives-loading">Loading narratives…</div>
          )}
          {error && (
            <div className="narratives-error">{error}</div>
          )}
          {!loading && !error && narratives.length === 0 && (
            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              No narratives found.
              <br />
              <span style={{ fontSize: '0.75rem' }}>Narratives are generated as sources ingest conflicting reports.</span>
            </div>
          )}
          {narratives.map((n) => (
            <NarrativeCard
              key={n.id}
              narrative={n}
              selected={n.id === selectedId}
              onClick={() => setSelectedId(n.id === selectedId ? null : n.id)}
            />
          ))}
        </div>

        {/* Right: detail panel */}
        <div className="narrative-detail">
          {selectedId ? (
            <NarrativeDetail narrativeId={selectedId} />
          ) : (
            <div className="narrative-detail-empty">
              Select a narrative to view details
            </div>
          )}
        </div>
      </div>

      {/* Bottom: collapsible bias compass */}
      {showCompass && (
        <div className="bias-compass-container">
          <div className="bias-compass-titlebar">
            <h3 className="bias-compass-title">🧭 Source Bias Compass</h3>
            <button
              className="bias-compass-toggle"
              onClick={() => setShowCompass(false)}
            >
              ✕ Close
            </button>
          </div>
          <BiasCompass />
        </div>
      )}
    </div>
  );
}

export default NarrativesView;

import { useEffect, useState, useCallback } from 'react';
import api from '../../services/api';
import { Narrative, NarrativeTracker, NarrativeTrackerMonthlyPoint } from './types';
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

  const [trackersEnabled, setTrackersEnabled] = useState(true);
  const [trackers, setTrackers] = useState<NarrativeTracker[]>([]);
  const [selectedTrackerId, setSelectedTrackerId] = useState<string | null>(null);
  const [trackerTimeline, setTrackerTimeline] = useState<NarrativeTrackerMonthlyPoint[]>([]);
  const [trackerError, setTrackerError] = useState<string | null>(null);
  const [creatingTracker, setCreatingTracker] = useState(false);
  const [trackerName, setTrackerName] = useState('');
  const [trackerKeywords, setTrackerKeywords] = useState('');

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

  const fetchTrackers = useCallback(async () => {
    try {
      setTrackerError(null);
      const res = await api.get('/narratives/trackers');
      const rows = res.data?.trackers ?? [];
      setTrackers(rows);
      if (!selectedTrackerId && rows.length > 0) {
        setSelectedTrackerId(rows[0].id);
      }
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number; data?: { detail?: string } } })?.response?.status;
      if (status === 404) {
        setTrackersEnabled(false);
        return;
      }
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load trackers';
      setTrackerError(msg);
    }
  }, [selectedTrackerId]);

  const fetchTrackerTimeline = useCallback(async (trackerId: string) => {
    try {
      const res = await api.get(`/narratives/trackers/${trackerId}/monthly`, { params: { months: 12 } });
      setTrackerTimeline(res.data?.timeline ?? []);
    } catch {
      setTrackerTimeline([]);
    }
  }, []);

  useEffect(() => {
    fetchNarratives();
  }, [fetchNarratives]);

  useEffect(() => {
    fetchTrackers();
  }, [fetchTrackers, refreshKey]);

  useEffect(() => {
    if (selectedTrackerId) {
      fetchTrackerTimeline(selectedTrackerId);
    } else {
      setTrackerTimeline([]);
    }
  }, [selectedTrackerId, fetchTrackerTimeline]);

  const handleRefresh = () => {
    setRefreshKey((k) => k + 1);
  };

  const handleCreateTracker = async () => {
    if (!trackerName.trim()) return;
    setCreatingTracker(true);
    try {
      await api.post('/narratives/trackers', {
        name: trackerName.trim(),
        criteria: {
          keywords: trackerKeywords.split(',').map((x) => x.trim()).filter(Boolean),
          min_divergence: 0,
          min_evidence: 0,
        },
      });
      setTrackerName('');
      setTrackerKeywords('');
      await fetchTrackers();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create tracker';
      setTrackerError(msg);
    } finally {
      setCreatingTracker(false);
    }
  };

  const handleRecomputeTracker = async (trackerId: string) => {
    try {
      await api.post(`/narratives/trackers/${trackerId}/recompute`);
      await fetchTrackers();
      await fetchTrackerTimeline(trackerId);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to recompute tracker';
      setTrackerError(msg);
    }
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

      {trackersEnabled && (
        <div className="models-card" style={{ marginBottom: '0.75rem', padding: '0.75rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <strong style={{ fontSize: '0.8rem' }}>Story Trackers (operator-defined)</strong>
            {selectedTrackerId && (
              <button onClick={() => handleRecomputeTracker(selectedTrackerId)} style={{ fontSize: '0.75rem' }}>
                Recompute
              </button>
            )}
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
            <input
              className="input"
              placeholder="Tracker name (e.g. Iran nuclear build-up)"
              value={trackerName}
              onChange={(e) => setTrackerName(e.target.value)}
              style={{ minWidth: 260 }}
            />
            <input
              className="input"
              placeholder="keywords comma-separated"
              value={trackerKeywords}
              onChange={(e) => setTrackerKeywords(e.target.value)}
              style={{ minWidth: 260 }}
            />
            <button onClick={handleCreateTracker} disabled={creatingTracker || !trackerName.trim()}>
              {creatingTracker ? 'Creating…' : 'Add Tracker'}
            </button>
          </div>

          {trackerError && <div className="narratives-error" style={{ marginBottom: '0.5rem' }}>{trackerError}</div>}

          {trackers.length > 0 ? (
            <>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                {trackers.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setSelectedTrackerId(t.id)}
                    style={{
                      fontSize: '0.72rem',
                      border: selectedTrackerId === t.id ? '1px solid var(--accent-primary)' : '1px solid var(--border-primary)',
                      background: 'transparent',
                    }}
                  >
                    {t.name} · v{t.version}
                  </button>
                ))}
              </div>
              {trackerTimeline.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: '0.4rem' }}>
                  {trackerTimeline.map((row) => (
                    <div key={row.month} style={{ border: '1px solid var(--border-primary)', borderRadius: 6, padding: '0.4rem' }}>
                      <div style={{ fontSize: '0.68rem', color: 'var(--text-secondary)' }}>
                        {new Date(row.month).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })}
                      </div>
                      <div style={{ fontSize: '0.8rem', fontWeight: 600 }}>{row.matched_narratives} narratives</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{row.total_posts} posts</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              No trackers yet.
            </div>
          )}
        </div>
      )}

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

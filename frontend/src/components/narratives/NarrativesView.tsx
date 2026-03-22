import { useEffect, useState, useCallback } from 'react';
import api from '../../services/api';
import type { Narrative, NarrativeTracker, NarrativeTrackerMonthlyPoint } from './types';
import { NarrativeCard } from './NarrativeCard';
import { NarrativeDetail } from './NarrativeDetail';
import { BiasCompass } from './BiasCompass';
import { Skeleton } from '../common/Skeleton';
import '../../styles/narratives.css';

export function NarrativesView() {
  const [narratives, setNarratives] = useState<Narrative[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('active');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [triageFilter, setTriageFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<string>('last_updated');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCompass, setShowCompass] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [relabelling, setRelabelling] = useState(false);
  const [relabelStatus, setRelabelStatus] = useState<string | null>(null);

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

  const handleRelabel = async () => {
    setRelabelling(true);
    setRelabelStatus(null);
    try {
      const res = await api.post('/narratives/relabel?limit=200');
      const data = res.data;
      const relabelled = data.relabelled ?? data.updated ?? 0;
      const failed = data.failed ?? data.errors ?? 0;
      setRelabelStatus(`Relabelled ${relabelled}, failed ${failed}`);
      setRefreshKey((k) => k + 1);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Re-label failed';
      setRelabelStatus(`Error: ${msg}`);
    } finally {
      setRelabelling(false);
    }
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

  // Client-side filter + sort
  const displayedNarratives = (() => {
    let list = narratives;
    if (typeFilter !== 'all') {
      list = list.filter((n) => n.narrative_type === typeFilter);
    }
    if (triageFilter !== 'all') {
      if (triageFilter === 'none') {
        list = list.filter((n) => !n.triage_status);
      } else {
        list = list.filter((n) => n.triage_status === triageFilter);
      }
    }
    const sorted = [...list];
    switch (sortBy) {
      case 'post_count':
        sorted.sort((a, b) => b.post_count - a.post_count);
        break;
      case 'divergence':
        sorted.sort((a, b) => b.divergence_score - a.divergence_score);
        break;
      case 'confidence':
        sorted.sort((a, b) => (b.label_confidence ?? 0) - (a.label_confidence ?? 0));
        break;
      case 'source_count':
        sorted.sort((a, b) => b.source_count - a.source_count);
        break;
      default: // last_updated
        sorted.sort((a, b) => new Date(b.last_updated).getTime() - new Date(a.last_updated).getTime());
    }
    return sorted;
  })();

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

          <select
            value={typeFilter}
            onChange={(e) => {
              setTypeFilter(e.target.value);
              setSelectedId(null);
            }}
          >
            <option value="all">All Types</option>
            <option value="state_action">State Action</option>
            <option value="military">Military</option>
            <option value="diplomatic">Diplomatic</option>
            <option value="economic">Economic</option>
            <option value="humanitarian">Humanitarian</option>
            <option value="cyber">Cyber</option>
            <option value="other">Other</option>
          </select>

          <select
            value={triageFilter}
            onChange={(e) => {
              setTriageFilter(e.target.value);
              setSelectedId(null);
            }}
          >
            <option value="all">All Triage</option>
            <option value="none">Not Triaged</option>
            <option value="detected">Detected</option>
            <option value="under_review">Under Review</option>
            <option value="confirmed">Confirmed</option>
            <option value="contradicted">Contradicted</option>
            <option value="archived">Archived</option>
          </select>

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
          >
            <option value="last_updated">Last Updated</option>
            <option value="post_count">Post Count ↓</option>
            <option value="divergence">Divergence ↓</option>
            <option value="confidence">Confidence ↓</option>
            <option value="source_count">Source Count ↓</option>
          </select>

          <button onClick={() => setShowCompass((v) => !v)}>
            {showCompass ? 'Hide Compass' : '🧭 Bias Compass'}
          </button>

          <button onClick={handleRefresh} title="Refresh narratives">
            ↻ Refresh
          </button>

          <button className="btn btn-secondary" onClick={handleRelabel} disabled={relabelling} title="Re-label up to 20 narratives using AI">
            {relabelling ? <><span className="spinner spinner-sm" /> Re-labelling…</> : '🔄 Re-label'}
          </button>

          {relabelStatus && (
            <span className="narratives-relabel-status" title={relabelStatus}>
              {relabelStatus}
            </span>
          )}

          {total > 0 && (
            <span className="narratives-total-count">
              {total} total
            </span>
          )}
        </div>
      </div>

      {trackersEnabled && (
        <div className="models-card narratives-trackers">
          <div className="narratives-trackers__header">
            <strong className="narratives-trackers__title">Story Trackers (operator-defined)</strong>
            {selectedTrackerId && (
              <button className="narratives-trackers__recompute" onClick={() => handleRecomputeTracker(selectedTrackerId)}>
                Recompute
              </button>
            )}
          </div>

          <div className="narratives-trackers__form">
            <input
              className="input narratives-trackers__input"
              placeholder="Tracker name (e.g. Iran nuclear build-up)"
              value={trackerName}
              onChange={(e) => setTrackerName(e.target.value)}
            />
            <input
              className="input narratives-trackers__input"
              placeholder="keywords comma-separated"
              value={trackerKeywords}
              onChange={(e) => setTrackerKeywords(e.target.value)}
            />
            <button onClick={handleCreateTracker} disabled={creatingTracker || !trackerName.trim()}>
              {creatingTracker ? 'Creating…' : 'Add Tracker'}
            </button>
          </div>

          {trackerError && <div className="narratives-error narratives-trackers__error">{trackerError}</div>}

          {trackers.length > 0 ? (
            <>
              <div className="narratives-trackers__list">
                {trackers.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setSelectedTrackerId(t.id)}
                    className={selectedTrackerId === t.id ? 'narratives-trackers__pill narratives-trackers__pill--active' : 'narratives-trackers__pill'}
                  >
                    {t.name} · v{t.version}
                  </button>
                ))}
              </div>
              {trackerTimeline.length > 0 && (
                <div className="narratives-trackers__timeline">
                  {trackerTimeline.map((row) => (
                    <div key={row.month} className="narratives-trackers__month">
                      <div className="narratives-trackers__month-label">
                        {new Date(row.month).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })}
                      </div>
                      <div className="narratives-trackers__month-value">{row.matched_narratives} narratives</div>
                      <div className="narratives-trackers__month-subvalue">{row.total_posts} posts</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="narratives-trackers__empty">
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
            <div className="narratives-loading">
              <Skeleton rows={4} type="card" />
            </div>
          )}
          {error && (
            <div className="narratives-error">{error}</div>
          )}
          {!loading && !error && displayedNarratives.length === 0 && (
            <div className="narratives-empty">
              {narratives.length > 0 ? 'No narratives match the current filters.' : 'No narratives found.'}
              <br />
              <span style={{ fontSize: '0.75rem' }}>Narratives are generated as sources ingest conflicting reports.</span>
            </div>
          )}
          {displayedNarratives.map((n) => (
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

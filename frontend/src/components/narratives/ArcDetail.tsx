import { useEffect, useState } from 'react';
import api from '../../services/api';
import type { ArcDetail as ArcDetailType } from './types';
import { timeAgo } from './utils';

interface ArcDetailProps {
  arcId: string;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function formatDateFull(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function ArcDetail({ arcId }: ArcDetailProps) {
  const [arc, setArc] = useState<ArcDetailType | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'overview' | 'timeline' | 'report'>('overview');
  const [report, setReport] = useState<any>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    if (!arcId) return;
    setLoading(true);
    setError(null);
    setArc(null);

    api.get(`/narratives/arcs/${arcId}`)
      .then((res) => setArc(res.data))
      .catch((err: unknown) => {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load arc';
        setError(msg);
      })
      .finally(() => setLoading(false));
  }, [arcId]);

  if (loading) {
    return <div className="narrative-detail-empty">Loading arc…</div>;
  }
  if (error) {
    return <div className="narratives-error">{error}</div>;
  }
  if (!arc) {
    return <div className="narrative-detail-empty">No arc selected</div>;
  }

  return (
    <div className="narrative-detail-content">
      {/* Header */}
      <div className="narrative-detail-header">
        <h3>{arc.title}</h3>
        <span className={`narrative-status-badge status-${arc.status}`}>{arc.status}</span>
      </div>

      {/* Tabs */}
      <div className="narrative-detail-tabs">
        <button
          className={tab === 'overview' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('overview')}
        >
          Overview
        </button>
        <button
          className={tab === 'timeline' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('timeline')}
        >
          Timeline
        </button>
        <button
          className={tab === 'report' ? 'tab-btn active' : 'tab-btn'}
          onClick={() => setTab('report')}
        >
          Report
        </button>
      </div>

      {tab === 'overview' && (
        <div className="arc-overview">
          {arc.summary ? (
            <div className="arc-detail-summary">{arc.summary}</div>
          ) : (
            <div className="arc-detail-summary" style={{ color: 'var(--text-muted, #666)', fontStyle: 'italic' }}>
              No summary available.
            </div>
          )}

          <div className="arc-detail-stats">
            <span>📰 {arc.narrative_count} narratives</span>
            <span>📝 {arc.total_post_count} posts</span>
            <span>📅 {formatDateFull(arc.first_seen)} → {formatDateFull(arc.last_updated)}</span>
            {arc.arc_type && (
              <span className="narrative-type-pill">{arc.arc_type.replace(/_/g, ' ')}</span>
            )}
          </div>

          {arc.summary_history.length > 0 && (
            <div style={{ marginTop: '1rem' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #666)', marginBottom: '0.5rem' }}>
                Summary History ({arc.summary_history.length})
              </div>
              {arc.summary_history.slice(0, 3).map((s, i) => (
                <div key={i} style={{ marginBottom: '0.75rem' }}>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted, #666)', marginBottom: '0.2rem' }}>
                    {timeAgo(s.generated_at)} · {s.narrative_count} narratives · {s.post_count} posts
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #888)', lineHeight: 1.4 }}>
                    {s.summary}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'timeline' && (
        <div className="arc-timeline">
          {arc.narratives.length === 0 ? (
            <div style={{ color: 'var(--text-muted, #666)', fontSize: '0.85rem' }}>
              No narratives in this arc yet.
            </div>
          ) : (
            arc.narratives.map((n) => (
              <div key={n.id} className="arc-timeline-entry">
                <div className="arc-timeline-date">{formatDate(n.first_seen)}</div>
                <div className="arc-timeline-title">{n.canonical_title ?? n.title}</div>
                {n.canonical_claim && (
                  <div className="arc-timeline-claim">{n.canonical_claim}</div>
                )}
                <div className="arc-timeline-meta">
                  <span>{n.post_count} posts</span>
                  {n.confirmation_status && <span>{n.confirmation_status}</span>}
                  {n.narrative_type && <span>{n.narrative_type.replace(/_/g, ' ')}</span>}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {tab === 'report' && (
        <div className="arc-report">
          {!report && !reportLoading && (
            <div style={{ textAlign: 'center', padding: '2rem 0' }}>
              <p style={{ color: 'var(--text-secondary, #888)', fontSize: '0.9rem', marginBottom: '1rem' }}>
                Generate a deep-dive analytical report on how this arc evolved over time.
              </p>
              <button
                className="generate-report-btn"
                onClick={() => {
                  setReportLoading(true);
                  setReportError(null);
                  api.post(`/narratives/arcs/${arcId}/report`)
                    .then((res) => setReport(res.data))
                    .catch((err: unknown) => {
                      const msg = (err as { response?: { data?: { detail?: string; error?: string } } })?.response?.data?.detail
                        ?? (err as { response?: { data?: { error?: string } } })?.response?.data?.error
                        ?? 'Failed to generate report';
                      setReportError(msg);
                    })
                    .finally(() => setReportLoading(false));
                }}
              >
                Generate Report
              </button>
              {reportError && (
                <p style={{ color: '#ef4444', fontSize: '0.85rem', marginTop: '0.75rem' }}>{reportError}</p>
              )}
            </div>
          )}

          {reportLoading && (
            <div style={{ textAlign: 'center', padding: '2rem 0', color: 'var(--text-secondary, #888)' }}>
              <div style={{ marginBottom: '0.5rem' }}>Generating report…</div>
              <div style={{ fontSize: '0.8rem' }}>This may take up to 2 minutes for large arcs.</div>
            </div>
          )}

          {report && !reportLoading && (
            <div>
              {report.error ? (
                <p style={{ color: '#ef4444', fontSize: '0.85rem' }}>{report.error}</p>
              ) : report.raw_report ? (
                <div className="arc-report-section">
                  <p style={{ whiteSpace: 'pre-wrap' }}>{report.raw_report}</p>
                </div>
              ) : (
                <>
                  {report.title && <h2>{report.title}</h2>}

                  {report.origin && (
                    <div className="arc-report-section">
                      <h3>Origin</h3>
                      <p>{report.origin}</p>
                    </div>
                  )}

                  {report.key_events && report.key_events.length > 0 && (
                    <div className="arc-report-section">
                      <h3>Key Events</h3>
                      {report.key_events.map((ev: any, i: number) => (
                        <div key={i} className="arc-report-event">
                          <div className="arc-report-event-date">{ev.date}</div>
                          <div>
                            <div className="arc-report-event-text">{ev.event}</div>
                            {ev.significance && (
                              <div className="arc-report-event-sig">{ev.significance}</div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {report.turning_points && report.turning_points.length > 0 && (
                    <div className="arc-report-section">
                      <h3>Turning Points</h3>
                      {report.turning_points.map((tp: any, i: number) => (
                        <div key={i} className="arc-report-turning-point">
                          <div className="arc-report-turning-point-shift">{tp.date} — {tp.shift}</div>
                          {(tp.from || tp.to) && (
                            <div className="arc-report-turning-point-detail">
                              {tp.from && <span>From: {tp.from}</span>}
                              {tp.from && tp.to && <span> → </span>}
                              {tp.to && <span>{tp.to}</span>}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {report.source_analysis && (
                    <div className="arc-report-section">
                      <h3>Source Analysis</h3>
                      <p>{report.source_analysis}</p>
                    </div>
                  )}

                  {report.current_status && (
                    <div className="arc-report-section">
                      <h3>Current Status</h3>
                      <p>{report.current_status}</p>
                    </div>
                  )}

                  {report.trajectory && (
                    <div className="arc-report-section">
                      <h3>Trajectory</h3>
                      <p>{report.trajectory}</p>
                    </div>
                  )}

                  {report.confidence_assessment && (
                    <div className="arc-report-section">
                      <div className="arc-report-confidence">{report.confidence_assessment}</div>
                    </div>
                  )}

                  <div style={{ marginTop: '1rem', display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                    <button
                      className="generate-report-btn"
                      onClick={() => {
                        setReport(null);
                        setReportError(null);
                      }}
                      style={{ background: 'var(--bg-secondary, #1a1a2e)', border: '1px solid var(--border-color, #333)' }}
                    >
                      Regenerate
                    </button>
                    {report.model && (
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted, #666)' }}>
                        Generated by {report.model}
                      </span>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ArcDetail;

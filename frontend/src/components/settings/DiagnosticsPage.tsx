import { useState, useEffect, useCallback } from 'react';
import api from '../../services/api';

/* ── Types ───────────────────────────────────────────────── */

interface CollectorStatus {
  [collectorType: string]: string;
}

interface SourceHealth {
  type: string;
  handle: string;
  last_polled: string | null;
  error_count: number;
  last_error: string | null;
  enabled: boolean;
}

interface TaskModel {
  task: string;
  model_id: string;
  updated_at: string;
}

interface LLMCall {
  timestamp: string;
  provider: string;
  model: string;
  task: string;
  tokens_in: number;
  tokens_out: number;
  latency_ms: number | null;
  cost_usd: number | null;
  error: string | null;
}

interface ByTask {
  task: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number | null;
}

interface ByModel {
  model: string;
  provider: string;
  calls: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number | null;
}

interface UsageSummary {
  period_hours: number;
  since: string;
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number | null;
  avg_latency_ms: number | null;
  by_task: ByTask[];
  by_model: ByModel[];
}

interface DiagnosticsData {
  collector_status: CollectorStatus;
  source_health: SourceHealth[];
  task_models: TaskModel[];
  llm_usage_summary: UsageSummary;
  recent_llm_calls: LLMCall[];
}

/* ── Helpers ─────────────────────────────────────────────── */

function relativeTime(isoString: string | null): string {
  if (!isoString) return '—';
  const diff = Date.now() - new Date(isoString).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatCost(usd: number | null): string {
  if (usd === null || usd === undefined) return '—';
  if (usd < 0.001) return '<$0.001';
  return `$${usd.toFixed(4)}`;
}

function fmt(n: number): string {
  return n.toLocaleString('en-US');
}

function truncate(s: string | null, len = 80): string {
  if (!s) return '—';
  return s.length > len ? s.slice(0, len) + '…' : s;
}

const TIME_OPTIONS = [
  { label: '1h', value: 1 },
  { label: '6h', value: 6 },
  { label: '24h', value: 24 },
  { label: '48h', value: 48 },
  { label: '7d', value: 168 },
];

/* ── Section wrapper ─────────────────────────────────────── */

function Section({
  title,
  children,
  defaultOpen = true,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div style={styles.section}>
      <button style={styles.sectionHeader} onClick={() => setOpen((o) => !o)}>
        <span>{open ? '▾' : '▸'}</span>
        <span style={{ marginLeft: 8 }}>{title}</span>
      </button>
      {open && <div style={styles.sectionBody}>{children}</div>}
    </div>
  );
}

/* ── Main page ───────────────────────────────────────────── */

export function DiagnosticsPage() {
  const [data, setData] = useState<DiagnosticsData | null>(null);
  const [hours, setHours] = useState(24);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAllSources, setShowAllSources] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get(`/sources/diagnostics?hours=${hours}`);
      setData(res.data as DiagnosticsData);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load diagnostics');
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.header}>
        <h2 style={styles.title}>🔧 System Diagnostics</h2>
        <div style={styles.controls}>
          <div style={styles.timeSelector}>
            {TIME_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                style={{
                  ...styles.timeBtn,
                  ...(hours === opt.value ? styles.timeBtnActive : {}),
                }}
                onClick={() => setHours(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button style={styles.refreshBtn} onClick={load} disabled={loading}>
            {loading ? '↻ Loading…' : '↻ Refresh'}
          </button>
        </div>
      </div>

      {error && <div style={styles.errorBanner}>{error}</div>}

      {!data && !loading && !error && (
        <div style={styles.empty}>No data available.</div>
      )}

      {data && (
        <>
          {/* ── Collector Status ─────────────────────────────── */}
          <Section title="Collector Status">
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Collector</th>
                  <th style={styles.th}>Status</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.collector_status ?? {}).map(([type, status]) => (
                  <tr key={type} style={styles.tr}>
                    <td style={styles.td}>{type}</td>
                    <td style={styles.td}>
                      <span
                        style={{
                          ...styles.dot,
                          backgroundColor:
                            status === 'active' ? '#22c55e' : '#ef4444',
                        }}
                      />
                      {typeof status === 'string' ? status : JSON.stringify(status)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          {/* ── Source Health ─────────────────────────────────── */}
          <Section title={`Source Health (${(data.source_health ?? []).length} enabled)`}>
            {(data.source_health ?? []).length === 0 ? (
              <div style={styles.empty}>No enabled sources.</div>
            ) : (
              <>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Type</th>
                      <th style={styles.th}>Handle</th>
                      <th style={styles.th}>Last Polled</th>
                      <th style={styles.th}>Errors</th>
                      <th style={styles.th}>Last Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(showAllSources
                      ? data.source_health
                      : (data.source_health ?? []).filter((s) => s.error_count > 0)
                    ).map((s, i) => (
                      <tr key={i} style={styles.tr}>
                        <td style={styles.td}>{s.type}</td>
                        <td style={{ ...styles.td, fontFamily: 'monospace', fontSize: 12 }}>
                          {s.handle}
                        </td>
                        <td style={{ ...styles.td, color: 'var(--text-muted)' }}>
                          {relativeTime(s.last_polled)}
                        </td>
                        <td
                          style={{
                            ...styles.td,
                            color: s.error_count > 0 ? '#ef4444' : 'inherit',
                            fontWeight: s.error_count > 0 ? 600 : 400,
                          }}
                        >
                          {s.error_count}
                        </td>
                        <td
                          style={{
                            ...styles.td,
                            color: s.last_error ? '#ef4444' : 'var(--text-muted)',
                            fontSize: 12,
                            maxWidth: 300,
                          }}
                        >
                          {truncate(s.last_error)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <button
                  style={styles.showAllBtn}
                  onClick={() => setShowAllSources((v) => !v)}
                >
                  {showAllSources
                    ? 'Show errors only'
                    : `Show all ${(data.source_health ?? []).length} sources`}
                </button>
              </>
            )}
          </Section>

          {/* ── Task Model Configuration ──────────────────────── */}
          <Section title="Task Model Configuration" defaultOpen={false}>
            {data.task_models.length === 0 ? (
              <div style={styles.empty}>No custom model assignments (using defaults).</div>
            ) : (
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Task</th>
                    <th style={styles.th}>Model</th>
                    <th style={styles.th}>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.task_models ?? []).map((o, i) => (
                    <tr key={i} style={styles.tr}>
                      <td style={styles.td}>{o.task}</td>
                      <td style={{ ...styles.td, fontFamily: 'monospace', fontSize: 12 }}>
                        {o.model_id}
                      </td>
                      <td style={{ ...styles.td, color: 'var(--text-muted)' }}>
                        {relativeTime(o.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>

          {/* ── LLM Usage Summary ─────────────────────────────── */}
          <Section title={`LLM Usage Summary (last ${hours}h)`}>
            <div style={styles.statsGrid}>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Total Calls</div>
                <div style={styles.statValue}>
                  {fmt((data.llm_usage_summary?.total_calls ?? 0))}
                </div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Tokens In</div>
                <div style={styles.statValue}>
                  {fmt((data.llm_usage_summary?.total_tokens_in ?? 0))}
                </div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Tokens Out</div>
                <div style={styles.statValue}>
                  {fmt((data.llm_usage_summary?.total_tokens_out ?? 0))}
                </div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Total Cost</div>
                <div style={styles.statValue}>
                  {formatCost((data.llm_usage_summary?.total_cost_usd ?? 0))}
                </div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Avg Latency</div>
                <div style={styles.statValue}>
                  {(data.llm_usage_summary?.avg_latency_ms ?? 0) != null
                    ? `${Math.round((data.llm_usage_summary?.avg_latency_ms ?? 0))}ms`
                    : '—'}
                </div>
              </div>
            </div>

            {(data.llm_usage_summary?.by_task ?? []).length > 0 && (
              <>
                <div style={styles.subHeading}>By Task</div>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Task</th>
                      <th style={styles.th}>Calls</th>
                      <th style={styles.th}>Tokens In</th>
                      <th style={styles.th}>Tokens Out</th>
                      <th style={styles.th}>Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.llm_usage_summary?.by_task ?? []).map((row, i) => (
                      <tr key={i} style={styles.tr}>
                        <td style={styles.td}>{row.task}</td>
                        <td style={styles.td}>{fmt(row.calls)}</td>
                        <td style={styles.td}>{fmt(row.tokens_in)}</td>
                        <td style={styles.td}>{fmt(row.tokens_out)}</td>
                        <td style={styles.td}>{formatCost(row.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            {(data.llm_usage_summary?.by_model ?? []).length > 0 && (
              <>
                <div style={styles.subHeading}>By Model</div>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Model</th>
                      <th style={styles.th}>Provider</th>
                      <th style={styles.th}>Calls</th>
                      <th style={styles.th}>Tokens In</th>
                      <th style={styles.th}>Tokens Out</th>
                      <th style={styles.th}>Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.llm_usage_summary?.by_model ?? []).map((row, i) => (
                      <tr key={i} style={styles.tr}>
                        <td style={{ ...styles.td, fontFamily: 'monospace', fontSize: 12 }}>
                          {row.model}
                        </td>
                        <td style={styles.td}>{row.provider}</td>
                        <td style={styles.td}>{fmt(row.calls)}</td>
                        <td style={styles.td}>{fmt(row.tokens_in)}</td>
                        <td style={styles.td}>{fmt(row.tokens_out)}</td>
                        <td style={styles.td}>{formatCost(row.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}

            {(data.llm_usage_summary?.total_calls ?? 0) === 0 && (
              <div style={styles.empty}>No LLM calls in the selected period.</div>
            )}
          </Section>

          {/* ── Recent LLM Calls ──────────────────────────────── */}
          <Section
            title={`Recent LLM Calls (${(data.recent_llm_calls ?? []).length})`}
            defaultOpen={false}
          >
            {(data.recent_llm_calls ?? []).length === 0 ? (
              <div style={styles.empty}>No LLM calls in the selected period.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ ...styles.table, minWidth: 900 }}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Time</th>
                      <th style={styles.th}>Provider</th>
                      <th style={styles.th}>Model</th>
                      <th style={styles.th}>Task</th>
                      <th style={styles.th}>In</th>
                      <th style={styles.th}>Out</th>
                      <th style={styles.th}>Latency</th>
                      <th style={styles.th}>Cost</th>
                      <th style={styles.th}>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data.recent_llm_calls ?? []).map((r, i) => (
                      <tr
                        key={i}
                        style={{
                          ...styles.tr,
                          backgroundColor: r.error
                            ? 'rgba(239,68,68,0.08)'
                            : undefined,
                        }}
                      >
                        <td style={{ ...styles.td, color: 'var(--text-muted)', fontSize: 11 }}>
                          {relativeTime(r.timestamp)}
                        </td>
                        <td style={styles.td}>{r.provider}</td>
                        <td style={{ ...styles.td, fontFamily: 'monospace', fontSize: 11 }}>
                          {truncate(r.model, 40)}
                        </td>
                        <td style={styles.td}>{r.task}</td>
                        <td style={styles.td}>{fmt(r.tokens_in)}</td>
                        <td style={styles.td}>{fmt(r.tokens_out)}</td>
                        <td style={styles.td}>
                          {r.latency_ms != null ? `${r.latency_ms}ms` : '—'}
                        </td>
                        <td style={styles.td}>{formatCost(r.cost_usd)}</td>
                        <td
                          style={{
                            ...styles.td,
                            color: r.error ? '#ef4444' : 'var(--text-muted)',
                            fontSize: 11,
                            maxWidth: 200,
                          }}
                        >
                          {truncate(r.error, 60)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
}

/* ── Styles ──────────────────────────────────────────────── */

const styles: Record<string, React.CSSProperties> = {
  page: {
    padding: '24px',
    maxWidth: 1200,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 24,
    flexWrap: 'wrap',
    gap: 12,
  },
  title: {
    margin: 0,
    fontSize: 20,
    fontWeight: 600,
    color: 'var(--text-primary)',
  },
  controls: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  timeSelector: {
    display: 'flex',
    gap: 4,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 6,
    padding: 3,
  },
  timeBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    padding: '4px 10px',
    borderRadius: 4,
    fontSize: 13,
  },
  timeBtnActive: {
    background: 'var(--accent)',
    color: '#fff',
  },
  refreshBtn: {
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    color: 'var(--text-primary)',
    cursor: 'pointer',
    padding: '6px 14px',
    borderRadius: 6,
    fontSize: 13,
  },
  errorBanner: {
    background: 'rgba(239,68,68,0.12)',
    border: '1px solid rgba(239,68,68,0.4)',
    color: '#ef4444',
    borderRadius: 6,
    padding: '10px 14px',
    marginBottom: 16,
    fontSize: 13,
  },
  empty: {
    color: 'var(--text-muted)',
    fontSize: 13,
    padding: '12px 0',
  },
  section: {
    marginBottom: 20,
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 8,
    overflow: 'hidden',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    width: '100%',
    background: 'transparent',
    border: 'none',
    borderBottom: '1px solid var(--border)',
    color: 'var(--text-primary)',
    cursor: 'pointer',
    fontSize: 14,
    fontWeight: 600,
    padding: '12px 16px',
    textAlign: 'left',
  },
  sectionBody: {
    padding: '16px',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 13,
  },
  th: {
    textAlign: 'left',
    color: 'var(--text-muted)',
    fontWeight: 500,
    fontSize: 12,
    padding: '6px 12px',
    borderBottom: '1px solid var(--border)',
    whiteSpace: 'nowrap',
  },
  td: {
    padding: '8px 12px',
    color: 'var(--text-primary)',
    borderBottom: '1px solid rgba(255,255,255,0.04)',
    verticalAlign: 'top',
  },
  tr: {
    transition: 'background 0.1s',
  },
  dot: {
    display: 'inline-block',
    width: 8,
    height: 8,
    borderRadius: '50%',
    marginRight: 8,
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
    gap: 12,
    marginBottom: 20,
  },
  statCard: {
    background: 'var(--bg-secondary, rgba(255,255,255,0.03))',
    border: '1px solid var(--border)',
    borderRadius: 6,
    padding: '12px 16px',
  },
  statLabel: {
    color: 'var(--text-muted)',
    fontSize: 11,
    marginBottom: 4,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  statValue: {
    color: 'var(--text-primary)',
    fontSize: 20,
    fontWeight: 600,
  },
  subHeading: {
    color: 'var(--text-muted)',
    fontSize: 12,
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: 8,
    marginTop: 16,
  },
  showAllBtn: {
    background: 'transparent',
    border: '1px solid var(--border)',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: 12,
    marginTop: 10,
    padding: '4px 12px',
    borderRadius: 4,
  },
};

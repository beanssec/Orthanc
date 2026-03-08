import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import '../../styles/dashboard.css';

// ── Types ──────────────────────────────────────────────────

interface DashboardStats {
  total_posts: number;
  total_events: number;
  total_entities: number;
  total_sources: number;
  posts_last_24h: number;
  posts_by_source_type: Record<string, number>;
  top_entities: Array<{ name: string; type: string; mention_count: number; id?: number }>;
  recent_alerts: unknown[];
  collector_status: Record<string, string>;
  source_health: Array<{ name: string; type: string; last_polled: string | null; status: string }>;
  recent_posts?: RecentPost[];
}

interface RecentPost {
  id: number;
  title?: string;
  content?: string;
  source_type?: string;
  author?: string;
  published_at?: string;
  created_at?: string;
}

interface VelocityBucket {
  hour: string;
  counts: Record<string, number>;
  total: number;
}

interface SourceHealthRow {
  source_type: string;
  total_posts: number;
  last_post: string | null;
  posts_1h: number;
  posts_24h: number;
  status: 'active' | 'idle' | 'stale';
}

interface TrendingEntity {
  name: string;
  type: string;
  mentions: number;
  id?: number;
}

interface GeoHotspot {
  place_name: string;
  lat: number | null;
  lng: number | null;
  count: number;
}

interface TrendingNarrative {
  id: string;
  title: string;
  post_count: number;
  divergence_score: number;
  consensus: string | null;
  status: string;
}

interface AlertEvent {
  id: number | string;
  severity?: string;
  title?: string;
  summary?: string;
  message?: string;
  keyword?: string;
  pattern?: string;
  created_at?: string;
  fired_at?: string;
  acknowledged?: boolean;
}

interface FusedIntelEvent {
  id: string;
  severity: string;
  source_count: number;
  post_count: number;
  ai_summary: string | null;
  entity_names: string[];
  component_source_types: string[];
  created_at: string | null;
}

// ── Source type colours ────────────────────────────────────
const SOURCE_COLORS: Record<string, string> = {
  rss:      '#10b981',
  x:        '#38bdf8',
  telegram: '#3b82f6',
  reddit:   '#ff4500',
  discord:  '#5865f2',
  shodan:   '#ff6b35',
  webhook:  '#f59e0b',
  youtube:  '#ff0000',
  firms:    '#ef4444',
  flight:   '#a855f7',
  ais:      '#06b6d4',
  cashtag:  '#84cc16',
  bluesky:  '#0085ff',
  mastodon: '#6364ff',
};

function sourceColor(type: string): string {
  return SOURCE_COLORS[type?.toLowerCase()] ?? '#9ca3af';
}

// ── Helpers ────────────────────────────────────────────────
function entityTypeClass(type: string): string {
  const map: Record<string, string> = {
    PERSON: 'person', ORG: 'org', GPE: 'gpe', EVENT: 'event', NORP: 'norp',
  };
  return map[type?.toUpperCase()] ?? 'norp';
}

function sourceIcon(type: string): string {
  const icons: Record<string, string> = {
    rss: '📡', x: '𝕏', telegram: '✈️', webhook: '🔗',
    reddit: '🤖', discord: '💬', shodan: '🔍', youtube: '📹', firms: '🔥',
    flight: '✈', ais: '🚢', cashtag: '💰', bluesky: '🦋', mastodon: '🐘',
  };
  return icons[type?.toLowerCase()] ?? '📰';
}

function severityEmoji(sev?: string): string {
  switch (sev?.toLowerCase()) {
    case 'critical':
    case 'urgent':   return '🔴';
    case 'high':     return '🟠';
    case 'medium':
    case 'warning':  return '🟡';
    case 'low':
    case 'info':     return '🟢';
    default:         return '⚪';
  }
}

function formatTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  const d = new Date(ts);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return d.toLocaleDateString();
}

function formatShortTime(ts: string | null | undefined): string {
  if (!ts) return '';
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function formatHour(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  } catch {
    return iso.slice(11, 16);
  }
}

// ── Velocity SVG Bar Chart ─────────────────────────────────
function VelocityChart({ buckets }: { buckets: VelocityBucket[] }) {
  const navigate = useNavigate();
  const [tooltip, setTooltip] = useState<{ x: number; y: number; bucket: VelocityBucket } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 560, h: 200 });

  useEffect(() => {
    const measure = () => {
      if (wrapRef.current) {
        const rect = wrapRef.current.getBoundingClientRect();
        setDims({ w: Math.max(200, rect.width), h: Math.max(120, rect.height) });
      }
    };
    measure();
    const obs = new ResizeObserver(measure);
    if (wrapRef.current) obs.observe(wrapRef.current);
    return () => obs.disconnect();
  }, []);

  if (buckets.length === 0) {
    return (
      <div className="velocity-empty">No data for this period</div>
    );
  }

  const W = dims.w;
  const H = dims.h;
  const padL = 28;
  const padR = 8;
  const padT = 8;
  const padB = 24;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const maxTotal = Math.max(...buckets.map((b) => b.total), 1);
  const barW = Math.max(2, (chartW / buckets.length) - 1);
  const gap = (chartW / buckets.length) - barW;

  // All source types present
  const allSources = Array.from(
    new Set(buckets.flatMap((b) => Object.keys(b.counts)))
  );

  // Y-axis labels
  const yTicks = [0, Math.round(maxTotal / 2), maxTotal];

  return (
    <div ref={wrapRef} className="velocity-chart-wrap" style={{ position: 'relative', width: '100%', flex: 1, minHeight: 0 }}>
      <svg
        ref={svgRef}
        width={W}
        height={H}
        style={{ display: 'block', cursor: 'crosshair' }}
        onMouseLeave={() => setTooltip(null)}
      >
        {/* Y-axis gridlines + labels */}
        {yTicks.map((tick) => {
          const y = padT + chartH - (tick / maxTotal) * chartH;
          return (
            <g key={tick}>
              <line
                x1={padL} y1={y} x2={W - padR} y2={y}
                stroke="var(--border)" strokeWidth={0.5}
              />
              <text
                x={padL - 4} y={y + 3}
                textAnchor="end"
                fontSize={8}
                fill="var(--text-muted)"
              >
                {tick}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {buckets.map((bucket, i) => {
          const x = padL + i * (barW + gap);
          let yOff = 0;
          const segments = allSources.map((src) => {
            const cnt = bucket.counts[src] ?? 0;
            const barH = (cnt / maxTotal) * chartH;
            const seg = (
              <rect
                key={src}
                x={x}
                y={padT + chartH - yOff - barH}
                width={barW}
                height={barH}
                fill={sourceColor(src)}
                opacity={0.85}
              />
            );
            yOff += barH;
            return seg;
          });

          // X-axis label — show every ~4 buckets to avoid crowding
          const showLabel = i === 0 || i === buckets.length - 1 || i % Math.ceil(buckets.length / 6) === 0;

          return (
            <g key={bucket.hour} style={{ cursor: 'pointer' }}>
              {/* hover hit area */}
              <rect
                x={x}
                y={padT}
                width={barW}
                height={chartH}
                fill="transparent"
                onMouseEnter={(e) => {
                  const svgRect = svgRef.current?.getBoundingClientRect();
                  if (!svgRect) return;
                  setTooltip({
                    x: e.clientX - svgRect.left,
                    y: e.clientY - svgRect.top,
                    bucket,
                  });
                }}
                onClick={() => {
                  const nextHour = new Date(new Date(bucket.hour).getTime() + 3600000).toISOString();
                  navigate(`/feed?date_from=${encodeURIComponent(bucket.hour)}&date_to=${encodeURIComponent(nextHour)}`);
                }}
              />
              {segments}
              {showLabel && (
                <text
                  x={x + barW / 2}
                  y={H - 4}
                  textAnchor="middle"
                  fontSize={7.5}
                  fill="var(--text-muted)"
                >
                  {formatHour(bucket.hour)}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="velocity-tooltip"
          style={{
            position: 'absolute',
            left: tooltip.x + 8,
            top: tooltip.y - 10,
            pointerEvents: 'none',
          }}
        >
          <div className="velocity-tooltip__hour">{formatHour(tooltip.bucket.hour)}</div>
          <div className="velocity-tooltip__total">{tooltip.bucket.total} posts</div>
          {Object.entries(tooltip.bucket.counts).map(([src, cnt]) => (
            <div key={src} className="velocity-tooltip__row">
              <span className="velocity-tooltip__dot" style={{ background: sourceColor(src) }} />
              <span>{src}: {cnt}</span>
            </div>
          ))}
          <div className="velocity-tooltip__hint">Click to open feed</div>
        </div>
      )}

      {/* Legend */}
      <div className="velocity-legend">
        {allSources.map((src) => (
          <span key={src} className="velocity-legend__item">
            <span className="velocity-legend__dot" style={{ background: sourceColor(src) }} />
            {src}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── KPI Card ───────────────────────────────────────────────
interface KpiCardProps {
  icon: string;
  value: string | number;
  label: string;
  sub?: string;
  delta?: number;
  onClick?: () => void;
}

function KpiCard({ icon, value, label, sub, delta, onClick }: KpiCardProps) {
  return (
    <div className={`kpi-card${onClick ? ' kpi-card--clickable' : ''}`} onClick={onClick}>
      <div className="kpi-card__icon">{icon}</div>
      <div className="kpi-card__value">{typeof value === 'number' ? value.toLocaleString() : value}</div>
      <div className="kpi-card__label">{label}</div>
      {sub && <div className="kpi-card__sub">{sub}</div>}
      {delta !== undefined && (
        <div className={`kpi-card__delta ${delta >= 0 ? 'kpi-card__delta--up' : 'kpi-card__delta--down'}`}>
          {delta >= 0 ? '▲' : '▼'} {Math.abs(delta)}%
        </div>
      )}
      {onClick && <div className="kpi-card__arrow">→</div>}
    </div>
  );
}

// ── Source Health Strip ────────────────────────────────────
function SourceHealthStrip({
  sourceHealth,
  navigate,
}: {
  sourceHealth: SourceHealthRow[];
  navigate: (path: string) => void;
}) {
  if (sourceHealth.length === 0) {
    return <div className="source-health-strip"><span style={{ color: 'var(--text-muted)', fontSize: 12 }}>No source data yet</span></div>;
  }

  return (
    <div className="source-health-strip">
      <span className="source-health-strip__label">SOURCES</span>
      {sourceHealth.map((row) => (
        <div
          key={row.source_type}
          className={`source-pill source-pill--${row.status}`}
          onClick={() => navigate(`/feed?source=${row.source_type}`)}
          title={`Last post: ${formatTime(row.last_post)}\n1h: ${row.posts_1h} | 24h: ${row.posts_24h}\nClick to filter feed`}
        >
          <span className={`source-pill__dot source-pill__dot--${row.status}`} />
          <span className="source-pill__icon">{sourceIcon(row.source_type)}</span>
          <span className="source-pill__name">{row.source_type}</span>
          <span className="source-pill__count">{row.posts_24h}</span>
        </div>
      ))}
    </div>
  );
}

// ── Component ──────────────────────────────────────────────
export function DashboardView() {
  const navigate = useNavigate();

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [velocity, setVelocity] = useState<VelocityBucket[]>([]);
  const [sourceHealth, setSourceHealth] = useState<SourceHealthRow[]>([]);
  const [trendingEntities, setTrendingEntities] = useState<TrendingEntity[]>([]);
  const [trendingNarratives, setTrendingNarratives] = useState<TrendingNarrative[]>([]);
  const [geoHotspots, setGeoHotspots] = useState<GeoHotspot[]>([]);
  const [alerts, setAlerts] = useState<AlertEvent[]>([]);
  const [fusedEvents, setFusedEvents] = useState<FusedIntelEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchAll = useCallback(async () => {
    try {
      const [statsRes, velRes, healthRes, entRes, geoRes] = await Promise.allSettled([
        api.get('/dashboard/stats'),
        api.get('/dashboard/velocity?hours=24'),
        api.get('/dashboard/source-health'),
        api.get('/dashboard/trending-entities?hours=6&limit=10'),
        api.get('/dashboard/geo-hotspots?hours=24&limit=10'),
      ]);

      if (statsRes.status === 'fulfilled') setStats(statsRes.value.data);
      if (velRes.status === 'fulfilled') setVelocity(velRes.value.data);
      if (healthRes.status === 'fulfilled') setSourceHealth(healthRes.value.data);
      if (entRes.status === 'fulfilled') setTrendingEntities(entRes.value.data);
      if (geoRes.status === 'fulfilled') setGeoHotspots(geoRes.value.data);

      // Alerts — best-effort
      try {
        const alertRes = await api.get('/alerts/events/?acknowledged=false&limit=5');
        setAlerts(alertRes.data?.items ?? alertRes.data ?? []);
      } catch {
        // alerts endpoint may not exist yet
      }

      // Fused intelligence events — best-effort
      try {
        const fusionRes = await api.get('/fusion/events?hours=24&limit=10');
        setFusedEvents(fusionRes.data ?? []);
      } catch {
        // fusion endpoint may have no data yet
      }

      // Trending narratives — best-effort
      try {
        const narrativesRes = await api.get('/narratives/trending?hours=6&limit=5');
        setTrendingNarratives(narrativesRes.data ?? []);
      } catch {
        // narratives endpoint may not have data yet
      }

      setLastRefresh(new Date());
      setError(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load dashboard';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 60000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  if (loading) {
    return (
      <div className="dashboard__loading">
        <span className="spinner" />
        Loading dashboard…
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="dashboard__error">⚠ {error}</div>
    );
  }

  // Derived values
  const activeSourceCount = sourceHealth.filter((s) => s.status === 'active').length;
  const maxMentions = Math.max(...trendingEntities.map((e) => e.mentions), 1);
  const maxGeoCount = Math.max(...geoHotspots.map((g) => g.count), 1);

  return (
    <div className="dashboard">

      {/* ── Header ────────────────────────────────────── */}
      <div className="dashboard__header">
        <h1 className="dashboard__title">Command Center</h1>
        <span className="dashboard__refresh">
          Auto-refresh 60s · {formatShortTime(lastRefresh.toISOString())}
        </span>
      </div>

      {/* ── Row 1: KPI Strip ──────────────────────────── */}
      <div className="kpi-strip">
        <KpiCard
          icon="📰"
          value={stats?.posts_last_24h ?? 0}
          label="Posts (24h)"
          sub={`${(stats?.total_posts ?? 0).toLocaleString()} total`}
          onClick={() => navigate('/feed')}
        />
        <KpiCard
          icon="🗺️"
          value={stats?.total_events ?? 0}
          label="Map Events"
          sub="Geo-located"
          onClick={() => navigate('/map')}
        />
        <KpiCard
          icon="🔗"
          value={stats?.total_entities ?? 0}
          label="Entities"
          sub="Tracked"
          onClick={() => navigate('/entities')}
        />
        <KpiCard
          icon="📡"
          value={activeSourceCount}
          label="Active Sources"
          sub={`of ${sourceHealth.length} total`}
          onClick={() => navigate('/settings/sources')}
        />
        <KpiCard
          icon="🚨"
          value={alerts.length}
          label="Unread Alerts"
          sub={alerts.length === 0 ? 'All clear' : 'Require attention'}
          onClick={() => navigate('/settings/alerts')}
        />
      </div>

      {/* ── Row 2: Source Health Strip (full width) ───── */}
      <SourceHealthStrip sourceHealth={sourceHealth} navigate={navigate} />

      {/* ── Row 3: Post Velocity (full width) ─────────── */}
      <div className="dash-card dash-card--full">
        <div className="dash-card__header">
          <span className="dash-card__title">Post Velocity — Last 24h</span>
          <span className="dash-card__meta">hourly buckets · click bars to open feed</span>
        </div>
        <div className="dash-card__body dash-card__body--velocity">
          <VelocityChart buckets={velocity} />
        </div>
      </div>

      {/* ── Row 4: Trending Entities + Trending Narratives + Geographic Hotspots */}
      <div className="dashboard-row dashboard-row--3col">

        {/* Trending Entities */}
        <div className="dash-card">
          <div className="dash-card__header">
            <span className="dash-card__title">Trending Entities</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/entities')}>
              View all →
            </button>
          </div>
          <div className="dash-card__body">
            {trendingEntities.length === 0 ? (
              <div className="dash-empty">No entity data in last 6h</div>
            ) : (
              <div className="entity-bars">
                {trendingEntities.map((ent, i) => (
                  <div
                    key={i}
                    className="entity-bar-row"
                    onClick={() => {
                      if (ent.id) {
                        navigate(`/entities?selected=${ent.id}`);
                      } else {
                        navigate(`/entities?search=${encodeURIComponent(ent.name)}`);
                      }
                    }}
                  >
                    <span className={`badge badge--${entityTypeClass(ent.type)}`}>
                      {ent.type}
                    </span>
                    <span className="entity-bar-row__name">{ent.name}</span>
                    <div className="entity-bar-row__track">
                      <div
                        className="entity-bar-row__fill"
                        style={{ width: `${(ent.mentions / maxMentions) * 100}%` }}
                      />
                    </div>
                    <span className="entity-bar-row__count">{ent.mentions}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Trending Narratives */}
        <div className="dash-card">
          <div className="dash-card__header">
            <span className="dash-card__title">Trending Narratives</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/narratives')}>
              View all →
            </button>
          </div>
          <div className="dash-card__body">
            {trendingNarratives.length === 0 ? (
              <div className="dash-empty" style={{ fontSize: '0.75rem', lineHeight: 1.5 }}>
                No active narratives — narratives will appear as the clustering engine processes posts
              </div>
            ) : (
              <div>
                {trendingNarratives.map((narr) => {
                  const divergenceLevel =
                    narr.divergence_score >= 0.7 ? 'high' :
                    narr.divergence_score >= 0.4 ? 'medium' : 'low';
                  return (
                    <div
                      key={narr.id}
                      className="dashboard-narrative-item"
                      onClick={() => navigate(`/narratives?id=${narr.id}`)}
                    >
                      <span className={`narrative-divergence-dot ${divergenceLevel}`} />
                      <span className="narrative-title-truncated">{narr.title}</span>
                      <span className="narrative-post-count">{narr.post_count} posts</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Geographic Hotspots */}
        <div className="dash-card">
          <div className="dash-card__header">
            <span className="dash-card__title">Geographic Hotspots</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/map')}>
              Map →
            </button>
          </div>
          <div className="dash-card__body">
            {geoHotspots.length === 0 ? (
              <div className="dash-empty">No geo data in last 24h</div>
            ) : (
              <div className="geo-list">
                {geoHotspots.map((spot, i) => (
                  <div
                    key={i}
                    className="geo-row"
                    onClick={() => navigate(`/map?lat=${spot.lat ?? 0}&lng=${spot.lng ?? 0}&zoom=6`)}
                  >
                    <span className="geo-row__rank">{i + 1}</span>
                    <span className="geo-row__name">{spot.place_name}</span>
                    <div className="geo-row__track">
                      <div
                        className="geo-row__fill"
                        style={{ width: `${(spot.count / maxGeoCount) * 100}%` }}
                      />
                    </div>
                    <span className="geo-row__count">{spot.count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Row 5: Recent Alerts + Activity Feed ───────── */}
      <div className="dashboard-row dashboard-row--5050">

        {/* Recent Alerts */}
        <div className="dash-card">
          <div className="dash-card__header">
            <span className="dash-card__title">Recent Alerts</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/settings/alerts')}>
              View all →
            </button>
          </div>
          <div className="dash-card__body">
            {alerts.length === 0 ? (
              <div className="dash-empty dash-empty--calm">
                <span style={{ fontSize: 24 }}>✅</span>
                No unread alerts — all clear
              </div>
            ) : (
              <div className="alert-list">
                {alerts.slice(0, 5).map((alert, i) => (
                  <div
                    key={alert.id ?? i}
                    className="alert-row alert-row--clickable"
                    onClick={() => {
                      const searchTerm = alert.keyword || alert.pattern || alert.title || alert.message;
                      if (searchTerm) {
                        navigate(`/feed?search=${encodeURIComponent(searchTerm)}`);
                      } else {
                        navigate(`/settings/alerts?highlight=${alert.id}`);
                      }
                    }}
                  >
                    <span className="alert-row__sev">
                      {severityEmoji(alert.severity)}
                    </span>
                    <div className="alert-row__body">
                      <div className="alert-row__title">{alert.title ?? alert.message ?? 'Alert'}</div>
                      <div className="alert-row__time">{formatTime(alert.fired_at ?? alert.created_at)}</div>
                    </div>
                    <span className="alert-row__chevron">›</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Activity Feed */}
        <div className="dash-card">
          <div className="dash-card__header">
            <span className="dash-card__title">Recent Activity</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/feed')}>
              Feed →
            </button>
          </div>
          <div className="dash-card__body">
            {stats?.recent_posts && stats.recent_posts.length > 0 ? (
              <div className="activity-feed">
                {stats.recent_posts.slice(0, 10).map((post) => (
                  <div
                    key={post.id}
                    className="activity-feed__item"
                    onClick={() => navigate(`/feed?post=${post.id}`)}
                  >
                    <span className="activity-feed__icon">
                      {sourceIcon(post.source_type ?? '')}
                    </span>
                    <div className="activity-feed__content">
                      <div className="activity-feed__meta">
                        <span
                          className="activity-feed__badge"
                          style={{ background: `${sourceColor(post.source_type ?? '')}22`, color: sourceColor(post.source_type ?? ''), border: `1px solid ${sourceColor(post.source_type ?? '')}44` }}
                        >
                          {post.source_type?.toUpperCase()}
                        </span>
                        <span className="activity-feed__author">
                          {post.author ?? 'Unknown'}
                        </span>
                        <span className="activity-feed__time">
                          {formatTime(post.published_at ?? post.created_at)}
                        </span>
                      </div>
                      <div className="activity-feed__preview">
                        {post.title ?? post.content ?? '—'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="dash-empty">
                <span>{stats?.posts_last_24h ?? 0} posts ingested in last 24h</span>
                <button className="btn btn-secondary btn-sm" style={{ marginTop: 8 }} onClick={() => navigate('/feed')}>
                  Open feed →
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Row 6: Intelligence Fusion (only if data exists) ─────────── */}
      {fusedEvents.length > 0 && (
        <div className="dash-card dash-card--full">
          <div className="dash-card__header">
            <span className="dash-card__title">◆ Intelligence Fusion</span>
            <span className="dash-card__meta">{fusedEvents.length} multi-source events · last 24h</span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/map')}>
              Map →
            </button>
          </div>
          <div className="dash-card__body">
            <div className="fusion-list">
              {fusedEvents.slice(0, 5).map((ev) => {
                const sevColors: Record<string, string> = { flash: '#ef4444', urgent: '#f97316', routine: '#3b82f6' };
                const color = sevColors[ev.severity] ?? '#6b7280';
                const summary = (ev.ai_summary ?? '').slice(0, 180);
                const places = ev.entity_names?.slice(0, 3).join(', ') || '';
                return (
                  <div key={ev.id} className="fusion-row">
                    <div className="fusion-row__sev" style={{ color }}>
                      <span style={{ display: 'inline-block', width: 10, height: 10, transform: 'rotate(45deg)', background: color, flexShrink: 0, marginRight: 4 }} />
                      {ev.severity.toUpperCase()}
                    </div>
                    <div className="fusion-row__body">
                      <div className="fusion-row__meta">
                        <span className="fusion-row__sources">{ev.source_count} sources</span>
                        <span className="fusion-row__posts">{ev.post_count} posts</span>
                        {places && <span className="fusion-row__place">📍 {places}</span>}
                        <span className="fusion-row__time">{formatTime(ev.created_at)}</span>
                      </div>
                      <div className="fusion-row__types">
                        {ev.component_source_types.map((s) => (
                          <span key={s} className="fusion-row__tag" style={{ background: `${sourceColor(s)}22`, color: sourceColor(s), border: `1px solid ${sourceColor(s)}44` }}>
                            {s}
                          </span>
                        ))}
                      </div>
                      {summary && <div className="fusion-row__summary">{summary}</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

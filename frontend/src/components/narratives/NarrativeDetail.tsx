import { useEffect, useState, useMemo } from 'react';
import api from '../../services/api';
import { NarrativeDetail as NarrativeDetailType, NarrativePost, Claim } from './types';
import { timeAgo, pct, claimStatusIcon } from './utils';

interface NarrativeDetailProps {
  narrativeId: string;
}

type TabKey = 'overview' | 'stances' | 'claims' | 'timeline';

// ── Sub-components ──────────────────────────────────────────

function StanceBadge({ stance }: { stance: string }) {
  const cls = stance.toLowerCase().replace(/[^a-z]/g, '');
  return <span className={`stance-badge ${cls}`}>{stance}</span>;
}

function OverviewTab({ detail }: { detail: NarrativeDetailType }) {
  return (
    <div>
      {detail.summary && (
        <p className="narrative-detail-summary" style={{ marginBottom: '1rem' }}>
          {detail.summary}
        </p>
      )}

      <div className="narrative-detail-stats">
        <div className="narrative-stat">
          <div className="narrative-stat-value">{detail.post_count}</div>
          <div className="narrative-stat-label">Posts</div>
        </div>
        <div className="narrative-stat">
          <div className="narrative-stat-value">{detail.source_count}</div>
          <div className="narrative-stat-label">Sources</div>
        </div>
        <div className="narrative-stat">
          <div className="narrative-stat-value">{pct(detail.divergence_score)}</div>
          <div className="narrative-stat-label">Divergence</div>
        </div>
        <div className="narrative-stat">
          <div className="narrative-stat-value">{pct(detail.evidence_score)}</div>
          <div className="narrative-stat-label">Evidence</div>
        </div>
        <div className="narrative-stat">
          <div className="narrative-stat-value">{detail.claims.length}</div>
          <div className="narrative-stat-label">Claims</div>
        </div>
      </div>

      {detail.consensus && (
        <div style={{ marginTop: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Consensus:</span>
          <span className={`consensus-badge ${detail.consensus}`}>{detail.consensus}</span>
        </div>
      )}

      {detail.topic_keywords.length > 0 && (
        <div className="narrative-keywords">
          {detail.topic_keywords.map((kw) => (
            <span key={kw} className="narrative-keyword">{kw}</span>
          ))}
        </div>
      )}

      <div style={{ marginTop: '1rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
        <span>First seen: {timeAgo(detail.first_seen)}</span>
        <span style={{ marginLeft: '1rem' }}>Last updated: {timeAgo(detail.last_updated)}</span>
      </div>
    </div>
  );
}

function StancesTab({ detail }: { detail: NarrativeDetailType }) {
  const stanceByGroup = detail.stance_by_group ?? {};
  const groups = Object.entries(stanceByGroup);

  // Group posts by source_type for display
  const postsByGroup = useMemo(() => {
    const map: Record<string, NarrativePost[]> = {};
    for (const post of detail.posts) {
      const key = post.source_type ?? 'Unknown';
      if (!map[key]) map[key] = [];
      map[key].push(post);
    }
    return map;
  }, [detail.posts]);

  if (groups.length === 0 && detail.posts.length === 0) {
    return (
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', padding: '1rem 0' }}>
        No stance data available yet.
      </div>
    );
  }

  // Render groups from stance_by_group if available, else fall back to grouped posts
  if (groups.length > 0) {
    return (
      <div>
        {groups.map(([groupName, groupData]) => {
          const groupPosts = detail.posts.filter(
            (p) => p.source_type?.toLowerCase() === groupName.toLowerCase()
          );
          const stanceEntries = Object.entries(groupData.stances);
          const totalStances = stanceEntries.reduce((s, [, v]) => s + v, 0);

          return (
            <div key={groupName} className="stance-group">
              <div className="stance-group-header">
                <div className="stance-group-dot" style={{ backgroundColor: groupData.color }} />
                <span className="stance-group-name">{groupName}</span>
                <span className="stance-group-count">({groupPosts.length} posts)</span>
              </div>

              {/* Stance distribution mini-bars */}
              {totalStances > 0 && (
                <div className="stance-bars">
                  {stanceEntries.map(([stance, count]) => (
                    <div
                      key={stance}
                      className="stance-bar-segment"
                      style={{
                        width: `${(count / totalStances) * 100}%`,
                        background: stanceColor(stance),
                        opacity: 0.7,
                      }}
                      title={`${stance}: ${count}`}
                    />
                  ))}
                </div>
              )}

              {groupPosts.slice(0, 5).map((post) => (
                <PostRow key={post.id} post={post} />
              ))}
              {groupPosts.length > 5 && (
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', padding: '0.25rem 0.5rem' }}>
                  +{groupPosts.length - 5} more posts
                </div>
              )}
            </div>
          );
        })}

        {/* Posts that don't match any known group */}
        {Object.entries(postsByGroup)
          .filter(([key]) => !groups.some(([g]) => g.toLowerCase() === key.toLowerCase()))
          .map(([groupName, posts]) => (
            <div key={groupName} className="stance-group">
              <div className="stance-group-header">
                <div className="stance-group-dot" style={{ backgroundColor: '#6b7280' }} />
                <span className="stance-group-name">{groupName}</span>
                <span className="stance-group-count">({posts.length} posts)</span>
              </div>
              {posts.slice(0, 5).map((post) => (
                <PostRow key={post.id} post={post} />
              ))}
            </div>
          ))}
      </div>
    );
  }

  // Fallback: just group by source_type
  return (
    <div>
      {Object.entries(postsByGroup).map(([groupName, posts]) => (
        <div key={groupName} className="stance-group">
          <div className="stance-group-header">
            <div className="stance-group-dot" style={{ backgroundColor: '#6b7280' }} />
            <span className="stance-group-name">{groupName}</span>
            <span className="stance-group-count">({posts.length})</span>
          </div>
          {posts.slice(0, 8).map((post) => (
            <PostRow key={post.id} post={post} />
          ))}
        </div>
      ))}
    </div>
  );
}

function PostRow({ post }: { post: NarrativePost }) {
  return (
    <div className="stance-post">
      <div className="stance-post-header">
        <span className="stance-post-author">{post.author}</span>
        <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
          {post.stance && <StanceBadge stance={post.stance} />}
          <span className="stance-post-time">{timeAgo(post.timestamp)}</span>
        </div>
      </div>
      {post.stance_summary && (
        <div className="stance-post-summary">{post.stance_summary}</div>
      )}
    </div>
  );
}

function stanceColor(stance: string): string {
  const map: Record<string, string> = {
    confirming: '#10b981',
    denying: '#ef4444',
    attributing: '#f59e0b',
    contextualizing: '#3b82f6',
    deflecting: '#9ca3af',
    speculating: '#8b5cf6',
  };
  return map[stance.toLowerCase()] ?? '#6b7280';
}

function ClaimsTab({ claims }: { claims: Claim[] }) {
  if (claims.length === 0) {
    return (
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', padding: '1rem 0' }}>
        No claims tracked for this narrative yet.
      </div>
    );
  }

  return (
    <div className="claims-list">
      {claims.map((claim) => (
        <div key={claim.id} className="claim-row">
          <div className="claim-status-icon">{claimStatusIcon(claim.status)}</div>
          <div className="claim-body">
            <div className="claim-text">{claim.claim_text}</div>
            <div className="claim-meta">
              <span className="claim-type-badge">{claim.claim_type}</span>
              <span className={`consensus-badge ${claim.status}`}>{claim.status}</span>
              {claim.evidence_count > 0 && (
                <span className="claim-evidence-count">{claim.evidence_count} evidence</span>
              )}
              {claim.first_claimed_by && (
                <span>First: {claim.first_claimed_by}</span>
              )}
              {claim.first_claimed_at && (
                <span>{timeAgo(claim.first_claimed_at)}</span>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function TimelineTab({ posts }: { posts: NarrativePost[] }) {
  if (posts.length === 0) {
    return (
      <div className="timeline-empty">No post timeline data available.</div>
    );
  }

  // Build hourly buckets
  const buckets = useMemo(() => {
    const map: Record<string, { hour: string; count: number; groups: Record<string, number> }> = {};
    for (const post of posts) {
      const d = new Date(post.timestamp);
      if (isNaN(d.getTime())) continue;
      const hour = new Date(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours()).toISOString();
      if (!map[hour]) map[hour] = { hour, count: 0, groups: {} };
      map[hour].count++;
      const g = post.source_type ?? 'Unknown';
      map[hour].groups[g] = (map[hour].groups[g] ?? 0) + 1;
    }
    return Object.values(map).sort((a, b) => a.hour.localeCompare(b.hour));
  }, [posts]);

  if (buckets.length === 0) {
    return <div className="timeline-empty">No timestamped posts.</div>;
  }

  const maxCount = Math.max(...buckets.map((b) => b.count), 1);
  const svgH = 120;
  const svgPad = { top: 8, bottom: 24, left: 36, right: 8 };
  const plotH = svgH - svgPad.top - svgPad.bottom;
  const barW = Math.max(4, Math.min(24, (800 - svgPad.left - svgPad.right) / buckets.length - 2));

  // Collect unique groups for colors
  const allGroups = Array.from(new Set(posts.map((p) => p.source_type ?? 'Unknown')));
  const groupColors: Record<string, string> = {};
  const palette = ['#3b82f6', '#10b981', '#ef4444', '#f59e0b', '#8b5cf6', '#06b6d4', '#f43f5e'];
  allGroups.forEach((g, i) => { groupColors[g] = palette[i % palette.length]; });

  const totalPlotW = buckets.length * (barW + 2);

  return (
    <div className="timeline-container" style={{ overflowX: 'auto' }}>
      <svg
        width={Math.max(600, totalPlotW + svgPad.left + svgPad.right)}
        height={svgH}
        style={{ display: 'block' }}
      >
        {/* Y axis */}
        <line
          x1={svgPad.left}
          y1={svgPad.top}
          x2={svgPad.left}
          y2={svgPad.top + plotH}
          stroke="var(--border-primary)"
          strokeWidth={1}
        />
        {[0, 0.5, 1].map((ratio) => {
          const yPos = svgPad.top + plotH - ratio * plotH;
          return (
            <g key={ratio}>
              <line
                x1={svgPad.left - 3}
                y1={yPos}
                x2={svgPad.left}
                y2={yPos}
                stroke="var(--border-primary)"
                strokeWidth={1}
              />
              <text
                x={svgPad.left - 5}
                y={yPos}
                textAnchor="end"
                dominantBaseline="middle"
                style={{ fontSize: '9px', fill: 'var(--text-secondary)' }}
              >
                {Math.round(ratio * maxCount)}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {buckets.map((bucket, i) => {
          const x = svgPad.left + i * (barW + 2);
          const entries = Object.entries(bucket.groups);
          let yOffset = svgPad.top + plotH;

          return (
            <g key={bucket.hour}>
              {entries.map(([group, count]) => {
                const barH = Math.max(1, (count / maxCount) * plotH);
                yOffset -= barH;
                return (
                  <rect
                    key={group}
                    x={x}
                    y={yOffset}
                    width={barW}
                    height={barH}
                    fill={groupColors[group] ?? '#6b7280'}
                    fillOpacity={0.8}
                    rx={1}
                  >
                    <title>{`${group}: ${count} posts`}</title>
                  </rect>
                );
              })}
              {/* Hour label every few bars */}
              {i % Math.max(1, Math.floor(buckets.length / 8)) === 0 && (
                <text
                  x={x + barW / 2}
                  y={svgPad.top + plotH + 14}
                  textAnchor="middle"
                  style={{ fontSize: '9px', fill: 'var(--text-secondary)' }}
                >
                  {new Date(bucket.hour).getHours()}h
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
        {allGroups.map((g) => (
          <div key={g} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: groupColors[g] }} />
            {g}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main component ──────────────────────────────────────────

export function NarrativeDetail({ narrativeId }: NarrativeDetailProps) {
  const [detail, setDetail] = useState<NarrativeDetailType | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>('overview');

  useEffect(() => {
    if (!narrativeId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setDetail(null);

    api
      .get(`/narratives/${narrativeId}`)
      .then((res) => {
        if (!cancelled) setDetail(res.data);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.response?.data?.detail ?? 'Failed to load narrative detail');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [narrativeId]);

  if (loading) {
    return (
      <div className="narrative-detail-loading">
        Loading narrative…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '1rem' }}>
        <div className="narratives-error">{error}</div>
      </div>
    );
  }

  if (!detail) return null;

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'overview', label: 'Overview' },
    { key: 'stances', label: `Stances (${detail.posts.length})` },
    { key: 'claims', label: `Claims (${detail.claims.length})` },
    { key: 'timeline', label: 'Timeline' },
  ];

  return (
    <>
      <div className="narrative-detail-header">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
          <div className="narrative-detail-title">{detail.title}</div>
          <div style={{ display: 'flex', gap: '0.4rem', flexShrink: 0 }}>
            {detail.consensus && (
              <span className={`consensus-badge ${detail.consensus}`}>{detail.consensus}</span>
            )}
            <span className={`narrative-status-badge ${detail.status}`}>{detail.status}</span>
          </div>
        </div>
        {detail.summary && (
          <div className="narrative-detail-summary">{detail.summary}</div>
        )}
      </div>

      <div className="narrative-tabs">
        {tabs.map((t) => (
          <button
            key={t.key}
            className={`narrative-tab${activeTab === t.key ? ' active' : ''}`}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="narrative-tab-content">
        {activeTab === 'overview' && <OverviewTab detail={detail} />}
        {activeTab === 'stances' && <StancesTab detail={detail} />}
        {activeTab === 'claims' && <ClaimsTab claims={detail.claims} />}
        {activeTab === 'timeline' && <TimelineTab posts={detail.posts} />}
      </div>
    </>
  );
}

export default NarrativeDetail;

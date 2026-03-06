import { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useFeedStore } from '../../stores/feedStore'
import type { Post } from '../../stores/feedStore'
import { useWebSocket } from '../../hooks/useWebSocket'
import FeedTimeline from './FeedTimeline'
import FeedDetail from './FeedDetail'
import FeedFilters from './FeedFilters'
import api from '../../services/api'
import '../../styles/feed.css'

// ── Source type colours (matches dashboard) ────────────────
const SOURCE_COLORS: Record<string, string> = {
  rss:      '#10b981',
  x:        '#38bdf8',
  telegram: '#3b82f6',
  reddit:   '#ff4500',
  discord:  '#5865f2',
  shodan:   '#ff6b35',
  webhook:  '#f59e0b',
  firms:    '#ef4444',
  flight:   '#a855f7',
  ais:      '#06b6d4',
  cashtag:  '#84cc16',
}

function srcColor(type: string): string {
  return SOURCE_COLORS[type?.toLowerCase()] ?? '#9ca3af'
}

interface VelocityBucket {
  hour: string
  counts: Record<string, number>
  total: number
}

// ── Volume Sparkline ───────────────────────────────────────
function VolumeSparkline() {
  const [buckets, setBuckets] = useState<VelocityBucket[]>([])
  const [tooltip, setTooltip] = useState<{ x: number; bucket: VelocityBucket } | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    api.get('/dashboard/velocity?hours=24')
      .then((r) => setBuckets(r.data))
      .catch(() => {/* silent */})
  }, [])

  if (buckets.length === 0) return null

  const W = 800
  const H = 40
  const maxTotal = Math.max(...buckets.map((b) => b.total), 1)
  const barW = Math.max(2, (W / buckets.length) - 1)
  const gap = (W / buckets.length) - barW

  const allSources = Array.from(
    new Set(buckets.flatMap((b) => Object.keys(b.counts)))
  )

  return (
    <div className="feed-sparkline" style={{ position: 'relative' }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: H, display: 'block' }}
        onMouseLeave={() => setTooltip(null)}
      >
        {buckets.map((bucket, i) => {
          const x = i * (barW + gap)
          let yOff = 0
          const segs = allSources.map((src) => {
            const cnt = bucket.counts[src] ?? 0
            const bh = (cnt / maxTotal) * H
            const seg = (
              <rect
                key={src}
                x={x}
                y={H - yOff - bh}
                width={barW}
                height={bh}
                fill={srcColor(src)}
                opacity={0.8}
              />
            )
            yOff += bh
            return seg
          })

          return (
            <g key={bucket.hour}>
              <rect
                x={x} y={0} width={barW} height={H}
                fill="transparent"
                onMouseEnter={(e) => {
                  const r = svgRef.current?.getBoundingClientRect()
                  if (!r) return
                  setTooltip({ x: e.clientX - r.left, bucket })
                }}
              />
              {segs}
            </g>
          )
        })}
      </svg>

      {tooltip && (
        <div
          className="feed-sparkline__tooltip"
          style={{
            position: 'absolute',
            left: Math.min(tooltip.x + 6, W - 120),
            top: H + 4,
            pointerEvents: 'none',
          }}
        >
          <div className="feed-sparkline__tooltip-hour">
            {new Date(tooltip.bucket.hour).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
          </div>
          <div className="feed-sparkline__tooltip-total">{tooltip.bucket.total} posts</div>
        </div>
      )}
    </div>
  )
}

// ── Main FeedView ──────────────────────────────────────────
export function FeedView() {
  const [searchParams] = useSearchParams()
  const [selectedPost, setSelectedPost] = useState<Post | null>(null)
  const [newPostIds, setNewPostIds] = useState<Set<string>>(new Set())
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false)
  const [mobileDetailOpen, setMobileDetailOpen] = useState(false)
  const { connected, reconnecting } = useWebSocket()
  const posts = useFeedStore((s) => s.posts)
  const filters = useFeedStore((s) => s.filters)

  // Apply URL param: ?source=telegram → pre-filter by source type
  useEffect(() => {
    const sourceParam = searchParams.get('source')
    if (sourceParam) {
      const sources = sourceParam.split(',').filter(Boolean) as Post['source_type'][]
      useFeedStore.getState().setFilters({ source_types: sources })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Apply URL param: ?post=uuid → auto-select that post
  useEffect(() => {
    const postParam = searchParams.get('post')
    if (!postParam || posts.length === 0) return
    const match = posts.find((p) => String(p.id) === String(postParam))
    if (match && selectedPost?.id !== match.id) {
      setSelectedPost(match)
      setMobileDetailOpen(true)
    }
  }, [posts, searchParams]) // eslint-disable-line react-hooks/exhaustive-deps

  // When a post is selected on mobile, open the detail overlay
  const handleSelectPost = (post: Post | null) => {
    setSelectedPost(post)
    if (post) setMobileDetailOpen(true)
  }

  // Track new posts from WebSocket for flash animation
  useEffect(() => {
    if (posts.length > 0) {
      const latest = posts[0]
      setNewPostIds((prev) => {
        const next = new Set(prev)
        next.add(latest.id)
        return next
      })
      const timer = setTimeout(() => {
        setNewPostIds((prev) => {
          const next = new Set(prev)
          next.delete(latest.id)
          return next
        })
      }, 1500)
      return () => clearTimeout(timer)
    }
  }, [posts.length])

  // Count posts per source type
  const sourceCounts = posts.reduce(
    (acc, p) => {
      acc[p.source_type] = (acc[p.source_type] || 0) + 1
      return acc
    },
    {} as Record<string, number>
  )

  const hasActiveFilters = Object.values(filters).some((v) =>
    Array.isArray(v) ? v.length > 0 : v !== null && v !== ''
  )

  return (
    <div className="feed-view">
      {/* ── Filter sidebar (desktop left col / mobile overlay) ── */}
      <div className={`feed-sidebar${mobileFiltersOpen ? ' feed-sidebar--mobile-open' : ''}`}>
        {/* Mobile overlay close header */}
        <div className="mobile-overlay-close">
          <span className="mobile-overlay-close__title">Filters</span>
          <button
            className="mobile-overlay-close__btn"
            onClick={() => setMobileFiltersOpen(false)}
            aria-label="Close filters"
          >
            ✕
          </button>
        </div>

        <div className="feed-sidebar__header-row" style={{ display: 'none' /* hidden; overlay header takes its place */ }}>
          <span className="feed-sidebar__title">Filters</span>
          {hasActiveFilters && (
            <button
              className="feed-sidebar__clear"
              onClick={() =>
                useFeedStore.getState().setFilters({
                  source_types: [],
                  keyword: '',
                  date_from: null,
                  date_to: null,
                })
              }
            >
              Clear all
            </button>
          )}
        </div>
        <FeedFilters counts={sourceCounts} />
      </div>

      {/* ── Timeline (center column) ── */}
      <div className="feed-timeline">
        <div className="feed-timeline__header">
          <span className="feed-timeline__title">Live Feed</span>
          <span className="feed-timeline__count">{posts.length} posts</span>
          <span
            className={`status-dot ${connected ? 'status-dot--active' : reconnecting ? 'status-dot--warning' : 'status-dot--error'}`}
            title={connected ? 'Connected' : reconnecting ? 'Reconnecting...' : 'Disconnected'}
          />
        </div>

        {/* Mobile controls bar — hidden on desktop via CSS */}
        <div className="feed-mobile-bar">
          <button
            className={`feed-mobile-bar__btn${hasActiveFilters ? ' feed-mobile-bar__btn--active' : ''}`}
            onClick={() => setMobileFiltersOpen(true)}
          >
            🔍 Filters{hasActiveFilters ? ' •' : ''}
          </button>
          {selectedPost && (
            <button
              className="feed-mobile-bar__btn"
              onClick={() => setMobileDetailOpen(true)}
            >
              📄 Detail
            </button>
          )}
        </div>

        {/* Volume sparkline between header and feed list */}
        <VolumeSparkline />

        <FeedTimeline
          selectedPost={selectedPost}
          onSelectPost={handleSelectPost}
          newPostIds={newPostIds}
        />
      </div>

      {/* ── Detail panel (desktop right col / mobile overlay) ── */}
      <div className={`feed-detail${mobileDetailOpen ? ' feed-detail--mobile-open' : ''}`}>
        {/* Mobile overlay close header */}
        {mobileDetailOpen && (
          <div className="mobile-overlay-close">
            <span className="mobile-overlay-close__title">Post Detail</span>
            <button
              className="mobile-overlay-close__btn"
              onClick={() => setMobileDetailOpen(false)}
              aria-label="Close detail"
            >
              ✕
            </button>
          </div>
        )}
        {selectedPost ? (
          <FeedDetail post={selectedPost} />
        ) : (
          <div className="feed-detail__empty">
            <span className="feed-detail__empty-text">Select a post to view details</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default FeedView

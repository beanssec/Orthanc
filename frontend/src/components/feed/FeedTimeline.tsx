import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useFeedStore } from '../../stores/feedStore'
import type { Post, FeedFilters } from '../../stores/feedStore'
import api from '../../services/api'
import FeedItem from './FeedItem'

interface PaginatedFeedResponse {
  items: Post[]
  total: number
  page: number
  page_size: number
}

interface FeedTimelineProps {
  selectedPost: Post | null
  onSelectPost: (post: Post) => void
  newPostIds: Set<string>
}

/** Build query params from filters, omitting null/empty values */
function buildFeedParams(filters: FeedFilters, page: number, page_size = 50): Record<string, unknown> {
  const params: Record<string, unknown> = { page, page_size }

  if (filters.source_types.length > 0) params.source_types = filters.source_types
  if (filters.keyword) params.keyword = filters.keyword
  if (filters.date_from) params.date_from = filters.date_from
  if (filters.date_to) params.date_to = filters.date_to
  if (filters.author) params.author = filters.author
  if (filters.has_media !== null) params.has_media = filters.has_media
  if (filters.media_type) params.media_type = filters.media_type
  if (filters.has_geo !== null) params.has_geo = filters.has_geo
  if (filters.location) params.location = filters.location
  if (filters.entity) params.entity = filters.entity
  if (filters.min_authenticity !== null) params.min_authenticity = filters.min_authenticity
  if (filters.max_authenticity !== null) params.max_authenticity = filters.max_authenticity
  if (filters.sort) params.sort = filters.sort

  return params
}

const FeedTimeline: React.FC<FeedTimelineProps> = ({ selectedPost, onSelectPost, newPostIds }) => {
  const posts      = useFeedStore((s) => s.posts)
  const filters    = useFeedStore((s) => s.filters)
  const totalCount = useFeedStore((s) => s.totalCount)
  const setPosts   = useFeedStore((s) => s.setPosts)
  const addPost    = useFeedStore((s) => s.addPost)
  const setTotalCount = useFeedStore((s) => s.setTotalCount)

  const [page, setPage]             = useState(1)
  const [loading, setLoading]       = useState(false)
  const [hasMore, setHasMore]       = useState(true)
  const [pendingCount, setPendingCount] = useState(0)
  const [isScrolledDown, setIsScrolledDown] = useState(false)

  const scrollRef   = useRef<HTMLDivElement>(null)
  const bottomRef   = useRef<HTMLDivElement>(null)
  const prevLenRef  = useRef(0)
  const filtersRef  = useRef(filters)

  // Keep filtersRef in sync
  useEffect(() => {
    filtersRef.current = filters
  }, [filters])

  // ------------------------------------------------------------------
  // Fetch page 1 whenever filters change (debounced 300ms)
  // ------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false

    const timer = setTimeout(async () => {
      setLoading(true)
      setPendingCount(0)
      try {
        const params = buildFeedParams(filters, 1)
        const res = await api.get<PaginatedFeedResponse>('/feed/', { params })
        if (!cancelled) {
          setPosts(res.data.items)
          setTotalCount(res.data.total)
          setPage(2)
          setHasMore(res.data.items.length === 50)
          prevLenRef.current = res.data.items.length
          // scroll back to top
          scrollRef.current?.scrollTo({ top: 0 })
          setIsScrolledDown(false)
        }
      } catch (_) {
        // silently ignore — auth/network errors handled upstream
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 300)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)])

  // ------------------------------------------------------------------
  // Detect new posts arriving (from WebSocket via addPost in feedStore)
  // Client-side check: only show if it matches current source_types filter
  // ------------------------------------------------------------------
  useEffect(() => {
    const currentLen = posts.length
    if (currentLen > prevLenRef.current) {
      const delta = currentLen - prevLenRef.current
      prevLenRef.current = currentLen
      if (isScrolledDown) {
        setPendingCount((c) => c + delta)
      } else {
        scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
      }
    }
  }, [posts.length, isScrolledDown])

  // ------------------------------------------------------------------
  // Scroll tracking
  // ------------------------------------------------------------------
  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    setIsScrolledDown(el.scrollTop > 120)
  }, [])

  // ------------------------------------------------------------------
  // Infinite scroll
  // ------------------------------------------------------------------
  useEffect(() => {
    if (!bottomRef.current) return
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading) {
          loadMore()
        }
      },
      { root: scrollRef.current, rootMargin: '100px' }
    )
    obs.observe(bottomRef.current)
    return () => obs.disconnect()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMore, loading, page])

  const loadMore = async () => {
    if (loading || !hasMore) return
    setLoading(true)
    try {
      const params = buildFeedParams(filtersRef.current, page)
      const res = await api.get<PaginatedFeedResponse>('/feed/', { params })
      if (res.data.items.length === 0) {
        setHasMore(false)
      } else {
        res.data.items.forEach((p) => addPost(p))
        setPage((prev) => prev + 1)
        setHasMore(res.data.items.length === 50)
        prevLenRef.current += res.data.items.length
      }
    } catch (_) {
      // silent
    } finally {
      setLoading(false)
    }
  }

  const handleBannerClick = () => {
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    setPendingCount(0)
    setIsScrolledDown(false)
  }

  // Client-side WS post filter: only show if it passes source_types check
  const wsFilteredPosts = posts.filter((p) => {
    const f = filters
    if (f.source_types.length > 0 && !f.source_types.includes(p.source_type)) return false
    return true
  })

  const startPost = (page - 2) * 50 + 1
  const endPost   = Math.min(startPost + posts.length - 1, totalCount)

  return (
    <div className="feed-timeline__scroll" ref={scrollRef} onScroll={handleScroll}>
      {/* Total count header */}
      {totalCount > 0 && (
        <div className="feed-timeline__total-bar">
          Showing {posts.length > 0 ? `1–${posts.length}` : '0'} of {totalCount.toLocaleString()} posts
        </div>
      )}

      {/* New posts banner */}
      {pendingCount > 0 && (
        <div className="new-posts-banner" onClick={handleBannerClick}>
          ↑ {pendingCount} new post{pendingCount !== 1 ? 's' : ''}
        </div>
      )}

      {/* Posts list */}
      {wsFilteredPosts.length === 0 && !loading ? (
        <div className="feed-timeline__empty">
          <span className="feed-timeline__empty-icon">🔍</span>
          <span>No posts match current filters</span>
        </div>
      ) : (
        wsFilteredPosts.map((post) => (
          <FeedItem
            key={post.id}
            post={post}
            isSelected={selectedPost?.id === post.id}
            isNew={newPostIds.has(post.id)}
            keyword={filters.keyword || undefined}
            onClick={onSelectPost}
          />
        ))
      )}

      {/* Infinite scroll sentinel */}
      <div ref={bottomRef} className="feed-sentinel">
        {loading && <div className="feed-loading">Loading more…</div>}
      </div>
    </div>
  )
}

export default FeedTimeline

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useFeedStore } from '../../stores/feedStore'
import type { Post } from '../../stores/feedStore'
import api from '../../services/api'
import FeedItem from './FeedItem'

interface FeedTimelineProps {
  selectedPost: Post | null
  onSelectPost: (post: Post) => void
  newPostIds: Set<string>
}

const FeedTimeline: React.FC<FeedTimelineProps> = ({ selectedPost, onSelectPost, newPostIds }) => {
  const posts      = useFeedStore((s) => s.posts)
  const filters    = useFeedStore((s) => s.filters)
  const setPosts   = useFeedStore((s) => s.setPosts)
  const addPost    = useFeedStore((s) => s.addPost)

  const [page, setPage]             = useState(1)
  const [loading, setLoading]       = useState(false)
  const [hasMore, setHasMore]       = useState(true)
  const [pendingCount, setPendingCount] = useState(0)
  const [isScrolledDown, setIsScrolledDown] = useState(false)

  const scrollRef   = useRef<HTMLDivElement>(null)
  const bottomRef   = useRef<HTMLDivElement>(null)
  const prevLenRef  = useRef(0)

  // ------------------------------------------------------------------
  // Initial load
  // ------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const res = await api.get<Post[]>('/feed/', { params: { page: 1, page_size: 50 } })
        if (!cancelled) {
          setPosts(res.data)
          setPage(2)
          setHasMore(res.data.length === 50)
          prevLenRef.current = res.data.length
        }
      } catch (_) {
        // silently ignore — auth/network errors handled upstream
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [setPosts])

  // ------------------------------------------------------------------
  // Detect new posts arriving (from WebSocket via addPost in feedStore)
  // ------------------------------------------------------------------
  useEffect(() => {
    const currentLen = posts.length
    if (currentLen > prevLenRef.current) {
      const delta = currentLen - prevLenRef.current
      prevLenRef.current = currentLen
      if (isScrolledDown) {
        setPendingCount((c) => c + delta)
      } else {
        // auto-scroll to top
        scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
      }
    }
  }, [posts.length, isScrolledDown])

  // ------------------------------------------------------------------
  // Scroll tracking: detect if user has scrolled away from top
  // ------------------------------------------------------------------
  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    setIsScrolledDown(el.scrollTop > 120)
  }, [])

  // ------------------------------------------------------------------
  // Infinite scroll: intersect observer on sentinel at bottom
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
      const res = await api.get<Post[]>('/feed/', { params: { page, page_size: 50 } })
      if (res.data.length === 0) {
        setHasMore(false)
      } else {
        res.data.forEach((p) => addPost(p))
        setPage((prev) => prev + 1)
        setHasMore(res.data.length === 50)
        prevLenRef.current += res.data.length
      }
    } catch (_) {
      // silent
    } finally {
      setLoading(false)
    }
  }

  // ------------------------------------------------------------------
  // Filter posts
  // ------------------------------------------------------------------
  const filteredPosts = posts.filter((p) => {
    if (filters.source_types.length > 0 && !filters.source_types.includes(p.source_type)) {
      return false
    }
    if (filters.keyword) {
      const kw = filters.keyword.toLowerCase()
      if (!(p.content ?? '').toLowerCase().includes(kw) &&
          !(p.author ?? '').toLowerCase().includes(kw)) {
        return false
      }
    }
    if (filters.date_from) {
      if (new Date(p.timestamp) < new Date(filters.date_from)) return false
    }
    if (filters.date_to) {
      if (new Date(p.timestamp) > new Date(filters.date_to)) return false
    }
    return true
  })

  const handleBannerClick = () => {
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    setPendingCount(0)
    setIsScrolledDown(false)
  }

  return (
    <div className="feed-timeline__scroll" ref={scrollRef} onScroll={handleScroll}>
      {/* New posts banner */}
      {pendingCount > 0 && (
        <div className="new-posts-banner" onClick={handleBannerClick}>
          ↑ {pendingCount} new post{pendingCount !== 1 ? 's' : ''}
        </div>
      )}

      {/* Posts list */}
      {filteredPosts.length === 0 && !loading ? (
        <div className="feed-timeline__empty">
          <span className="feed-timeline__empty-icon">🔍</span>
          <span>No posts match current filters</span>
        </div>
      ) : (
        filteredPosts.map((post) => (
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
      <div ref={bottomRef} />

      {loading && (
        <div className="feed-timeline__loader">
          <span>Loading…</span>
        </div>
      )}
    </div>
  )
}

export default FeedTimeline

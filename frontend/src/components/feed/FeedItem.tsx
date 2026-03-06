import React, { useEffect, useRef, useState, useCallback } from 'react'
import type { Post } from '../../stores/feedStore'
import api from '../../services/api'
import { AuthImage } from '../common/AuthMedia'

/** Derive authenticity badge props from score. */
function getAuthenticityBadge(
  mediaType: Post['media_type'],
  score: number | null,
  checkedAt: string | null
): { label: string; className: string } | null {
  if (!mediaType) return null
  if (mediaType === 'video') return null  // No badge for video in MVP
  if (score === null && !checkedAt) {
    return { label: '🔍 Requires xAI or OpenRouter key for analysis', className: 'authenticity-badge authenticity-badge--pending' }
  }
  if (score === null && checkedAt) {
    return { label: '⚠️ Analysis unavailable', className: 'authenticity-badge authenticity-badge--pending' }
  }
  if (score === null) return null
  if (score >= 0.7) return { label: '🟢 Likely Authentic', className: 'authenticity-badge authenticity-badge--real' }
  if (score >= 0.4) return { label: '🟡 Uncertain', className: 'authenticity-badge authenticity-badge--uncertain' }
  return { label: '🔴 Possibly AI-Generated', className: 'authenticity-badge authenticity-badge--ai' }
}

interface FeedItemProps {
  post: Post
  isSelected: boolean
  isNew?: boolean
  keyword?: string
  onClick: (post: Post) => void
}

/** Returns a relative time string: "2m ago", "1h ago", "3d ago", etc. */
export function relativeTime(isoString: string): string {
  const now = Date.now()
  const then = new Date(isoString).getTime()
  const diffMs = now - then
  const diffSec = Math.floor(diffMs / 1000)

  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30) return `${diffDay}d ago`
  const diffMo = Math.floor(diffDay / 30)
  if (diffMo < 12) return `${diffMo}mo ago`
  return `${Math.floor(diffMo / 12)}y ago`
}

const SOURCE_LABELS: Record<string, string> = {
  telegram: 'TG',
  x: 'X',
  rss: 'RSS',
  reddit: 'Reddit',
  discord: 'Discord',
  shodan: 'Shodan',
  webhook: 'Hook',
  firms: 'FIRMS',
  flight: 'Flight',
  ais: 'AIS',
  cashtag: '$TAG',
  document: '📄 Doc',
}

/** Decodes HTML entities like &#039; &amp; &lt; &gt; into their real characters. */
function decodeHtmlEntities(text: string): string {
  const textarea = document.createElement('textarea')
  textarea.innerHTML = text
  return textarea.value
}

/** Cleans up verbose RSS feed names: strips subtitle after " – ", " — ", " - ", " | ". */
function cleanAuthor(author: string | null, sourceType: string): string {
  if (!author) return ''
  if (sourceType === 'rss') {
    const cleaned = author.split(/\s[–—\-|]\s/)[0].trim()
    return cleaned || author
  }
  return author
}

/** Splits text around keyword matches and returns segments for highlighting. */
function highlightContent(text: string, keyword: string): React.ReactNode[] {
  if (!keyword.trim()) return [text]
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return parts.map((part, i) =>
    part.toLowerCase() === keyword.toLowerCase() ? (
      <mark key={i} className="feed-item__highlight">{part}</mark>
    ) : (
      part
    )
  )
}

const FeedItem: React.FC<FeedItemProps> = ({ post, isSelected, isNew, keyword, onClick }) => {
  const [flashClass, setFlashClass] = useState(isNew ? 'feed-item--new' : '')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Inline translation state
  const [translating, setTranslating] = useState(false)
  const [translatedPreview, setTranslatedPreview] = useState<string | null>(null)

  useEffect(() => {
    if (isNew) {
      setFlashClass('feed-item--new')
      timerRef.current = setTimeout(() => setFlashClass(''), 700)
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [isNew])

  // Reset translation when post changes
  useEffect(() => {
    setTranslatedPreview(null)
  }, [post.id])

  const handleTranslateClick = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation()
    // Toggle off
    if (translatedPreview) {
      setTranslatedPreview(null)
      return
    }
    if (translating) return
    setTranslating(true)
    try {
      const text = post.content || ''
      const res = await api.post('/translate', { text, target_lang: 'en' })
      const data = res.data as { translated?: string | null; no_translation_needed?: boolean }
      if (data.no_translation_needed || !data.translated) {
        setTranslatedPreview(null)
      } else {
        // Show only first 200 chars in the item preview
        const t = data.translated
        setTranslatedPreview(t.slice(0, 200) + (t.length > 200 ? '…' : ''))
      }
    } catch {
      // silently fail for inline translate
    } finally {
      setTranslating(false)
    }
  }, [post.content, translating, translatedPreview])

  const rawPreview = post.content ? decodeHtmlEntities(post.content.slice(0, 200)) : ''
  const truncated = post.content && post.content.length > 200
  const displayPreview = translatedPreview ?? rawPreview

  const classes = [
    'feed-item',
    isSelected ? 'feed-item--selected' : '',
    flashClass,
  ].filter(Boolean).join(' ')

  return (
    <div
      className={classes}
      onClick={() => onClick(post)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onClick(post) }}
    >
      <div className={`feed-item__source-bar feed-item__source-bar--${post.source_type}`} />
      <div className="feed-item__body">
        <div className="feed-item__top-row">
          <span className={`feed-item__badge feed-item__badge--${post.source_type}`}>
            {SOURCE_LABELS[post.source_type]}
          </span>
          <span className="feed-item__author">
            {cleanAuthor(post.author, post.source_type)
              ? decodeHtmlEntities(cleanAuthor(post.author, post.source_type))
              : <span style={{ fontStyle: 'italic', opacity: 0.5 }}>unknown</span>}
          </span>
          <span className="feed-item__time">{relativeTime(post.timestamp)}</span>
          <button
            className={`feed-item__translate-icon${translatedPreview ? ' feed-item__translate-icon--active' : ''}`}
            onClick={handleTranslateClick}
            title={translatedPreview ? 'Show original' : 'Translate to English'}
            disabled={translating}
          >
            {translating ? '…' : '🌐'}
          </button>
        </div>

        {displayPreview && (
          <div className={`feed-item__content${translatedPreview ? ' feed-item__content--translated' : ''}`}>
            {keyword && !translatedPreview
              ? highlightContent(displayPreview + (truncated ? '…' : ''), keyword)
              : displayPreview + (!translatedPreview && truncated ? '…' : '')}
          </div>
        )}

        {/* Media thumbnail + authenticity badge */}
        {post.media_type && (
          <div className="feed-item__media">
            {post.media_thumbnail_path ? (
              <AuthImage
                postId={post.id}
                thumb={true}
                className="media-thumbnail"
                alt="Media thumbnail"
                onClick={(e) => { e.stopPropagation(); onClick(post) }}
              />
            ) : post.media_type === 'video' ? (
              <span className="feed-item__media-icon" title="Video attached">🎥</span>
            ) : (
              <span className="feed-item__media-icon" title="Image attached">🖼️</span>
            )}
            {(() => {
              const badge = getAuthenticityBadge(
                post.media_type,
                post.authenticity_score ?? null,
                post.authenticity_checked_at ?? null
              )
              return badge ? (
                <span className={badge.className}>{badge.label}</span>
              ) : null
            })()}
          </div>
        )}

        {post.event && (
          <div className="feed-item__location">
            📍{' '}
            <span>{post.event.place_name || `${post.event.lat.toFixed(4)}, ${post.event.lng.toFixed(4)}`}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export default FeedItem

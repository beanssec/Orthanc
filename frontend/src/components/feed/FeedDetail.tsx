import React, { useState, useCallback, useEffect } from 'react'
import type { Post } from '../../stores/feedStore'
import api from '../../services/api'
import '../../styles/collaboration.css'
import { AuthImage, AuthVideo } from '../common/AuthMedia'
import { AddToCase } from '../cases/AddToCase'

// ── Media Analysis Panel ──────────────────────────────────
interface MediaAnalysisResult {
  score?: number
  verdict?: string
  confidence?: string
  reasoning?: string
  indicators?: Record<string, boolean>
}

function AuthenticityBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score >= 0.7 ? 'var(--success, #4caf50)' : score >= 0.4 ? '#f0a500' : 'var(--danger, #e53935)'
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>
        <span>AI-Generated</span>
        <span style={{ color, fontWeight: 700 }}>{pct}% authentic</span>
        <span>Authentic</span>
      </div>
      <div style={{ background: 'var(--bg-tertiary, #1a1a2e)', borderRadius: 4, height: 8, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.4s' }} />
      </div>
    </div>
  )
}

function MediaAnalysisPanel({ post }: { post: Post }) {
  const [open, setOpen] = useState(false)
  if (!post.media_type) return null

  const analysis: MediaAnalysisResult | null = (() => {
    if (!post.authenticity_analysis) return null
    try { return JSON.parse(post.authenticity_analysis) } catch { return null }
  })()

  const meta = post.media_metadata as Record<string, unknown> | null
  const exif = meta?.exif as Record<string, string> | null | undefined

  const verdictLabel: Record<string, string> = {
    likely_real: '🟢 Likely Real',
    uncertain: '🟡 Uncertain',
    likely_ai: '🔴 Likely AI-Generated',
    confirmed_ai: '🔴 Confirmed AI-Generated',
  }

  return (
    <div className="media-analysis">
      <button
        className="media-analysis__toggle"
        onClick={() => setOpen(v => !v)}
      >
        <span className={`feed-detail__json-toggle-icon${open ? ' feed-detail__json-toggle-icon--open' : ''}`}>▶</span>
        📋 Media Analysis
        {post.authenticity_score !== null && post.authenticity_score !== undefined && (
          <span style={{
            marginLeft: 8, fontSize: 11, fontWeight: 600,
            color: post.authenticity_score >= 0.7 ? 'var(--success, #4caf50)' : post.authenticity_score >= 0.4 ? '#f0a500' : 'var(--danger, #e53935)'
          }}>
            {Math.round(post.authenticity_score * 100)}% authentic
          </span>
        )}
      </button>

      {open && (
        <div className="media-analysis__body">
          {/* Full media display */}
          {post.media_type === 'image' && post.media_path && (
            <div style={{ marginBottom: 12, textAlign: 'center' }}>
              <AuthImage
                postId={post.id}
                thumb={false}
                alt="Full media"
                style={{ maxWidth: '100%', maxHeight: 400, borderRadius: 6, border: '1px solid var(--border)' }}
              />
            </div>
          )}
          {post.media_type === 'video' && post.media_path && (
            <div style={{ marginBottom: 12 }}>
              <AuthVideo postId={post.id} mime={post.media_mime || 'video/mp4'} />
            </div>
          )}

          {/* Authenticity score */}
          {post.authenticity_score !== null && post.authenticity_score !== undefined && (
            <AuthenticityBar score={post.authenticity_score} />
          )}

          {/* Verdict + reasoning */}
          {analysis && (
            <div style={{ marginBottom: 10 }}>
              {analysis.verdict && (
                <div style={{ marginBottom: 4 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Verdict: </span>
                  <span style={{ fontWeight: 600, fontSize: 12 }}>
                    {verdictLabel[analysis.verdict] ?? analysis.verdict}
                  </span>
                  {analysis.confidence && (
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>
                      ({analysis.confidence} confidence)
                    </span>
                  )}
                </div>
              )}
              {analysis.reasoning && (
                <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, background: 'var(--bg-tertiary, #1a1a2e)', padding: '8px 10px', borderRadius: 4 }}>
                  {analysis.reasoning}
                </div>
              )}
              {/* Indicators */}
              {analysis.indicators && Object.keys(analysis.indicators).length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>Indicators</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {Object.entries(analysis.indicators).map(([key, val]) => (
                      <span
                        key={key}
                        style={{
                          fontSize: 10,
                          padding: '2px 6px',
                          borderRadius: 10,
                          background: val ? 'rgba(229,57,53,0.18)' : 'rgba(76,175,80,0.12)',
                          color: val ? 'var(--danger, #e53935)' : 'var(--success, #4caf50)',
                          border: `1px solid ${val ? 'rgba(229,57,53,0.3)' : 'rgba(76,175,80,0.25)'}`,
                        }}
                      >
                        {val ? '⚠ ' : '✓ '}{key.replace(/_/g, ' ')}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {post.authenticity_score === null && !post.authenticity_checked_at && post.media_type === 'image' && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 8 }}>
              ⏳ Authenticity analysis pending…
            </div>
          )}

          {/* File metadata */}
          {meta && (
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>File Info</div>

              {meta['ai_software_detected'] && (
                <div style={{ padding: '6px 10px', background: 'rgba(229,57,53,0.12)', border: '1px solid rgba(229,57,53,0.3)', borderRadius: 4, fontSize: 12, color: 'var(--danger, #e53935)', marginBottom: 8 }}>
                  ⚠ AI software detected in EXIF: <strong>{String(meta['ai_software_name'] ?? 'unknown')}</strong>
                </div>
              )}
              {meta['exif_stripped'] && (
                <div style={{ padding: '6px 10px', background: 'rgba(240,165,0,0.1)', border: '1px solid rgba(240,165,0,0.3)', borderRadius: 4, fontSize: 12, color: '#f0a500', marginBottom: 8 }}>
                  ⚠ EXIF data stripped — common with manipulated images
                </div>
              )}

              <table className="exif-table">
                <tbody>
                  {meta['sha256'] && (
                    <tr><td>SHA-256</td><td className="mono" style={{ fontSize: 9, wordBreak: 'break-all' }}>{String(meta['sha256'])}</td></tr>
                  )}
                  {post.media_size_bytes && (
                    <tr><td>File Size</td><td>{(post.media_size_bytes / 1024).toFixed(1)} KB</td></tr>
                  )}
                  {meta['width'] && meta['height'] && (
                    <tr><td>Dimensions</td><td>{String(meta['width'])} × {String(meta['height'])} px</td></tr>
                  )}
                  {meta['format'] && (
                    <tr><td>Format</td><td>{String(meta['format'])}</td></tr>
                  )}
                  {meta['duration_seconds'] && (
                    <tr><td>Duration</td><td>{Number(meta['duration_seconds']).toFixed(1)}s</td></tr>
                  )}
                  {meta['video_codec'] && (
                    <tr><td>Video Codec</td><td>{String(meta['video_codec'])}</td></tr>
                  )}
                </tbody>
              </table>

              {/* EXIF table */}
              {exif && Object.keys(exif).length > 0 && (
                <>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 10, marginBottom: 4 }}>EXIF Data</div>
                  <table className="exif-table">
                    <tbody>
                      {Object.entries(exif).map(([k, v]) => (
                        <tr key={k}>
                          <td>{k.replace(/_/g, ' ')}</td>
                          <td>{String(v)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

interface FeedDetailProps {
  post: Post | null
}

/** Decodes HTML entities like &#039; &amp; &lt; &gt; into their real characters. */
function decodeHtmlEntities(text: string): string {
  const textarea = document.createElement('textarea')
  textarea.innerHTML = text
  return textarea.value
}

/** Formats an ISO datetime to "Mar 4, 2026 09:15:32 UTC" */
function formatTimestamp(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'UTC',
    hour12: false,
  }).replace(',', '') + ' UTC'
}

const SOURCE_LABELS: Record<string, string> = {
  telegram: 'TELEGRAM',
  x: 'X / TWITTER',
  rss: 'RSS',
  reddit: 'REDDIT',
  discord: 'DISCORD',
  shodan: 'SHODAN',
  webhook: 'WEBHOOK',
  firms: 'FIRMS',
  flight: 'FLIGHTS',
  ais: 'SHIPS / AIS',
  cashtag: 'CASHTAG',
  document: '📄 DOCUMENT',
}

const LANG_NAMES: Record<string, string> = {
  ru: 'Russian',
  ar: 'Arabic',
  fa: 'Farsi',
  zh: 'Chinese',
  ko: 'Korean',
  he: 'Hebrew',
  uk: 'Ukrainian',
  en: 'English',
}

interface TranslationState {
  translating: boolean
  translated: string | null
  sourceLang: string | null
  error: string | null
}

// ── Post Bookmark Button ──────────────────────────────────
function PostBookmarkButton({ postId }: { postId: string }) {
  const [bookmarked, setBookmarked] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/bookmarks/check/post/${postId}`)
      .then(res => setBookmarked((res.data as { bookmarked: boolean }).bookmarked))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [postId])

  const toggle = async () => {
    const prev = bookmarked
    setBookmarked(!prev)
    try {
      if (prev) await api.delete(`/bookmarks/post/${postId}`)
      else await api.post(`/bookmarks/post/${postId}`)
    } catch { setBookmarked(prev) }
  }

  if (loading) return null
  return (
    <button
      className={`bookmark-btn${bookmarked ? ' bookmark-btn--active' : ''}`}
      onClick={toggle}
      title={bookmarked ? 'Remove bookmark' : 'Bookmark this post'}
      style={{ fontSize: 11, padding: '3px 8px' }}
    >
      <span className="bookmark-star">{bookmarked ? '★' : '☆'}</span>
      {bookmarked ? 'Saved' : 'Save'}
    </button>
  )
}

// ── Post Tags ─────────────────────────────────────────────
function PostTagsSection({ postId }: { postId: string }) {
  interface Tag { id: string; tag: string; target_type: string; target_id: string }
  const [tags, setTags] = useState<Tag[]>([])
  const [newTag, setNewTag] = useState('')

  useEffect(() => {
    api.get(`/tags/post/${postId}`)
      .then(res => setTags(res.data as Tag[]))
      .catch(() => {})
  }, [postId])

  const addTag = async (tag: string) => {
    const trimmed = tag.trim().toLowerCase()
    if (!trimmed) return
    try {
      const res = await api.post(`/tags/post/${postId}`, { tag: trimmed })
      setTags(prev => [...prev, res.data as Tag])
      setNewTag('')
    } catch { /* ignore */ }
  }

  const removeTag = async (tagValue: string) => {
    try {
      await api.delete(`/tags/post/${postId}/${encodeURIComponent(tagValue)}`)
      setTags(prev => prev.filter(t => t.tag !== tagValue))
    } catch { /* ignore */ }
  }

  return (
    <div className="tag-pills">
      {tags.map(t => (
        <span key={t.id} className="tag-pill">
          {t.tag}
          <button className="tag-pill__remove" onClick={() => removeTag(t.tag)}>×</button>
        </span>
      ))}
      <input
        className="tag-add-input"
        placeholder="+ tag"
        value={newTag}
        onChange={e => setNewTag(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') addTag(newTag) }}
      />
    </div>
  )
}

// ── Post Notes Section ────────────────────────────────────
function PostNotesSection({ postId }: { postId: string }) {
  interface Note { id: string; user_id: string; content: string; created_at: string; updated_at: string }
  const [notes, setNotes] = useState<Note[]>([])
  const [loading, setLoading] = useState(true)
  const [newNote, setNewNote] = useState('')
  const [submitting, setSubmitting] = useState(false)

  function formatDT(ts: string) {
    return new Date(ts).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  }

  useEffect(() => {
    api.get(`/notes/post/${postId}`)
      .then(res => setNotes(res.data as Note[]))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [postId])

  const submit = async () => {
    if (!newNote.trim()) return
    setSubmitting(true)
    try {
      const res = await api.post(`/notes/post/${postId}`, { content: newNote.trim() })
      setNotes(prev => [res.data as Note, ...prev])
      setNewNote('')
    } catch { /* ignore */ }
    finally { setSubmitting(false) }
  }

  const deleteNote = async (id: string) => {
    try {
      await api.delete(`/notes/${id}`)
      setNotes(prev => prev.filter(n => n.id !== id))
    } catch { /* ignore */ }
  }

  return (
    <div className="collab-notes">
      {loading ? null : notes.map(n => (
        <div key={n.id} className="note-card">
          <div className="note-card__header">
            <span className="note-card__timestamp">{formatDT(n.created_at)}</span>
            <div className="note-card__actions">
              <button className="note-card__action-btn note-card__action-btn--danger" onClick={() => deleteNote(n.id)}>Delete</button>
            </div>
          </div>
          <div className="note-card__content">{n.content}</div>
        </div>
      ))}
      <div className="note-add-form">
        <textarea
          placeholder="Add a note…"
          value={newNote}
          onChange={e => setNewNote(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) submit() }}
        />
        <div className="note-add-form__actions">
          <button className="btn btn-primary btn-sm" disabled={!newNote.trim() || submitting} onClick={submit}>
            {submitting ? 'Adding…' : '+ Add Note'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────
const FeedDetail: React.FC<FeedDetailProps> = ({ post }) => {
  const [jsonOpen, setJsonOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showNotes, setShowNotes] = useState(false)

  // Translation state per post — keyed by post.id
  const [translations, setTranslations] = useState<Record<string, TranslationState>>({})
  const [showTranslation, setShowTranslation] = useState<Record<string, boolean>>({})

  const handleCopy = useCallback(() => {
    if (!post?.content) return
    navigator.clipboard.writeText(post.content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }, [post])

  const handleTranslate = useCallback(async () => {
    if (!post) return
    const id = post.id

    // Toggle off if already shown
    if (showTranslation[id] && translations[id]?.translated) {
      setShowTranslation((prev) => ({ ...prev, [id]: false }))
      return
    }

    // Show existing translation if cached
    if (translations[id]?.translated) {
      setShowTranslation((prev) => ({ ...prev, [id]: true }))
      return
    }

    // Start translating
    setTranslations((prev) => ({
      ...prev,
      [id]: { translating: true, translated: null, sourceLang: null, error: null },
    }))
    setShowTranslation((prev) => ({ ...prev, [id]: true }))

    try {
      const content = post.content || ''
      const res = await api.post('/translate', { text: content, target_lang: 'en' })
      const data = res.data as {
        translated: string | null
        source_lang: string
        error?: string
        no_translation_needed?: boolean
      }

      if (data.error) {
        setTranslations((prev) => ({
          ...prev,
          [id]: { translating: false, translated: null, sourceLang: data.source_lang, error: data.error! },
        }))
      } else if (data.no_translation_needed) {
        setTranslations((prev) => ({
          ...prev,
          [id]: {
            translating: false,
            translated: null,
            sourceLang: 'en',
            error: 'Text appears to already be in English.',
          },
        }))
      } else {
        setTranslations((prev) => ({
          ...prev,
          [id]: {
            translating: false,
            translated: data.translated,
            sourceLang: data.source_lang,
            error: null,
          },
        }))
      }
    } catch {
      setTranslations((prev) => ({
        ...prev,
        [id]: { translating: false, translated: null, sourceLang: null, error: 'Translation request failed.' },
      }))
    }
  }, [post, showTranslation, translations])

  if (!post) {
    return (
      <div className="feed-detail">
        <div className="feed-detail__empty">
          <span className="feed-detail__empty-icon">📋</span>
          <span>Select a post to view details</span>
        </div>
      </div>
    )
  }

  const confidencePct = post.event
    ? Math.round(post.event.confidence * 100)
    : 0

  const tlState = translations[post.id]
  const isTranslationVisible = showTranslation[post.id]
  const isTranslating = tlState?.translating ?? false
  const hasTranslation = !!(tlState?.translated)
  const showingTranslation = isTranslationVisible && (hasTranslation || tlState?.error)

  const translateBtnLabel = isTranslating
    ? '🌐 Translating…'
    : showingTranslation && hasTranslation
    ? '🌐 Hide Translation'
    : '🌐 Translate'

  return (
    <div className="feed-detail">
      {/* Header */}
      <div className="feed-detail__header">
        <span className={`feed-detail__header-badge feed-detail__header-badge--${post.source_type}`}>
          {SOURCE_LABELS[post.source_type]}
        </span>
        <button
          className="feed-detail__translate-btn"
          onClick={handleTranslate}
          disabled={isTranslating}
          title="Translate to English"
        >
          {translateBtnLabel}
        </button>
        <button
          className={`feed-detail__copy-btn${copied ? ' feed-detail__copy-btn--copied' : ''}`}
          onClick={handleCopy}
          title="Copy content to clipboard"
        >
          {copied ? '✓ Copied' : '⎘ Copy'}
        </button>
        <PostBookmarkButton postId={post.id} />
        <AddToCase
          itemType="post"
          itemId={post.id}
          title={post.author ? `${post.author}: ${(post.content || '').substring(0, 80)}` : (post.content || '').substring(0, 80)}
          content={(post.content || '').substring(0, 500)}
          lat={post.event?.lat}
          lng={post.event?.lng}
        />
      </div>

      {/* Full content */}
      <div className="feed-detail__content">
        {post.content
          ? decodeHtmlEntities(post.content)
          : <span style={{ opacity: 0.4, fontStyle: 'italic' }}>No content</span>}

        {/* Translation block */}
        {isTranslationVisible && (
          <>
            {isTranslating && (
              <div className="feed-detail__translation feed-detail__translation--loading">
                <span className="spinner spinner-sm" /> Translating…
              </div>
            )}
            {!isTranslating && tlState?.error && (
              <div className="feed-detail__translation feed-detail__translation--error">
                <div className="feed-detail__translation-label">Translation unavailable</div>
                <div>{tlState.error}</div>
              </div>
            )}
            {!isTranslating && tlState?.translated && (
              <div className="feed-detail__translation">
                <div className="feed-detail__translation-label">
                  Translated from {LANG_NAMES[tlState.sourceLang ?? ''] ?? tlState.sourceLang ?? 'unknown'}:
                </div>
                <div className="feed-detail__translation-text">
                  {tlState.translated}
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Media analysis panel */}
      <MediaAnalysisPanel post={post} />

      {/* Metadata */}
      <div className="feed-detail__metadata">
        <div className="feed-detail__meta-title">Metadata</div>

        {post.author && (
          <div className="feed-detail__meta-row">
            <span className="feed-detail__meta-key">Author</span>
            <span className="feed-detail__meta-value">{decodeHtmlEntities(post.author)}</span>
          </div>
        )}

        <div className="feed-detail__meta-row">
          <span className="feed-detail__meta-key">Timestamp</span>
          <span className="feed-detail__meta-value feed-detail__meta-value--time">
            {formatTimestamp(post.timestamp)}
          </span>
        </div>

        <div className="feed-detail__meta-row">
          <span className="feed-detail__meta-key">Ingested</span>
          <span className="feed-detail__meta-value feed-detail__meta-value--time">
            {formatTimestamp(post.ingested_at)}
          </span>
        </div>

        <div className="feed-detail__meta-row">
          <span className="feed-detail__meta-key">Source ID</span>
          <span className="feed-detail__meta-value feed-detail__meta-value--mono">
            {post.source_id}
          </span>
        </div>

        <div className="feed-detail__meta-row">
          <span className="feed-detail__meta-key">Post ID</span>
          <span className="feed-detail__meta-value feed-detail__meta-value--mono">
            {post.id}
          </span>
        </div>
      </div>

      {/* Location / Event */}
      {post.event && (
        <div className="feed-detail__location">
          <div className="feed-detail__location-title">📍 Geo Event</div>

          {post.event.place_name && (
            <div className="feed-detail__place">{post.event.place_name}</div>
          )}

          <div className="feed-detail__coords">
            {post.event.lat.toFixed(6)}, {post.event.lng.toFixed(6)}
          </div>

          <div className="feed-detail__confidence">
            <div className="feed-detail__confidence-label">
              <span>Confidence</span>
              <span className="feed-detail__confidence-value">{confidencePct}%</span>
            </div>
            <div className="feed-detail__confidence-bar-bg">
              <div
                className="feed-detail__confidence-bar-fill"
                style={{ width: `${confidencePct}%` }}
              />
            </div>
          </div>

          <a
            className="feed-detail__map-btn"
            href={`/map?lat=${post.event.lat}&lng=${post.event.lng}`}
          >
            🗺 View on Map
          </a>
        </div>
      )}

      {/* Tags */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Tags</div>
        <PostTagsSection postId={post.id} />
      </div>

      {/* Notes */}
      <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Notes</span>
          <button
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: 11, cursor: 'pointer', padding: '1px 6px' }}
            onClick={() => setShowNotes(v => !v)}
          >{showNotes ? '▲ hide' : '▼ show'}</button>
        </div>
        {showNotes && <PostNotesSection postId={post.id} />}
      </div>

      {/* Raw JSON */}
      <div className="feed-detail__json">
        <button
          className="feed-detail__json-toggle"
          onClick={() => setJsonOpen((v) => !v)}
        >
          <span className={`feed-detail__json-toggle-icon${jsonOpen ? ' feed-detail__json-toggle-icon--open' : ''}`}>
            ▶
          </span>
          Raw JSON
        </button>
        {jsonOpen && (
          <div className="feed-detail__json-body">
            <pre className="feed-detail__json-pre">
              {JSON.stringify(post, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  )
}

export default FeedDetail

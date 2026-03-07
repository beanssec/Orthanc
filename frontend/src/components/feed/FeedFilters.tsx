import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useFeedStore } from '../../stores/feedStore'
import type { Post, Facets, FeedFilters as FeedFiltersType } from '../../stores/feedStore'
import api from '../../services/api'

function filtersToOQL(filters: FeedFiltersType): string {
  const terms: string[] = []

  if (filters.source_types.length === 1) {
    terms.push(`source_type=${filters.source_types[0]}`)
  } else if (filters.source_types.length > 1) {
    terms.push(`source_type IN (${filters.source_types.join(', ')})`)
  }

  if (filters.keyword) terms.push(`content="*${filters.keyword}*"`)
  if (filters.author) terms.push(`author="${filters.author}"`)

  // Only add time filter if non-default (not exactly 24h)
  if (filters.date_from) {
    const hrs = Math.round((Date.now() - new Date(filters.date_from).getTime()) / 3600000)
    if (hrs !== 24) terms.push(`| where timestamp > now() - ${hrs}h`)
  }

  return terms.join(' ') || '| head 50'
}

const SOURCE_TYPES: Array<{ key: Post['source_type']; label: string }> = [
  { key: 'rss',      label: 'RSS' },
  { key: 'x',        label: 'X / Twitter' },
  { key: 'telegram', label: 'Telegram' },
  { key: 'reddit',   label: 'Reddit' },
  { key: 'discord',  label: 'Discord' },
  { key: 'shodan',   label: 'Shodan' },
  { key: 'webhook',  label: 'Webhook' },
  { key: 'firms',    label: 'FIRMS' },
  { key: 'flight',   label: 'Flights' },
  { key: 'ais',      label: 'Ships/AIS' },
  { key: 'cashtag',  label: 'Cashtags' },
]

interface FeedFiltersProps {
  counts: Record<string, number>
}

/** Build facets query params from current filters (exclude certain keys) */
function buildFacetParams(filters: ReturnType<typeof useFeedStore.getState>['filters']): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  if (filters.source_types.length > 0) params.source_types = filters.source_types
  if (filters.keyword) params.keyword = filters.keyword
  if (filters.date_from) params.date_from = filters.date_from
  if (filters.date_to) params.date_to = filters.date_to
  if (filters.author) params.author = filters.author
  if (filters.has_media !== null) params.has_media = filters.has_media
  if (filters.has_geo !== null) params.has_geo = filters.has_geo
  if (filters.location) params.location = filters.location
  if (filters.entity) params.entity = filters.entity
  return params
}

const FeedFilters: React.FC<FeedFiltersProps> = () => {
  const navigate   = useNavigate()
  const filters    = useFeedStore((s) => s.filters)
  const setFilters = useFeedStore((s) => s.setFilters)
  const setFacets  = useFeedStore((s) => s.setFacets)
  const facets     = useFeedStore((s) => s.facets)

  // Debounce refs
  const keywordTimer   = useRef<ReturnType<typeof setTimeout> | null>(null)
  const authorTimer    = useRef<ReturnType<typeof setTimeout> | null>(null)
  const locationTimer  = useRef<ReturnType<typeof setTimeout> | null>(null)
  const entityTimer    = useRef<ReturnType<typeof setTimeout> | null>(null)

  const keywordInputRef  = useRef<HTMLInputElement>(null)
  const authorInputRef   = useRef<HTMLInputElement>(null)
  const locationInputRef = useRef<HTMLInputElement>(null)
  const entityInputRef   = useRef<HTMLInputElement>(null)

  // Fetch facets whenever filters change
  const fetchFacets = useCallback(async (currentFilters: typeof filters) => {
    try {
      const params = buildFacetParams(currentFilters)
      const res = await api.get<Facets>('/feed/facets', { params })
      setFacets(res.data)
    } catch (_) {
      // silent
    }
  }, [setFacets])

  useEffect(() => {
    fetchFacets(filters)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(filters)])

  // Sync controlled inputs when filters are cleared externally
  useEffect(() => {
    if (keywordInputRef.current && filters.keyword === '') keywordInputRef.current.value = ''
    if (authorInputRef.current && !filters.author) authorInputRef.current.value = ''
    if (locationInputRef.current && !filters.location) locationInputRef.current.value = ''
    if (entityInputRef.current && !filters.entity) entityInputRef.current.value = ''
  }, [filters.keyword, filters.author, filters.location, filters.entity])

  // ── Event handlers ──────────────────────────────────────────────────────────

  const handleSourceToggle = (type: Post['source_type']) => {
    const current = filters.source_types
    const next = current.includes(type)
      ? current.filter((t) => t !== type)
      : [...current, type]
    setFilters({ source_types: next })
  }

  const handleKeyword = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    if (keywordTimer.current) clearTimeout(keywordTimer.current)
    keywordTimer.current = setTimeout(() => setFilters({ keyword: val }), 300)
  }

  const handleAuthor = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    if (authorTimer.current) clearTimeout(authorTimer.current)
    authorTimer.current = setTimeout(() => setFilters({ author: val || null }), 300)
  }

  const handleLocation = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    if (locationTimer.current) clearTimeout(locationTimer.current)
    locationTimer.current = setTimeout(() => setFilters({ location: val || null }), 300)
  }

  const handleEntity = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    if (entityTimer.current) clearTimeout(entityTimer.current)
    entityTimer.current = setTimeout(() => setFilters({ entity: val || null }), 300)
  }

  const handleMediaType = (type: string) => {
    // Toggle: clicking active media_type clears it
    if (filters.media_type === type) {
      setFilters({ media_type: null, has_media: null })
    } else {
      setFilters({ media_type: type, has_media: true })
    }
  }

  const handleDateFrom = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFilters({ date_from: e.target.value || null })
  }

  const handleDateTo = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFilters({ date_to: e.target.value || null })
  }

  const handleClearAll = () => {
    setFilters({
      source_types: [],
      keyword: '',
      date_from: null,
      date_to: null,
      author: null,
      has_media: null,
      media_type: null,
      has_geo: null,
      location: null,
      entity: null,
      min_authenticity: null,
      max_authenticity: null,
      sort: 'newest',
    })
  }

  const activeCount =
    filters.source_types.length +
    (filters.keyword ? 1 : 0) +
    (filters.date_from ? 1 : 0) +
    (filters.date_to ? 1 : 0) +
    (filters.author ? 1 : 0) +
    (filters.has_media !== null || filters.media_type ? 1 : 0) +
    (filters.has_geo !== null ? 1 : 0) +
    (filters.location ? 1 : 0) +
    (filters.entity ? 1 : 0) +
    (filters.min_authenticity !== null ? 1 : 0) +
    (filters.max_authenticity !== null ? 1 : 0)

  // Source type counts from facets (fall back to 0)
  const getSourceCount = (key: string): number => {
    if (!facets) return 0
    return facets.source_types.find((f) => f.value === key)?.count ?? 0
  }

  // Whether any posts have authenticity scores
  const hasAuthScores = facets !== null && facets.total_posts > 0

  return (
    <div className="feed-filters">

      {/* ── Sources ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Sources</span>
        {SOURCE_TYPES.map(({ key, label }) => {
          const count = getSourceCount(key)
          return (
            <label
              key={key}
              className="feed-filters__source-item"
              style={count === 0 ? { opacity: 0.4 } : undefined}
            >
              <input
                type="checkbox"
                checked={filters.source_types.includes(key)}
                onChange={() => handleSourceToggle(key)}
              />
              <span className={`feed-filters__dot feed-filters__dot--${key}`} />
              <span className="feed-filters__source-label">{label}</span>
              <span className="feed-filters__source-count">{count}</span>
            </label>
          )
        })}
      </div>

      {/* ── Keyword ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Keyword</span>
        <div className="feed-filters__keyword-wrap">
          <input
            ref={keywordInputRef}
            type="text"
            className="input"
            placeholder="Search content…"
            defaultValue={filters.keyword}
            onChange={handleKeyword}
          />
        </div>
      </div>

      {/* ── Time range presets ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Time Range</span>
        <div className="feed-filters__time-presets">
          {[
            { label: '1h',  hours: 1 },
            { label: '6h',  hours: 6 },
            { label: '24h', hours: 24 },
            { label: '48h', hours: 48 },
            { label: '7d',  hours: 168 },
            { label: '30d', hours: 720 },
            { label: 'All', hours: 0 },
          ].map(({ label, hours }) => {
            const isActive = hours === 0
              ? !filters.date_from
              : !!(filters.date_from && Math.abs(Date.now() - new Date(filters.date_from).getTime() - hours * 3600000) < 60000)
            return (
              <button
                key={label}
                className={`feed-filters__time-btn${isActive ? ' feed-filters__time-btn--active' : ''}`}
                onClick={() => setFilters({
                  date_from: hours > 0 ? new Date(Date.now() - hours * 3600000).toISOString() : null,
                  date_to: null,
                })}
              >
                {label}
              </button>
            )
          })}
        </div>
      </div>

      {/* ── Custom date range ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Custom Range</span>
        <div className="feed-filters__date-row">
          <span className="feed-filters__date-label">From</span>
          <input
            type="datetime-local"
            className="feed-filters__date-input"
            value={filters.date_from ? filters.date_from.slice(0, 16) : ''}
            onChange={handleDateFrom}
          />
        </div>
        <div className="feed-filters__date-row" style={{ marginTop: '6px' }}>
          <span className="feed-filters__date-label">To</span>
          <input
            type="datetime-local"
            className="feed-filters__date-input"
            value={filters.date_to ?? ''}
            onChange={handleDateTo}
          />
        </div>
      </div>

      {/* ── Sort ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Sort</span>
        <div className="feed-filters__sort-row">
          {(['newest', 'oldest'] as const).map((s) => (
            <button
              key={s}
              className={`feed-filters__time-btn${filters.sort === s ? ' feed-filters__time-btn--active' : ''}`}
              onClick={() => setFilters({ sort: s })}
            >
              {s === 'newest' ? '↓ Newest' : '↑ Oldest'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Author ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Author</span>
        <div className="feed-filters__keyword-wrap">
          <input
            ref={authorInputRef}
            id="feed-author-input"
            list="feed-author-list"
            type="text"
            className="input"
            placeholder="Filter by author…"
            defaultValue={filters.author ?? ''}
            onChange={handleAuthor}
          />
          <datalist id="feed-author-list">
            {facets?.authors.map((a) => (
              <option key={a.value} value={a.value}>{a.value} ({a.count})</option>
            ))}
          </datalist>
        </div>
      </div>

      {/* ── Media ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Media</span>
        <div className="feed-filters__media-row">
          {[
            { type: 'image',    label: '🖼 Image' },
            { type: 'video',    label: '🎥 Video' },
            { type: 'document', label: '📄 Doc' },
          ].map(({ type, label }) => {
            const count = facets?.media_types.find((m) => m.value === type)?.count ?? 0
            return (
              <label
                key={type}
                className={`feed-filters__media-item${filters.media_type === type ? ' feed-filters__media-item--active' : ''}`}
              >
                <input
                  type="checkbox"
                  checked={filters.media_type === type}
                  onChange={() => handleMediaType(type)}
                />
                <span className="feed-filters__media-label">{label}</span>
                {count > 0 && <span className="feed-filters__source-count">{count}</span>}
              </label>
            )
          })}
        </div>

        {/* Has geo checkbox */}
        <label className="feed-filters__media-item" style={{ marginTop: '6px' }}>
          <input
            type="checkbox"
            checked={filters.has_geo === true}
            onChange={() => setFilters({ has_geo: filters.has_geo === true ? null : true })}
          />
          <span className="feed-filters__media-label">📍 Has Location</span>
          {facets && <span className="feed-filters__source-count">{facets.has_geo_count}</span>}
        </label>
      </div>

      {/* ── Location ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Location</span>
        <div className="feed-filters__keyword-wrap">
          <input
            ref={locationInputRef}
            id="feed-location-input"
            list="feed-location-list"
            type="text"
            className="input"
            placeholder="Place name…"
            defaultValue={filters.location ?? ''}
            onChange={handleLocation}
          />
          <datalist id="feed-location-list">
            {facets?.source_types.map((s) => null) /* placeholder — locations from facets if added later */}
          </datalist>
        </div>
      </div>

      {/* ── Entity ── */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Entity</span>
        <div className="feed-filters__keyword-wrap">
          <input
            ref={entityInputRef}
            id="feed-entity-input"
            list="feed-entity-list"
            type="text"
            className="input"
            placeholder="Entity name…"
            defaultValue={filters.entity ?? ''}
            onChange={handleEntity}
          />
          <datalist id="feed-entity-list" />
        </div>
      </div>

      {/* ── Authenticity ── */}
      {hasAuthScores && (
        <div className="feed-filters__section">
          <span className="feed-filters__section-label">Authenticity</span>
          <div className="feed-filters__auth-row">
            <input
              type="number"
              className="feed-filters__auth-input"
              min={0} max={1} step={0.1}
              placeholder="Min"
              value={filters.min_authenticity ?? ''}
              onChange={(e) => setFilters({ min_authenticity: e.target.value ? parseFloat(e.target.value) : null })}
            />
            <span className="feed-filters__auth-sep">–</span>
            <input
              type="number"
              className="feed-filters__auth-input"
              min={0} max={1} step={0.1}
              placeholder="Max"
              value={filters.max_authenticity ?? ''}
              onChange={(e) => setFilters({ max_authenticity: e.target.value ? parseFloat(e.target.value) : null })}
            />
          </div>
          <span className="feed-filters__auth-hint">0.0 = AI generated · 1.0 = authentic</span>
        </div>
      )}

      {/* ── Footer ── */}
      {activeCount > 0 && (
        <div className="feed-filters__footer">
          <span className="feed-filters__active-badge">{activeCount} active</span>
          <button className="feed-filters__clear-all" onClick={handleClearAll}>
            Clear all
          </button>
        </div>
      )}

      {/* ── Open as Query ── */}
      <div style={{ padding: '0 12px 12px' }}>
        <button
          className="feed-filters__open-as-query"
          onClick={() => {
            const oql = filtersToOQL(filters)
            navigate(`/query?oql=${encodeURIComponent(oql)}`)
          }}
          title="Open current filters as an OQL query"
        >
          ⌨ Open as Query
        </button>
      </div>
    </div>
  )
}

export default FeedFilters

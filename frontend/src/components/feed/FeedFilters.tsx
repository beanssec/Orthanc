import React, { useEffect, useRef } from 'react'
import { useFeedStore } from '../../stores/feedStore'
import type { Post } from '../../stores/feedStore'

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

const FeedFilters: React.FC<FeedFiltersProps> = ({ counts }) => {
  const filters   = useFeedStore((s) => s.filters)
  const setFilters = useFeedStore((s) => s.setFilters)

  // Debounce ref for keyword
  const keywordTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keywordInputRef = useRef<HTMLInputElement>(null)

  // Sync controlled input value when filters are cleared externally
  useEffect(() => {
    if (keywordInputRef.current && filters.keyword === '') {
      keywordInputRef.current.value = ''
    }
  }, [filters.keyword])

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
    keywordTimer.current = setTimeout(() => {
      setFilters({ keyword: val })
    }, 300)
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
    })
  }

  const activeCount =
    filters.source_types.length +
    (filters.keyword ? 1 : 0) +
    (filters.date_from ? 1 : 0) +
    (filters.date_to ? 1 : 0)

  return (
    <div className="feed-filters">
      {/* Source types */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Sources</span>
        {SOURCE_TYPES.map(({ key, label }) => {
          const count = counts[key] ?? 0;
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
          );
        })}
      </div>

      {/* Keyword */}
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

      {/* Time range presets */}
      <div className="feed-filters__section">
        <span className="feed-filters__section-label">Time Range</span>
        <div className="feed-filters__time-presets">
          {[
            { label: '1h', hours: 1 },
            { label: '6h', hours: 6 },
            { label: '24h', hours: 24 },
            { label: '48h', hours: 48 },
            { label: '7d', hours: 168 },
            { label: '30d', hours: 720 },
            { label: 'All', hours: 0 },
          ].map(({ label, hours }) => {
            const isActive = hours === 0
              ? !filters.date_from
              : filters.date_from && Math.abs(Date.now() - new Date(filters.date_from).getTime() - hours * 3600000) < 60000;
            return (
              <button
                key={label}
                className={`feed-filters__time-btn ${isActive ? 'feed-filters__time-btn--active' : ''}`}
                onClick={() => setFilters({
                  date_from: hours > 0 ? new Date(Date.now() - hours * 3600000).toISOString() : null,
                  date_to: null,
                })}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Custom date range */}
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

      {/* Footer */}
      {activeCount > 0 && (
        <div className="feed-filters__footer">
          <span className="feed-filters__active-badge">{activeCount} active</span>
          <button className="feed-filters__clear-all" onClick={handleClearAll}>
            Clear all
          </button>
        </div>
      )}
    </div>
  )
}

export default FeedFilters

import React, { useCallback, useEffect, useRef, useState } from 'react';

export type TimeRange = '1h' | '6h' | '24h' | '48h' | '7d' | '30d' | 'all';

export const SOURCE_TYPES = [
  { id: 'telegram', label: 'Telegram', color: '#3b82f6' },
  { id: 'x', label: 'X / Twitter', color: '#38bdf8' },
  { id: 'rss', label: 'RSS', color: '#10b981' },
  { id: 'shodan', label: 'Shodan', color: '#e11d48' },
];

const TIME_RANGE_OPTIONS: { value: TimeRange; label: string }[] = [
  { value: '1h', label: '1h' },
  { value: '6h', label: '6h' },
  { value: '24h', label: '24h' },
  { value: '48h', label: '48h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: 'all', label: 'All' },
];

export interface SidebarFilters {
  timeRange: TimeRange;
  sourceTypes: string[];
  keyword: string;
  showHeatmap: boolean;
  showClusters: boolean;
}

interface StatsData {
  total: number;
  bySource: Record<string, number>;
}

interface MapSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  filters: SidebarFilters;
  onFiltersChange: (filters: Partial<SidebarFilters>) => void;
  stats: StatsData;
  extraClassName?: string;
}

export function MapSidebar({
  collapsed,
  onToggle,
  filters,
  onFiltersChange,
  stats,
  extraClassName,
}: MapSidebarProps) {
  const [keywordInput, setKeywordInput] = useState(filters.keyword);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onFiltersChange({ keyword: keywordInput });
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [keywordInput]);

  const handleSourceToggle = useCallback(
    (sourceId: string, checked: boolean) => {
      const next = checked
        ? [...filters.sourceTypes, sourceId]
        : filters.sourceTypes.filter((s) => s !== sourceId);
      onFiltersChange({ sourceTypes: next });
    },
    [filters.sourceTypes, onFiltersChange]
  );

  return (
    <div className={`map-sidebar${collapsed ? ' map-sidebar--collapsed' : ''}${extraClassName ? ` ${extraClassName}` : ''}`}>
      {/* Toggle button */}
      <button className="map-sidebar__toggle" onClick={onToggle} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
        {collapsed ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 18l6-6-6-6" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        )}
      </button>

      {/* Header */}
      <div className="map-sidebar__header">
        <div className="map-sidebar__title">Map Filters</div>
      </div>

      {/* Body */}
      <div className="map-sidebar__body">

        {/* Time range */}
        <div className="map-sidebar__section">
          <div className="map-sidebar__section-label">Time Range</div>
          <div className="time-range-buttons">
            {TIME_RANGE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                className={`time-range-btn${filters.timeRange === opt.value ? ' time-range-btn--active' : ''}`}
                onClick={() => onFiltersChange({ timeRange: opt.value })}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Source types */}
        <div className="map-sidebar__section">
          <div className="map-sidebar__section-label">Source Types</div>
          <div className="source-type-list">
            {SOURCE_TYPES.map((src) => {
              const count = stats.bySource[src.id] ?? 0;
              return (
                <label
                  key={src.id}
                  className="source-type-item"
                  style={count === 0 ? { opacity: 0.4 } : undefined}
                >
                  <input
                    type="checkbox"
                    checked={filters.sourceTypes.length === 0 || filters.sourceTypes.includes(src.id)}
                    onChange={(e) => handleSourceToggle(src.id, e.target.checked)}
                  />
                  <span className="source-type-dot" style={{ background: src.color }} />
                  <span className="source-type-label">{src.label}</span>
                  <span className="source-type-count">{count}</span>
                </label>
              );
            })}
          </div>
        </div>

        {/* Keyword search */}
        <div className="map-sidebar__section">
          <div className="map-sidebar__section-label">Keyword Filter</div>
          <input
            type="text"
            className="map-search-input"
            placeholder="Filter by content..."
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
          />
        </div>

        {/* Stats */}
        <div className="map-sidebar__section">
          <div className="map-sidebar__section-label">Stats</div>
          <div className="map-stats">
            <div className="map-stats__row">
              <span className="map-stats__label">Total events</span>
              <span className="map-stats__value">{stats.total}</span>
            </div>
            {SOURCE_TYPES.map((src) =>
              (stats.bySource[src.id] ?? 0) > 0 ? (
                <div key={src.id} className="map-stats__row">
                  <span className="map-stats__label">
                    <span className="source-type-dot" style={{ background: src.color }} />
                    {src.label}
                  </span>
                  <span className="map-stats__value">{stats.bySource[src.id]}</span>
                </div>
              ) : null
            )}
          </div>
        </div>

        {/* Layer toggles — Clusters only (Heatmap is in the right Layers panel) */}
        <div className="map-sidebar__section">
          <div className="map-sidebar__section-label">Layers</div>
          <div className="layer-toggles">
            <label className="layer-toggle-item">
              <span className="layer-toggle-label">Clusters</span>
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={filters.showClusters}
                  onChange={(e) => onFiltersChange({ showClusters: e.target.checked })}
                />
                <span className="toggle-slider" />
              </span>
            </label>
          </div>
        </div>

      </div>
    </div>
  );
}

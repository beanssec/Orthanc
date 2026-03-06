import React from 'react';

interface MapControlsProps {
  zoom: number;
  eventCount: number;
  loading: boolean;
  onRefresh: () => void;
  onFullscreen: () => void;
  isFullscreen: boolean;
}

export function MapControls({
  zoom,
  eventCount,
  loading,
  onRefresh,
  onFullscreen,
  isFullscreen,
}: MapControlsProps) {
  return (
    <div className="map-controls">
      {/* Event count badge */}
      <div className="map-event-count">{eventCount} events</div>

      {/* Zoom level */}
      <div className="map-info-badge">z{zoom.toFixed(1)}</div>

      {/* Control buttons */}
      <div className="map-controls__group">
        <button
          className={`map-control-btn${loading ? ' map-control-btn--spinning' : ''}`}
          onClick={onRefresh}
          title="Refresh events"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M23 4v6h-6" />
            <path d="M1 20v-6h6" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
        </button>
        <button
          className="map-control-btn"
          onClick={onFullscreen}
          title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
        >
          {isFullscreen ? (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import '../../styles/map.css';
import api from '../../services/api';
import { MapSidebar, SOURCE_TYPES } from './MapSidebar';
import type { SidebarFilters, TimeRange } from './MapSidebar';
import { MapControls } from './MapControls';

// CartoDB dark-matter — no token needed
const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

// Esri World Imagery — free, no API key required
const SATELLITE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    'esri-satellite': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© Esri, Maxar, Earthstar Geographics',
    },
  },
  layers: [{ id: 'satellite', type: 'raster', source: 'esri-satellite' }],
};

const HYBRID_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    'esri-satellite': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© Esri, Maxar, Earthstar Geographics',
    },
    'esri-labels': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 19,
    },
  },
  layers: [
    { id: 'satellite', type: 'raster', source: 'esri-satellite' },
    { id: 'labels', type: 'raster', source: 'esri-labels' },
  ],
};

// Color map for source types
const SOURCE_COLORS: Record<string, string> = {
  telegram: '#3b82f6',
  x: '#38bdf8',
  rss: '#10b981',
  shodan: '#e11d48',
};

function getSourceColor(sourceType: string): string {
  return SOURCE_COLORS[sourceType] ?? '#9ca3af';
}

interface MapEvent {
  id: string;
  lat: number;
  lng: number;
  place_name: string | null;
  confidence: number;
  precision?: string | null;
  post: {
    id: string;
    source_type: string;
    source_id: string;
    author: string | null;
    content: string | null;
    timestamp: string;
  };
}

function timeRangeToDateFrom(range: TimeRange): string | null {
  if (range === 'all') return null;
  const now = new Date();
  const map: Record<string, number> = {
    '1h': 1,
    '6h': 6,
    '24h': 24,
    '48h': 48,
    '7d': 168,
    '30d': 720,
  };
  const hours = map[range] ?? 24;
  const d = new Date(now.getTime() - hours * 60 * 60 * 1000);
  return d.toISOString();
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function buildPopupHtml(event: MapEvent): string {
  const color = getSourceColor(event.post.source_type);
  const content = (event.post.content ?? '').slice(0, 150);
  const author = event.post.author ?? 'Unknown';
  const place = event.place_name ?? '';
  const time = relativeTime(event.post.timestamp);

  return `
    <div class="map-popup">
      <div class="map-popup__source-badge" style="color: ${color}">
        <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${color};flex-shrink:0"></span>
        ${event.post.source_type.toUpperCase()}
      </div>
      <div class="map-popup__author">${escapeHtml(author)}</div>
      ${place ? `<div class="map-popup__place">📍 ${escapeHtml(place)}</div>` : ''}
      ${content ? `<div class="map-popup__content">${escapeHtml(content)}</div>` : ''}
      <div class="map-popup__footer">
        <span class="map-popup__time">${time}</span>
        <a class="map-popup__link" data-navigate="/feed?post=${event.post.id}" href="#">View in Feed →</a>
      </div>
    </div>
  `;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function buildClusterPopupHtml(events: MapEvent[]): string {
  const items = events.slice(0, 15).map((ev, idx) => {
    const color = getSourceColor(ev.post.source_type);
    const content = (ev.post.content ?? '').replace(/\*\*/g, '').slice(0, 80);
    const time = relativeTime(ev.post.timestamp);
    const place = ev.place_name ?? '';
    return `
      <div class="map-popup__cluster-item map-popup__cluster-item--clickable" data-event-idx="${idx}" data-post-id="${ev.post.id}" style="cursor:pointer">
        <div class="map-popup__cluster-header">
          <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${color};flex-shrink:0"></span>
          <span class="map-popup__cluster-source">${ev.post.source_type.toUpperCase()}</span>
          ${place ? `<span class="map-popup__cluster-place">📍 ${escapeHtml(place)}</span>` : ''}
          <span class="map-popup__cluster-time">${time}</span>
        </div>
        <div class="map-popup__cluster-content">${escapeHtml(content)}</div>
      </div>
    `;
  }).join('');

  const overflow = events.length > 15 ? `<div class="map-popup__cluster-overflow">+ ${events.length - 15} more events</div>` : '';

  return `
    <div class="map-popup map-popup--cluster">
      <div class="map-popup__cluster-title">${events.length} Events <span style="font-size:11px;color:#9ca3af;font-weight:400">— click to inspect</span></div>
      <div class="map-popup__cluster-list">${items}</div>
      ${overflow}
    </div>
  `;
}

function eventsToGeoJSON(events: MapEvent[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: events.map((ev) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [ev.lng, ev.lat] },
      properties: {
        id: ev.id,
        postId: ev.post.id,
        sourceType: ev.post.source_type,
        author: ev.post.author ?? '',
        content: ev.post.content ?? '',
        timestamp: ev.post.timestamp,
        placeName: ev.place_name ?? '',
        color: getSourceColor(ev.post.source_type),
        eventJson: JSON.stringify(ev),
      },
    })),
  };
}

// ---------------------------------------------------------------------------
// Plane icon helpers
// ---------------------------------------------------------------------------

function createPlaneImage(color: string): { width: number; height: number; data: Uint8ClampedArray } {
  const size = 32;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, size, size);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(16, 2);
  ctx.lineTo(24, 28);
  ctx.lineTo(16, 22);
  ctx.lineTo(8, 28);
  ctx.closePath();
  ctx.fill();
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

function createShipImage(color: string): { width: number; height: number; data: Uint8ClampedArray } {
  const size = 28;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, size, size);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(14, 2);
  ctx.lineTo(26, 14);
  ctx.lineTo(14, 26);
  ctx.lineTo(2, 14);
  ctx.closePath();
  ctx.fill();
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

function createSatelliteImage(color: string): { width: number; height: number; data: Uint8ClampedArray } {
  const size = 16;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, size, size);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(8, 8, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.globalAlpha = 0.6;
  ctx.beginPath();
  ctx.moveTo(1, 8); ctx.lineTo(5, 8);
  ctx.moveTo(11, 8); ctx.lineTo(15, 8);
  ctx.moveTo(8, 1); ctx.lineTo(8, 5);
  ctx.moveTo(8, 11); ctx.lineTo(8, 15);
  ctx.stroke();
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

function createDiamondImage(color: string, size: number = 28): { width: number; height: number; data: Uint8ClampedArray } {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, size, size);
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 2;
  // Diamond shape
  ctx.beginPath();
  ctx.moveTo(cx, cy - r);      // top
  ctx.lineTo(cx + r, cy);      // right
  ctx.lineTo(cx, cy + r);      // bottom
  ctx.lineTo(cx - r, cy);      // left
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.85;
  ctx.fill();
  ctx.strokeStyle = 'rgba(255,255,255,0.8)';
  ctx.lineWidth = 1.5;
  ctx.globalAlpha = 1;
  ctx.stroke();
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

function createTriangleImage(color: string, size: number = 28): { width: number; height: number; data: Uint8ClampedArray } {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, size, size);
  const margin = 2;
  // Upward-pointing triangle (warning symbol)
  ctx.beginPath();
  ctx.moveTo(size / 2, margin);                   // top center
  ctx.lineTo(size - margin, size - margin);        // bottom right
  ctx.lineTo(margin, size - margin);               // bottom left
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.9;
  ctx.fill();
  ctx.strokeStyle = 'rgba(255,255,255,0.85)';
  ctx.lineWidth = 1.5;
  ctx.globalAlpha = 1;
  ctx.stroke();
  // Exclamation mark
  ctx.fillStyle = 'rgba(0,0,0,0.75)';
  ctx.font = `bold ${Math.round(size * 0.45)}px sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('!', size / 2, size * 0.62);
  return { width: size, height: size, data: ctx.getImageData(0, 0, size, size).data };
}

// ---------------------------------------------------------------------------
// Layer constants
// ---------------------------------------------------------------------------

const SOURCE_ID = 'orthanc-events';
const CLUSTER_LAYER = 'clusters';
const CLUSTER_COUNT_LAYER = 'cluster-count';
const UNCLUSTERED_LAYER = 'unclustered-points';
const HEATMAP_LAYER = 'events-heatmap';

const FLIGHTS_SOURCE = 'flights-source';
const FLIGHTS_LAYER = 'flights-layer';

const SHIPS_SOURCE = 'ships-source';
const SHIPS_LAYER = 'ships-layer';

const FIRMS_SOURCE = 'firms-source';
const FIRMS_LAYER = 'firms-layer';

const FRONTLINES_SOURCE = 'frontlines-source';
const FRONTLINES_LAYER_LINE = 'frontlines-layer-line';
const FRONTLINES_LAYER_FILL = 'frontlines-layer-fill';
const FRONTLINES_LAYER_EVENTS = 'frontlines-layer-events';

const SATELLITES_SOURCE = 'satellites-source';
const SATELLITES_LAYER = 'satellites-layer';

const SENTIMENT_SOURCE = 'sentiment-source';
const SENTIMENT_LAYER_CIRCLES = 'sentiment-layer-circles';
const SENTIMENT_LAYER_HEAT = 'sentiment-layer-heat';

const ACLED_SOURCE = 'acled-source';
const ACLED_LAYER = 'acled-layer';

const GDELT_GEO_SOURCE = 'gdelt-geo-source';
const GDELT_GEO_HEAT = 'gdelt-geo-heat';
const GDELT_GEO_CIRCLES = 'gdelt-geo-circles';

const FUSION_SOURCE = 'fusion-source';
const FUSION_LAYER = 'fusion-layer';

const MARITIME_SOURCE = 'maritime-source';
const MARITIME_LAYER = 'maritime-layer';

const NOTAMS_SOURCE = 'notams-source';
const NOTAMS_LAYER = 'notams-layer';

// ---------------------------------------------------------------------------
// Layer state interface
// ---------------------------------------------------------------------------

interface LayerState {
  flights: boolean;
  ships: boolean;
  firms: boolean;
  frontlines: boolean;
  satellites: boolean;
  sentiment: boolean;
  gdelt: boolean;
  acled: boolean;
  fusion: boolean;
  notams: boolean;
  maritime: boolean;
}

interface LayerCounts {
  flights: number;
  ships: number;
  firms: number;
  frontlines: number;
  satellites: number;
  sentiment: number;
  gdelt: number;
  acled: number;
  fusion: number;
  notams: number;
  maritime: number;
}

interface FrontlineSourceInfo {
  id: string;
  name: string;
  description: string;
  cached: boolean;
  cached_at: number | null;
}

// ---------------------------------------------------------------------------
// Hover tooltip
// ---------------------------------------------------------------------------

function showTooltip(map: maplibregl.Map, tooltipRef: React.MutableRefObject<maplibregl.Popup | null>, coords: [number, number], html: string) {
  if (tooltipRef.current) tooltipRef.current.remove();
  tooltipRef.current = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 8,
    maxWidth: '260px',
  })
    .setLngLat(coords)
    .setHTML(html)
    .addTo(map);
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function MapView() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const tooltipRef = useRef<maplibregl.Popup | null>(null);
  const mapReadyRef = useRef(false);
  // Becomes true after map.on('load') fires; guards style.load re-setup
  const styleInitializedRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);

  // Refs that mirror state so the style.load callback can read current values
  const filteredEventsRef = useRef<MapEvent[]>([]);
  const filtersRef = useRef<SidebarFilters>({
    timeRange: '7d', sourceTypes: [], keyword: '', showHeatmap: false, showClusters: true,
  });
  const layersStateRef = useRef<LayerState>({
    flights: false, ships: false, firms: false, frontlines: false, satellites: false, sentiment: false,
    gdelt: false, acled: false, fusion: false, notams: false, maritime: false,
  });
  const fetchFnsRef = useRef<Record<keyof LayerState, () => void>>({} as Record<keyof LayerState, () => void>);

  const [baseLayer, setBaseLayer] = useState<'dark' | 'satellite' | 'hybrid'>('dark');

  const [zoom, setZoom] = useState(3);
  const [loading, setLoading] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [layerPanelCollapsed, setLayerPanelCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [mobileLayersOpen, setMobileLayersOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [allEvents, setAllEvents] = useState<MapEvent[]>([]);
  const [includeCountryLevel, setIncludeCountryLevel] = useState(true);
  const [selectedEvent, setSelectedEvent] = useState<MapEvent | null>(null);
  const [filters, setFilters] = useState<SidebarFilters>({
    timeRange: '7d',
    sourceTypes: [],
    keyword: '',
    showHeatmap: false,
    showClusters: true,
  });

  const [layers, setLayers] = useState<LayerState>({
    flights: false,
    ships: false,
    firms: false,
    frontlines: false,
    satellites: false,
    sentiment: false,
    gdelt: false,
    acled: false,
    fusion: false,
    notams: false,
    maritime: false,
  });
  const [layerCounts, setLayerCounts] = useState<LayerCounts>({
    flights: 0,
    ships: 0,
    firms: 0,
    frontlines: 0,
    satellites: 0,
    sentiment: 0,
    gdelt: 0,
    acled: 0,
    fusion: 0,
    notams: 0,
    maritime: 0,
  });

  // GDELT GEO state
  const [gdeltKeyword, setGdeltKeyword] = useState('conflict');
  const [gdeltInputValue, setGdeltInputValue] = useState('conflict');
  const gdeltDebounceRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const [sentimentHours, setSentimentHours] = useState(24);

  // Frontline source selector
  const [frontlineSource, setFrontlineSource] = useState('deepstate');
  const [frontlineSources, setFrontlineSources] = useState<FrontlineSourceInfo[]>([]);

  // Fetch available frontline sources on mount
  useEffect(() => {
    api.get('/layers/frontlines/sources')
      .then((res) => setFrontlineSources(res.data))
      .catch((err) => console.error('Failed to fetch frontline sources', err));
  }, []);

  // Track which layers have been loaded (lazy)
  const loadedLayers = useRef<Set<string>>(new Set());
  // Refresh interval handles
  const refreshIntervals = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  // Client-side keyword filtering
  const filteredEvents = useMemo(() => {
    if (!filters.keyword.trim()) return allEvents;
    const kw = filters.keyword.toLowerCase();
    return allEvents.filter(
      (ev) =>
        ev.post.content?.toLowerCase().includes(kw) ||
        ev.post.author?.toLowerCase().includes(kw) ||
        ev.place_name?.toLowerCase().includes(kw)
    );
  }, [allEvents, filters.keyword]);

  const stats = useMemo(() => {
    const bySource: Record<string, number> = {};
    for (const ev of filteredEvents) {
      bySource[ev.post.source_type] = (bySource[ev.post.source_type] ?? 0) + 1;
    }
    return { total: filteredEvents.length, bySource };
  }, [filteredEvents]);

  // Fetch events from API
  const fetchEvents = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { limit: '500' };
      const dateFrom = timeRangeToDateFrom(filters.timeRange);
      if (dateFrom) params.date_from = dateFrom;
      if (filters.sourceTypes.length > 0) {
        params.source_types = filters.sourceTypes.join(',');
      }
      if (!includeCountryLevel) {
        params.min_precision = 'city';
      }
      const res = await api.get<MapEvent[]>('/events/', { params });
      setAllEvents(res.data);
    } catch (err) {
      console.error('Failed to fetch events', err);
    } finally {
      setLoading(false);
    }
  }, [filters.timeRange, filters.sourceTypes, includeCountryLevel]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  // ---------------------------------------------------------------------------
  // Layer data fetchers
  // ---------------------------------------------------------------------------

  const fetchFlights = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/flights');
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(FLIGHTS_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, flights: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch flights', err);
    }
  }, []);

  const fetchShips = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/ships');
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(SHIPS_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, ships: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch ships', err);
    }
  }, []);

  const fetchFirms = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/firms');
      const raw = res.data as Array<Record<string, unknown>>;
      // Convert list → GeoJSON
      const geojson: GeoJSON.FeatureCollection = {
        type: 'FeatureCollection',
        features: raw
          .filter((d) => d.lat != null && d.lng != null)
          .map((d) => ({
            type: 'Feature' as const,
            geometry: { type: 'Point' as const, coordinates: [d.lng as number, d.lat as number] },
            properties: {
              brightness: d.brightness,
              frp: d.frp,
              confidence: d.confidence,
              satellite: d.satellite,
              daynight: d.daynight,
              zone: d.zone,
              timestamp: d.timestamp,
            },
          })),
      };
      const src = map.getSource(FIRMS_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(geojson);
      setLayerCounts((c) => ({ ...c, firms: geojson.features.length }));
    } catch (err) {
      console.error('Failed to fetch FIRMS', err);
    }
  }, []);

  const fetchFrontlines = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get(`/layers/frontlines?source=${frontlineSource}`);
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(FRONTLINES_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, frontlines: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch frontlines', err);
    }
  }, [frontlineSource]);

  const fetchSatellites = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/satellites');
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(SATELLITES_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, satellites: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch satellites', err);
    }
  }, []);

  const fetchSentiment = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get(`/layers/sentiment?hours=${sentimentHours}`);
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(SENTIMENT_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, sentiment: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch sentiment', err);
    }
  }, [sentimentHours]);

  const fetchGdelt = useCallback(async (keyword?: string) => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    const q = keyword ?? gdeltKeyword;
    if (!q.trim()) return;
    try {
      const res = await api.get(`/gdelt/geo?q=${encodeURIComponent(q)}`);
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(GDELT_GEO_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, gdelt: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch GDELT geo', err);
    }
  }, [gdeltKeyword]);

  const fetchAcled = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/acled?hours=168');
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(ACLED_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, acled: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch ACLED data', err);
    }
  }, []);

  const fetchFusion = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/fusion?hours=48');
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(FUSION_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, fusion: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch fusion data', err);
    }
  }, []);

  const fetchNotams = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/notams?active_only=true');
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(NOTAMS_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      setLayerCounts((c) => ({ ...c, notams: data.features?.length ?? 0 }));
    } catch (err) {
      console.error('Failed to fetch NOTAM data', err);
    }
  }, []);

  const fetchMaritime = useCallback(async () => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    try {
      const res = await api.get('/layers/maritime-events?hours=72');
      const data = res.data as GeoJSON.FeatureCollection;
      const src = map.getSource(MARITIME_SOURCE) as maplibregl.GeoJSONSource | undefined;
      if (src) src.setData(data);
      // Count only actual events (not port markers)
      const eventCount = data.features?.filter((f) => f.properties?.event_type !== 'monitored_port').length ?? 0;
      setLayerCounts((c) => ({ ...c, maritime: eventCount }));
    } catch (err) {
      console.error('Failed to fetch maritime events', err);
    }
  }, []);

  // Keep refs in sync with React state for use in style.load callback (can't use state directly in closure)
  useEffect(() => { filteredEventsRef.current = filteredEvents; }, [filteredEvents]);
  useEffect(() => { filtersRef.current = filters; }, [filters]);
  useEffect(() => { layersStateRef.current = layers; }, [layers]);
  useEffect(() => {
    fetchFnsRef.current = {
      flights: fetchFlights, ships: fetchShips, firms: fetchFirms,
      frontlines: fetchFrontlines, satellites: fetchSatellites, sentiment: fetchSentiment,
      gdelt: () => fetchGdelt(), acled: fetchAcled, fusion: fetchFusion,
      notams: fetchNotams, maritime: fetchMaritime,
    };
  }, [fetchFlights, fetchShips, fetchFirms, fetchFrontlines, fetchSatellites, fetchSentiment, fetchGdelt, fetchAcled, fetchFusion, fetchNotams, fetchMaritime]);

  // Switch base map layer
  useEffect(() => {
    if (!styleInitializedRef.current || !mapRef.current) return;
    const style: string | maplibregl.StyleSpecification =
      baseLayer === 'dark' ? MAP_STYLE :
      baseLayer === 'satellite' ? SATELLITE_STYLE :
      HYBRID_STYLE;
    mapRef.current.setStyle(style);
  }, [baseLayer]);

  // Map of layer key → { fetchFn, interval (ms), visibility }
  const LAYER_REFRESH: Record<keyof LayerState, { fetch: () => void; interval: number }> = useMemo(() => ({
    flights: { fetch: fetchFlights, interval: 60_000 },
    ships: { fetch: fetchShips, interval: 120_000 },
    firms: { fetch: fetchFirms, interval: 300_000 },
    frontlines: { fetch: fetchFrontlines, interval: 600_000 },
    satellites: { fetch: fetchSatellites, interval: 30_000 },
    sentiment: { fetch: fetchSentiment, interval: 300_000 },
    gdelt: { fetch: fetchGdelt, interval: 900_000 },
    acled: { fetch: fetchAcled, interval: 3_600_000 },
    fusion: { fetch: fetchFusion, interval: 300_000 },
    notams: { fetch: fetchNotams, interval: 900_000 },
    maritime: { fetch: fetchMaritime, interval: 900_000 },
  }), [fetchFlights, fetchShips, fetchFirms, fetchFrontlines, fetchSatellites, fetchSentiment, fetchGdelt, fetchAcled, fetchFusion, fetchNotams, fetchMaritime]);

  // Handle layer toggle
  const toggleLayer = useCallback((key: keyof LayerState, enabled: boolean) => {
    setLayers((prev) => ({ ...prev, [key]: enabled }));
  }, []);

  // Respond to layer enable/disable
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;

    const layerVisMap: Record<keyof LayerState, string[]> = {
      flights: [FLIGHTS_LAYER],
      ships: [SHIPS_LAYER],
      firms: [FIRMS_LAYER],
      frontlines: [FRONTLINES_LAYER_LINE, FRONTLINES_LAYER_FILL, FRONTLINES_LAYER_EVENTS],
      satellites: [SATELLITES_LAYER],
      sentiment: [SENTIMENT_LAYER_CIRCLES, SENTIMENT_LAYER_HEAT],
      gdelt: [GDELT_GEO_HEAT, GDELT_GEO_CIRCLES],
      acled: [ACLED_LAYER],
      fusion: [FUSION_LAYER],
      notams: [NOTAMS_LAYER],
      maritime: [MARITIME_LAYER],
    };

    for (const [key, enabled] of Object.entries(layers) as [keyof LayerState, boolean][]) {
      const mapLayers = layerVisMap[key] ?? [];
      const vis = enabled ? 'visible' : 'none';
      for (const lid of mapLayers) {
        if (map.getLayer(lid)) {
          map.setLayoutProperty(lid, 'visibility', vis);
        }
      }

      // Lazy-load on first enable
      if (enabled && !loadedLayers.current.has(key)) {
        loadedLayers.current.add(key);
        LAYER_REFRESH[key].fetch();
      }

      // Manage auto-refresh interval
      if (enabled && !refreshIntervals.current[key]) {
        LAYER_REFRESH[key].fetch(); // Immediate refresh on re-enable
        refreshIntervals.current[key] = setInterval(LAYER_REFRESH[key].fetch, LAYER_REFRESH[key].interval);
      } else if (!enabled && refreshIntervals.current[key]) {
        clearInterval(refreshIntervals.current[key]);
        delete refreshIntervals.current[key];
      }
    }
  }, [layers, LAYER_REFRESH]);

  // Cleanup intervals on unmount
  useEffect(() => {
    return () => {
      for (const h of Object.values(refreshIntervals.current)) clearInterval(h);
    };
  }, []);

  // Refetch frontlines when source changes (if layer is active)
  useEffect(() => {
    if (layers.frontlines && mapReadyRef.current) {
      // Reset the loaded flag so it will refetch
      loadedLayers.current.delete('frontlines');
      fetchFrontlines();
    }
  }, [frontlineSource]); // eslint-disable-line react-hooks/exhaustive-deps

  // Refetch sentiment when hours changes (if layer is active)
  useEffect(() => {
    if (layers.sentiment && mapReadyRef.current) {
      loadedLayers.current.delete('sentiment');
      fetchSentiment();
    }
  }, [sentimentHours]); // eslint-disable-line react-hooks/exhaustive-deps

  // Refetch GDELT when keyword changes (if layer is active)
  useEffect(() => {
    if (layers.gdelt && mapReadyRef.current) {
      loadedLayers.current.delete('gdelt');
      fetchGdelt(gdeltKeyword);
    }
  }, [gdeltKeyword]); // eslint-disable-line react-hooks/exhaustive-deps

  // Initialize map
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: MAP_STYLE,
      center: [20, 30],
      zoom: 3,
      attributionControl: false,
    });

    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

    map.on('zoom', () => setZoom(map.getZoom()));

    // ── Data layer setup ─────────────────────────────────────────────────────
    // Extracted so it can be called on initial load AND after map.setStyle()
    // (setStyle wipes all custom sources, layers, and images).
    const setupDataLayers = () => {
      // ── Custom icons ──────────────────────────────────────────────────────
      const planeBlue = createPlaneImage('#3b82f6');
      const planeRed = createPlaneImage('#ef4444');
      const shipCyan = createShipImage('#06b6d4');
      const shipOrange = createShipImage('#f97316');
      const satGreen = createSatelliteImage('#22c55e');
      const satRed = createSatelliteImage('#ef4444');
      const satGray = createSatelliteImage('#9ca3af');

      if (!map.hasImage('plane-icon')) map.addImage('plane-icon', { width: planeBlue.width, height: planeBlue.height, data: planeBlue.data });
      if (!map.hasImage('plane-icon-military')) map.addImage('plane-icon-military', { width: planeRed.width, height: planeRed.height, data: planeRed.data });
      if (!map.hasImage('ship-icon')) map.addImage('ship-icon', { width: shipCyan.width, height: shipCyan.height, data: shipCyan.data });
      if (!map.hasImage('ship-icon-military')) map.addImage('ship-icon-military', { width: shipOrange.width, height: shipOrange.height, data: shipOrange.data });
      if (!map.hasImage('sat-icon-stations')) map.addImage('sat-icon-stations', { width: satGreen.width, height: satGreen.height, data: satGreen.data });
      if (!map.hasImage('sat-icon-military')) map.addImage('sat-icon-military', { width: satRed.width, height: satRed.height, data: satRed.data });
      if (!map.hasImage('sat-icon-weather')) map.addImage('sat-icon-weather', { width: satGray.width, height: satGray.height, data: satGray.data });
      if (!map.hasImage('sat-icon-unknown')) map.addImage('sat-icon-unknown', { width: satGray.width, height: satGray.height, data: satGray.data });

      // ── Events source (clustered) ─────────────────────────────────────────
      map.addSource(SOURCE_ID, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
        cluster: true,
        clusterMaxZoom: 12,
        clusterRadius: 50,
      });

      map.addLayer({
        id: CLUSTER_LAYER,
        type: 'circle',
        source: SOURCE_ID,
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': ['step', ['get', 'point_count'], '#3b82f6', 10, '#f59e0b', 50, '#ef4444'],
          'circle-radius': ['step', ['get', 'point_count'], 20, 10, 28, 50, 36],
          'circle-opacity': 0.85,
          'circle-stroke-width': 2,
          'circle-stroke-color': 'rgba(255,255,255,0.3)',
        },
      });

      map.addLayer({
        id: CLUSTER_COUNT_LAYER,
        type: 'symbol',
        source: SOURCE_ID,
        filter: ['has', 'point_count'],
        layout: {
          'text-field': '{point_count_abbreviated}',
          'text-font': ['DIN Offc Pro Medium', 'Arial Unicode MS Bold'],
          'text-size': 12,
        },
        paint: { 'text-color': '#ffffff' },
      });

      map.addLayer({
        id: UNCLUSTERED_LAYER,
        type: 'circle',
        source: SOURCE_ID,
        filter: ['!', ['has', 'point_count']],
        paint: {
          'circle-color': ['get', 'color'],
          'circle-radius': 6,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(255,255,255,0.8)',
          'circle-opacity': 0.9,
        },
      });

      map.addLayer({
        id: HEATMAP_LAYER,
        type: 'heatmap',
        source: SOURCE_ID,
        maxzoom: 15,
        paint: {
          'heatmap-weight': ['interpolate', ['linear'], ['get', 'confidence'], 0, 0, 1, 1],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 1, 15, 3],
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,255,0)',
            0.2, 'rgba(59,130,246,0.5)',
            0.4, 'rgba(16,185,129,0.7)',
            0.6, 'rgba(245,158,11,0.8)',
            0.8, 'rgba(239,68,68,0.9)',
            1, 'rgba(239,68,68,1)',
          ],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 0, 20, 15, 40],
          'heatmap-opacity': 0.7,
        },
        layout: { visibility: 'none' },
      });

      // ── Flights source + layer ────────────────────────────────────────────
      map.addSource(FLIGHTS_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      map.addLayer({
        id: FLIGHTS_LAYER,
        type: 'symbol',
        source: FLIGHTS_SOURCE,
        layout: {
          visibility: 'none',
          'icon-image': ['case', ['==', ['get', 'is_military'], true], 'plane-icon-military', 'plane-icon'],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 3, 0.5, 8, 1.0, 12, 1.4],
          'icon-rotate': ['coalesce', ['get', 'heading'], 0],
          'icon-rotation-alignment': 'map',
          'icon-allow-overlap': true,
        },
      });

      // ── Ships source + layer ──────────────────────────────────────────────
      map.addSource(SHIPS_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      map.addLayer({
        id: SHIPS_LAYER,
        type: 'symbol',
        source: SHIPS_SOURCE,
        layout: {
          visibility: 'none',
          'icon-image': ['case',
            ['in', 'Military', ['coalesce', ['get', 'ship_type'], '']],
            'ship-icon-military',
            'ship-icon'
          ],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 3, 0.6, 8, 1.0, 12, 1.4],
          'icon-rotate': ['coalesce', ['get', 'heading'], ['get', 'course'], 0],
          'icon-rotation-alignment': 'map',
          'icon-allow-overlap': true,
        },
      });

      // ── FIRMS thermal source + layer ──────────────────────────────────────
      map.addSource(FIRMS_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      map.addLayer({
        id: FIRMS_LAYER,
        type: 'circle',
        source: FIRMS_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'circle-color': [
            'interpolate', ['linear'],
            ['coalesce', ['get', 'frp'], 50],
            0, '#f97316',
            100, '#ef4444',
            300, '#fff',
          ],
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            3, ['interpolate', ['linear'], ['coalesce', ['get', 'frp'], 10], 0, 3, 500, 8],
            10, ['interpolate', ['linear'], ['coalesce', ['get', 'frp'], 10], 0, 6, 500, 18],
          ],
          'circle-opacity': 0.75,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(255,150,50,0.5)',
          'circle-blur': 0.3,
        },
      });

      // ── Frontlines source + layers ────────────────────────────────────────
      map.addSource(FRONTLINES_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      // Frontline zone fills — color-coded by status from DeepState
      map.addLayer({
        id: FRONTLINES_LAYER_FILL,
        type: 'fill',
        source: FRONTLINES_SOURCE,
        filter: ['==', ['get', 'layer_type'], 'zone'],
        layout: { visibility: 'none' },
        paint: {
          'fill-color': [
            'match', ['get', 'status'],
            'occupied', '#dc2626',     // Red for Russian-occupied
            'liberated', '#16a34a',    // Green for Ukrainian-liberated
            'contested', '#a8a29e',    // Gray/brown for contested
            '#78716c',                 // Default fallback
          ],
          'fill-opacity': [
            'match', ['get', 'status'],
            'occupied', 0.25,
            'liberated', 0.15,
            'contested', 0.2,
            0.15,
          ],
        },
      });

      // Frontline zone borders
      map.addLayer({
        id: FRONTLINES_LAYER_LINE,
        type: 'line',
        source: FRONTLINES_SOURCE,
        filter: ['==', ['get', 'layer_type'], 'zone'],
        layout: {
          visibility: 'none',
          'line-join': 'round',
          'line-cap': 'round',
        },
        paint: {
          'line-color': [
            'match', ['get', 'status'],
            'occupied', '#ef4444',
            'liberated', '#22c55e',
            'contested', '#a8a29e',
            '#78716c',
          ],
          'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.5, 8, 1.5, 12, 2.5],
          'line-opacity': 0.7,
        },
      });

      // Frontline battle events (shelling, battles, explosions, advances)
      map.addLayer({
        id: FRONTLINES_LAYER_EVENTS,
        type: 'circle',
        source: FRONTLINES_SOURCE,
        filter: ['==', ['get', 'layer_type'], 'event'],
        layout: { visibility: 'none' },
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 2, 8, 4, 12, 7],
          'circle-color': [
            'match', ['get', 'event_type'],
            'shelling', '#f97316',     // Orange
            'battle', '#ef4444',       // Red
            'explosion', '#f59e0b',    // Amber
            'advance', '#22c55e',      // Green
            'retreat', '#6366f1',      // Indigo
            '#9ca3af',                 // Default gray
          ],
          'circle-opacity': 0.8,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(0,0,0,0.3)',
        },
      });

      // ── Satellites source + layer ─────────────────────────────────────────
      map.addSource(SATELLITES_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      map.addLayer({
        id: SATELLITES_LAYER,
        type: 'symbol',
        source: SATELLITES_SOURCE,
        layout: {
          visibility: 'none',
          'icon-image': ['concat', 'sat-icon-', ['coalesce', ['get', 'group'], 'unknown']],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 3, 0.7, 8, 1.0],
          'icon-allow-overlap': true,
        },
      });

      // ── Sentiment source + layers ─────────────────────────────────────────
      map.addSource(SENTIMENT_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      // Sentiment heatmap (rendered below circles)
      map.addLayer({
        id: SENTIMENT_LAYER_HEAT,
        type: 'heatmap',
        source: SENTIMENT_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'heatmap-weight': ['interpolate', ['linear'], ['get', 'post_count'], 1, 0.3, 20, 1],
          'heatmap-intensity': 0.8,
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)',
            0.2, '#22c55e',
            0.4, '#eab308',
            0.6, '#f97316',
            0.8, '#ef4444',
            1.0, '#dc2626',
          ],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 2, 20, 8, 40, 12, 60],
          'heatmap-opacity': 0.7,
        },
      });

      // Sentiment circles — sized by post count, colored by sentiment
      map.addLayer({
        id: SENTIMENT_LAYER_CIRCLES,
        type: 'circle',
        source: SENTIMENT_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'circle-radius': ['get', 'radius'],
          'circle-color': ['get', 'color'],
          'circle-opacity': 0.6,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(255,255,255,0.2)',
        },
      });

      // ── GDELT GEO media attention source + layers ─────────────────────────
      map.addSource(GDELT_GEO_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      // GDELT heatmap layer (orange/red gradient)
      map.addLayer({
        id: GDELT_GEO_HEAT,
        type: 'heatmap',
        source: GDELT_GEO_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'heatmap-weight': [
            'interpolate', ['linear'],
            ['coalesce', ['get', 'count'], ['get', 'shareimage'], 1],
            0, 0.2,
            100, 1,
          ],
          'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 0, 1, 10, 2],
          'heatmap-color': [
            'interpolate', ['linear'], ['heatmap-density'],
            0, 'rgba(0,0,0,0)',
            0.2, 'rgba(249,115,22,0.4)',
            0.4, 'rgba(239,68,68,0.6)',
            0.6, 'rgba(220,38,38,0.8)',
            0.8, 'rgba(185,28,28,0.9)',
            1.0, 'rgba(255,255,255,1)',
          ],
          'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 2, 15, 8, 30, 12, 50],
          'heatmap-opacity': 0.75,
        },
      });

      // GDELT circle layer for individual points
      map.addLayer({
        id: GDELT_GEO_CIRCLES,
        type: 'circle',
        source: GDELT_GEO_SOURCE,
        minzoom: 5,
        layout: { visibility: 'none' },
        paint: {
          'circle-radius': [
            'interpolate', ['linear'],
            ['coalesce', ['get', 'count'], 1],
            1, 4,
            50, 10,
            500, 18,
          ],
          'circle-color': '#f97316',
          'circle-opacity': 0.5,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(249,115,22,0.8)',
        },
      });

      // GDELT circle hover
      map.on('mouseenter', GDELT_GEO_CIRCLES, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const name = p.name || p.placename || p.location || '';
        const count = p.count || p.numarts || '';
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title">📰 Media Attention</div>
            ${name ? `<div class="map-tooltip__row"><span>Location</span><span>${escapeHtml(String(name))}</span></div>` : ''}
            ${count ? `<div class="map-tooltip__row"><span>Articles</span><span>${count}</span></div>` : ''}
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', GDELT_GEO_CIRCLES, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });

      // ── ACLED conflict events source + layer ─────────────────────────────
      map.addSource(ACLED_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      map.addLayer({
        id: ACLED_LAYER,
        type: 'circle',
        source: ACLED_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'circle-color': ['coalesce', ['get', 'color'], '#ef4444'],
          'circle-radius': [
            'case',
            ['>', ['coalesce', ['get', 'fatalities'], 0], 0],
            9,
            6,
          ],
          'circle-opacity': 0.8,
          'circle-stroke-width': 1,
          'circle-stroke-color': 'rgba(255,255,255,0.4)',
        },
      });

      // ACLED hover
      map.on('mouseenter', ACLED_LAYER, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const fatalitiesText = p.fatalities > 0 ? `${p.fatalities} fatalities` : 'No fatalities reported';
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title">${escapeHtml(p.icon || '⚔️')} ${escapeHtml(p.event_type || 'Conflict Event')}</div>
            ${p.actor1 ? `<div class="map-tooltip__row"><span>Actor</span><span>${escapeHtml(String(p.actor1))}</span></div>` : ''}
            ${p.actor2 ? `<div class="map-tooltip__row"><span>vs</span><span>${escapeHtml(String(p.actor2))}</span></div>` : ''}
            <div class="map-tooltip__row"><span>Location</span><span>${escapeHtml(p.location || '—')}</span></div>
            <div class="map-tooltip__row"><span>Casualties</span><span>${fatalitiesText}</span></div>
            ${p.date ? `<div class="map-tooltip__row"><span>Date</span><span>${new Date(p.date).toLocaleDateString()}</span></div>` : ''}
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', ACLED_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });

      // ACLED click popup
      map.on('click', ACLED_LAYER, (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const color = p.color || '#ef4444';
        const fatalitiesText = p.fatalities > 0
          ? `<span style="color:#ef4444;font-weight:600">⚠ ${p.fatalities} fatalities</span>`
          : 'No fatalities reported';
        const html = `
          <div class="map-popup">
            <div class="map-popup__source-badge" style="color:${color}">
              <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${color};flex-shrink:0"></span>
              ${escapeHtml(p.icon || '⚔️')} ACLED — ${escapeHtml(p.event_type || 'Conflict')}
            </div>
            ${p.sub_event_type ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">${escapeHtml(String(p.sub_event_type))}</div>` : ''}
            ${p.actor1 ? `<div class="map-popup__author">${escapeHtml(String(p.actor1))}${p.actor2 ? ` <span style="color:var(--text-muted)">vs</span> ${escapeHtml(String(p.actor2))}` : ''}</div>` : ''}
            <div class="map-popup__place">📍 ${escapeHtml(p.location || p.country || '—')}</div>
            <div class="map-popup__content">
              ${fatalitiesText}<br>
              ${p.date ? `Date: ${new Date(p.date).toLocaleDateString()}` : ''}
              ${p.title ? `<div style="margin-top:6px;font-size:11px;color:var(--text-muted)">${escapeHtml(String(p.title).slice(0, 200))}</div>` : ''}
            </div>
            ${p.source_url ? `<div class="map-popup__footer"><a class="map-popup__link" href="${escapeHtml(String(p.source_url))}" target="_blank" rel="noopener">Source →</a></div>` : ''}
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '300px', offset: 10 })
          .setLngLat(f.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });

      // ── NOTAM airspace restrictions source + layer ────────────────────────
      map.addSource(NOTAMS_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      // Create triangle/warning marker images for NOTAMs
      const notamAmberImg = createTriangleImage('#fbbf24', 28);
      const notamRedImg = createTriangleImage('#ef4444', 28);
      const notamOrangeImg = createTriangleImage('#f97316', 28);
      if (!map.hasImage('notam-standard')) map.addImage('notam-standard', { width: notamAmberImg.width, height: notamAmberImg.height, data: notamAmberImg.data });
      if (!map.hasImage('notam-gps_jamming')) map.addImage('notam-gps_jamming', { width: notamRedImg.width, height: notamRedImg.height, data: notamRedImg.data });
      if (!map.hasImage('notam-military')) map.addImage('notam-military', { width: notamOrangeImg.width, height: notamOrangeImg.height, data: notamOrangeImg.data });
      if (!map.hasImage('notam-tfr')) map.addImage('notam-tfr', { width: notamAmberImg.width, height: notamAmberImg.height, data: notamAmberImg.data });

      map.addLayer({
        id: NOTAMS_LAYER,
        type: 'symbol',
        source: NOTAMS_SOURCE,
        layout: {
          visibility: 'none',
          'icon-image': ['concat', 'notam-', ['coalesce', ['get', 'type'], 'standard']],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 3, 0.6, 8, 1.0, 12, 1.3],
          'icon-allow-overlap': true,
          'icon-ignore-placement': false,
        },
      });

      // NOTAM hover tooltip
      map.on('mouseenter', NOTAMS_LAYER, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const color = p.color || '#fbbf24';
        const typeLabel = String(p.type || 'standard').replace('_', ' ').toUpperCase();
        const endTime = p.end_time ? new Date(p.end_time).toLocaleString() : '—';
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title" style="color:${color}">⚠ NOTAM — ${typeLabel}</div>
            <div class="map-tooltip__row"><span>ID</span><span>${escapeHtml(String(p.notam_id || '—'))}</span></div>
            <div class="map-tooltip__row"><span>FIR</span><span>${escapeHtml(String(p.fir || '—'))}</span></div>
            <div class="map-tooltip__row"><span>Valid until</span><span>${endTime}</span></div>
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', NOTAMS_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });

      // NOTAM click popup
      map.on('click', NOTAMS_LAYER, (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const color = p.color || '#fbbf24';
        const typeLabel = String(p.type || 'standard').replace(/_/g, ' ').toUpperCase();
        const startTime = p.start_time ? new Date(p.start_time).toLocaleString() : '—';
        const endTime = p.end_time ? new Date(p.end_time).toLocaleString() : '—';
        const body = String(p.body || p.title || '').slice(0, 300);
        const flAlt = (p.lower_fl != null && p.upper_fl != null)
          ? `FL${p.lower_fl}–FL${p.upper_fl}`
          : null;
        const html = `
          <div class="map-popup">
            <div class="map-popup__source-badge" style="color:${color}">
              <span style="display:inline-block;width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:9px solid ${color};flex-shrink:0"></span>
              ⚠ NOTAM — ${typeLabel}
            </div>
            <div class="map-popup__author">${escapeHtml(String(p.notam_id || '—'))} &nbsp;|&nbsp; ${escapeHtml(String(p.fir || '—'))}</div>
            ${p.q_code ? `<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">Q-Code: ${escapeHtml(String(p.q_code))}</div>` : ''}
            <div class="map-popup__place">
              Valid: ${startTime}<br>
              Until: ${endTime}
              ${flAlt ? `<br>Altitude: ${escapeHtml(flAlt)}` : ''}
              ${p.radius_nm ? `<br>Radius: ${p.radius_nm} NM` : ''}
            </div>
            ${body ? `<div class="map-popup__content" style="font-size:11px;margin-top:6px">${escapeHtml(body)}</div>` : ''}
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '320px', offset: 10 })
          .setLngLat(f.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });

      // ── Fused Intelligence source + layer ────────────────────────────────
      map.addSource(FUSION_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      // Register diamond icons for each severity
      const diamondFlash = createDiamondImage('#ef4444', 32);
      const diamondUrgent = createDiamondImage('#f97316', 28);
      const diamondRoutine = createDiamondImage('#3b82f6', 24);
      if (!map.hasImage('fusion-flash')) map.addImage('fusion-flash', { width: diamondFlash.width, height: diamondFlash.height, data: diamondFlash.data });
      if (!map.hasImage('fusion-urgent')) map.addImage('fusion-urgent', { width: diamondUrgent.width, height: diamondUrgent.height, data: diamondUrgent.data });
      if (!map.hasImage('fusion-routine')) map.addImage('fusion-routine', { width: diamondRoutine.width, height: diamondRoutine.height, data: diamondRoutine.data });

      map.addLayer({
        id: FUSION_LAYER,
        type: 'symbol',
        source: FUSION_SOURCE,
        layout: {
          visibility: 'none',
          'icon-image': ['concat', 'fusion-', ['coalesce', ['get', 'severity'], 'routine']],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 3, 0.7, 8, 1.0, 12, 1.3],
          'icon-allow-overlap': true,
          'icon-ignore-placement': false,
        },
      });

      // Fusion hover tooltip
      map.on('mouseenter', FUSION_LAYER, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const severityColors: Record<string, string> = { flash: '#ef4444', urgent: '#f97316', routine: '#3b82f6' };
        const color = severityColors[p.severity] ?? '#6b7280';
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title" style="color:${color}">◆ Fused Intelligence — ${String(p.severity || 'routine').toUpperCase()}</div>
            <div class="map-tooltip__row"><span>Sources</span><span>${p.source_count || 0}</span></div>
            <div class="map-tooltip__row"><span>Reports</span><span>${p.post_count || 0}</span></div>
            ${p.summary ? `<div style="font-size:11px;color:var(--text-muted);margin-top:4px;max-width:200px">${escapeHtml(String(p.summary).slice(0, 120))}</div>` : ''}
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', FUSION_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });

      // Fusion click popup
      map.on('click', FUSION_LAYER, (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const severityColors: Record<string, string> = { flash: '#ef4444', urgent: '#f97316', routine: '#3b82f6' };
        const color = severityColors[p.severity] ?? '#6b7280';
        const severityLabel = String(p.severity || 'routine').toUpperCase();
        // Parse entity_names (stored as JSON string in GeoJSON properties)
        let entityNames: string[] = [];
        try { entityNames = JSON.parse(p.entity_names || '[]'); } catch { /* */ }
        // Parse source_types
        let sourceTypes: string[] = [];
        try { sourceTypes = JSON.parse(p.source_types || '[]'); } catch { /* */ }
        const summary = String(p.summary || '').slice(0, 300);
        const html = `
          <div class="map-popup">
            <div class="map-popup__source-badge" style="color:${color}">
              <span style="display:inline-block;width:8px;height:8px;transform:rotate(45deg);background:${color};flex-shrink:0"></span>
              ◆ FUSED INTELLIGENCE — ${severityLabel}
            </div>
            <div class="map-popup__author" style="font-size:12px">
              ${p.source_count || 0} sources · ${p.post_count || 0} reports
            </div>
            ${entityNames.length > 0 ? `<div class="map-popup__place">📍 ${escapeHtml(entityNames.slice(0, 3).join(', '))}</div>` : ''}
            ${summary ? `<div class="map-popup__content" style="font-size:11px">${escapeHtml(summary)}</div>` : ''}
            ${sourceTypes.length > 0 ? `<div style="margin-top:6px;font-size:10px;color:var(--text-muted)">Sources: ${escapeHtml(sourceTypes.join(', '))}</div>` : ''}
            <div class="map-popup__footer">
              <a class="map-popup__link" data-navigate="/feed" href="#">View component posts →</a>
            </div>
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '320px', offset: 10 })
          .setLngLat(f.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });

      // ── Maritime Events source + layer ───────────────────────────────────
      map.addSource(MARITIME_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      map.addLayer({
        id: MARITIME_LAYER,
        type: 'circle',
        source: MARITIME_SOURCE,
        layout: { visibility: 'none' },
        paint: {
          'circle-color': ['coalesce', ['get', 'color'], '#f97316'],
          'circle-radius': [
            'case',
            ['==', ['get', 'event_type'], 'dark_ship'], 10,
            ['==', ['get', 'event_type'], 'sts_transfer'], 9,
            ['==', ['get', 'event_type'], 'monitored_port'], 5,
            7,
          ],
          'circle-opacity': [
            'case',
            ['==', ['get', 'event_type'], 'monitored_port'], 0.4,
            0.85,
          ],
          'circle-stroke-width': [
            'case',
            ['==', ['get', 'event_type'], 'monitored_port'], 1,
            2,
          ],
          'circle-stroke-color': [
            'case',
            ['==', ['get', 'event_type'], 'monitored_port'], 'rgba(100,116,139,0.5)',
            'rgba(255,255,255,0.6)',
          ],
        },
      });

      // Maritime hover tooltip
      map.on('mouseenter', MARITIME_LAYER, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        if (p.event_type === 'monitored_port') return; // no tooltip for port markers
        const color = p.color || '#f97316';
        const label = String(p.label || p.event_type || 'Maritime Event');
        let detailsObj: Record<string, unknown> = {};
        try { detailsObj = JSON.parse(p.details || '{}'); } catch { /* */ }
        const detectedAt = p.detected_at ? new Date(p.detected_at).toLocaleString() : '—';
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title" style="color:${color}">${escapeHtml(p.icon || '🚨')} ${escapeHtml(label)}</div>
            <div class="map-tooltip__row"><span>Vessel</span><span>${escapeHtml(String(p.vessel_name || p.mmsi || '—'))}</span></div>
            <div class="map-tooltip__row"><span>MMSI</span><span>${escapeHtml(String(p.mmsi || '—'))}</span></div>
            <div class="map-tooltip__row"><span>Severity</span><span>${escapeHtml(String(p.severity || '—'))}</span></div>
            <div class="map-tooltip__row"><span>Detected</span><span>${detectedAt}</span></div>
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', MARITIME_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });

      // Maritime click popup
      map.on('click', MARITIME_LAYER, (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        if (p.event_type === 'monitored_port') return;
        const color = p.color || '#f97316';
        const label = String(p.label || p.event_type || 'Maritime Event');
        let detailsObj: Record<string, unknown> = {};
        try { detailsObj = JSON.parse(p.details || '{}'); } catch { /* */ }
        const detectedAt = p.detected_at ? new Date(p.detected_at).toLocaleString() : '—';
        const detailLines = Object.entries(detailsObj)
          .map(([k, v]) => `<div class="map-popup__content" style="font-size:11px">${escapeHtml(k.replace(/_/g, ' '))}: ${escapeHtml(String(v))}</div>`)
          .join('');
        const html = `
          <div class="map-popup">
            <div class="map-popup__source-badge" style="color:${color}">
              <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${color};flex-shrink:0"></span>
              ${escapeHtml(p.icon || '🚨')} ${escapeHtml(label)}
            </div>
            <div class="map-popup__author">${escapeHtml(String(p.vessel_name || 'Unknown vessel'))}</div>
            <div class="map-popup__place">MMSI: ${escapeHtml(String(p.mmsi || '—'))}</div>
            <div class="map-popup__content">
              Severity: <strong>${escapeHtml(String(p.severity || '—'))}</strong><br>
              Detected: ${detectedAt}
            </div>
            ${detailLines}
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '320px', offset: 10 })
          .setLngLat(f.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });

    }; // end setupDataLayers

    // Re-add all data layers after a base layer style switch.
    // style.load fires on initial load too — guard with styleInitializedRef.
    map.on('style.load', () => {
      if (!styleInitializedRef.current) return;
      setupDataLayers();

      // Re-populate events source data
      const evSrc = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
      if (evSrc) evSrc.setData(eventsToGeoJSON(filteredEventsRef.current));

      // Re-apply OSINT cluster / heatmap visibility
      const curFilters = filtersRef.current;
      const clusterVis = curFilters.showClusters ? 'visible' : 'none';
      if (map.getLayer(CLUSTER_LAYER)) map.setLayoutProperty(CLUSTER_LAYER, 'visibility', clusterVis);
      if (map.getLayer(CLUSTER_COUNT_LAYER)) map.setLayoutProperty(CLUSTER_COUNT_LAYER, 'visibility', clusterVis);
      if (map.getLayer(UNCLUSTERED_LAYER)) map.setLayoutProperty(UNCLUSTERED_LAYER, 'visibility', clusterVis);
      if (map.getLayer(HEATMAP_LAYER)) map.setLayoutProperty(HEATMAP_LAYER, 'visibility', curFilters.showHeatmap ? 'visible' : 'none');

      // Re-apply data layer visibility + re-fetch loaded layers
      const layerVisMap: Record<keyof LayerState, string[]> = {
        flights: [FLIGHTS_LAYER],
        ships: [SHIPS_LAYER],
        firms: [FIRMS_LAYER],
        frontlines: [FRONTLINES_LAYER_LINE, FRONTLINES_LAYER_FILL, FRONTLINES_LAYER_EVENTS],
        satellites: [SATELLITES_LAYER],
        sentiment: [SENTIMENT_LAYER_CIRCLES, SENTIMENT_LAYER_HEAT],
        gdelt: [GDELT_GEO_HEAT, GDELT_GEO_CIRCLES],
        acled: [ACLED_LAYER],
        fusion: [FUSION_LAYER],
        notams: [NOTAMS_LAYER],
        maritime: [MARITIME_LAYER],
      };
      const curLayers = layersStateRef.current;
      for (const [key, enabled] of Object.entries(curLayers) as [keyof LayerState, boolean][]) {
        const vis = enabled ? 'visible' : 'none';
        for (const lid of (layerVisMap[key as keyof LayerState] ?? [])) {
          if (map.getLayer(lid)) map.setLayoutProperty(lid, 'visibility', vis);
        }
        if (enabled && loadedLayers.current.has(key)) {
          fetchFnsRef.current[key as keyof LayerState]?.();
        }
      }
    });

    map.on('load', () => {
      styleInitializedRef.current = true;
      mapReadyRef.current = true;
      setMapReady(true);

      setupDataLayers();

      // ── Cluster click: popup + zoom ───────────────────────────────────────
      map.on('click', CLUSTER_LAYER, async (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: [CLUSTER_LAYER] });
        if (!features.length) return;
        const clusterId = features[0].properties?.cluster_id;
        const pointCount = features[0].properties?.point_count ?? 0;
        const src = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource;
        const geom = features[0].geometry;
        if (geom.type !== 'Point') return;
        const coords = geom.coordinates as [number, number];

        try {
          const leaves = await src.getClusterLeaves(clusterId, Math.min(pointCount, 20), 0);
          const events: MapEvent[] = [];
          for (const leaf of leaves) {
            try {
              events.push(JSON.parse(leaf.properties?.eventJson) as MapEvent);
            } catch { /* skip */ }
          }

          if (events.length) {
            if (popupRef.current) popupRef.current.remove();
            const popup = new maplibregl.Popup({
              closeButton: true,
              maxWidth: '420px',
              offset: 15,
            })
              .setLngLat(coords)
              .setHTML(buildClusterPopupHtml(events))
              .addTo(map);
            popupRef.current = popup;

            // Attach click handlers to cluster items via event delegation
            const el = popup.getElement();
            if (el) {
              el.addEventListener('click', (evt) => {
                const target = (evt.target as HTMLElement).closest('.map-popup__cluster-item--clickable');
                if (!target) return;
                const idx = parseInt(target.getAttribute('data-event-idx') || '0', 10);
                if (events[idx]) {
                  setSelectedEvent(events[idx]);
                }
              });
            }
          }

          const expansionZoom = await src.getClusterExpansionZoom(clusterId);
          const currentZoom = map.getZoom();
          if (expansionZoom != null && expansionZoom > currentZoom + 0.5) {
            map.easeTo({ center: coords, zoom: expansionZoom });
          }
        } catch {
          map.easeTo({ center: coords, zoom: map.getZoom() + 2 });
        }
      });

      map.on('mouseenter', CLUSTER_LAYER, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', CLUSTER_LAYER, () => { map.getCanvas().style.cursor = ''; });

      // ── Individual marker click — open detail panel ─────────────────────
      map.on('click', UNCLUSTERED_LAYER, (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: [UNCLUSTERED_LAYER] });
        if (!features.length) return;
        const props = features[0].properties;
        if (!props) return;

        let event: MapEvent | null = null;
        try {
          event = JSON.parse(props.eventJson) as MapEvent;
        } catch { return; }

        if (event) {
          setSelectedEvent(event);
        }
      });

      map.on('mouseenter', UNCLUSTERED_LAYER, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', UNCLUSTERED_LAYER, () => { map.getCanvas().style.cursor = ''; });

      // ── Flight hover/click ────────────────────────────────────────────────
      map.on('mouseenter', FLIGHTS_LAYER, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title">✈ ${escapeHtml(p.callsign || 'Unknown')}</div>
            <div class="map-tooltip__row"><span>Country</span><span>${escapeHtml(p.origin_country || '—')}</span></div>
            <div class="map-tooltip__row"><span>Altitude</span><span>${p.altitude ? Math.round(p.altitude) + ' m' : '—'}</span></div>
            <div class="map-tooltip__row"><span>Speed</span><span>${p.velocity ? Math.round(p.velocity) + ' m/s' : '—'}</span></div>
            ${p.is_military ? '<div class="map-tooltip__badge map-tooltip__badge--red">MILITARY</div>' : ''}
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', FLIGHTS_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });
      map.on('click', FLIGHTS_LAYER, (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const html = `
          <div class="map-popup">
            <div class="map-popup__source-badge" style="color:${p.is_military ? '#ef4444' : '#3b82f6'}">
              <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${p.is_military ? '#ef4444' : '#3b82f6'}"></span>
              ✈ ${p.is_military ? 'MILITARY' : 'CIVIL'} AIRCRAFT
            </div>
            <div class="map-popup__author">${escapeHtml(p.callsign || 'Unknown callsign')}</div>
            <div class="map-popup__place">🌍 ${escapeHtml(p.origin_country || 'Unknown country')}</div>
            <div class="map-popup__content">
              ICAO24: ${escapeHtml(p.icao24 || '—')}<br>
              Altitude: ${p.altitude ? Math.round(p.altitude) + ' m' : '—'}<br>
              Speed: ${p.velocity ? Math.round(p.velocity) + ' m/s' : '—'}<br>
              Heading: ${p.heading != null ? Math.round(p.heading) + '°' : '—'}<br>
              On ground: ${p.on_ground ? 'Yes' : 'No'}<br>
              Zone: ${escapeHtml(p.zone || '—')}
            </div>
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '280px', offset: 10 })
          .setLngLat(f.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });

      // ── Ship hover/click ──────────────────────────────────────────────────
      map.on('mouseenter', SHIPS_LAYER, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title">⚓ ${escapeHtml(p.vessel_name || 'Unknown')}</div>
            <div class="map-tooltip__row"><span>Type</span><span>${escapeHtml(p.ship_type || '—')}</span></div>
            <div class="map-tooltip__row"><span>Speed</span><span>${p.speed != null ? p.speed + ' kts' : '—'}</span></div>
            <div class="map-tooltip__row"><span>Dest</span><span>${escapeHtml(p.destination || '—')}</span></div>
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', SHIPS_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });
      map.on('click', SHIPS_LAYER, (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const isMilitary = (p.ship_type || '').toLowerCase().includes('military');
        const html = `
          <div class="map-popup">
            <div class="map-popup__source-badge" style="color:${isMilitary ? '#f97316' : '#06b6d4'}">
              <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${isMilitary ? '#f97316' : '#06b6d4'}"></span>
              ⚓ ${escapeHtml(p.ship_type || 'VESSEL')}
            </div>
            <div class="map-popup__author">${escapeHtml(p.vessel_name || 'Unknown Vessel')}</div>
            <div class="map-popup__content">
              MMSI: ${escapeHtml(p.mmsi || '—')}<br>
              Speed: ${p.speed != null ? p.speed + ' knots' : '—'}<br>
              Heading: ${p.heading != null ? Math.round(p.heading) + '°' : '—'}<br>
              Destination: ${escapeHtml(p.destination || '—')}<br>
              Region: ${escapeHtml(p.region || '—')}
            </div>
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '280px', offset: 10 })
          .setLngLat(f.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });

      // ── FIRMS hover ───────────────────────────────────────────────────────
      map.on('mouseenter', FIRMS_LAYER, (e) => {
        map.getCanvas().style.cursor = 'crosshair';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title">🔥 Thermal Anomaly</div>
            <div class="map-tooltip__row"><span>Satellite</span><span>${escapeHtml(p.satellite || '—')}</span></div>
            <div class="map-tooltip__row"><span>FRP</span><span>${p.frp != null ? p.frp + ' MW' : '—'}</span></div>
            <div class="map-tooltip__row"><span>Confidence</span><span>${escapeHtml(String(p.confidence || '—'))}</span></div>
            <div class="map-tooltip__row"><span>Time</span><span>${p.timestamp ? new Date(p.timestamp).toLocaleTimeString() : '—'}</span></div>
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', FIRMS_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });

      // ── Satellite hover ───────────────────────────────────────────────────
      map.on('mouseenter', SATELLITES_LAYER, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title">🛰 ${escapeHtml(p.name || 'Unknown')}</div>
            <div class="map-tooltip__row"><span>Group</span><span>${escapeHtml(p.group || '—')}</span></div>
            <div class="map-tooltip__row"><span>Altitude</span><span>${p.altitude_km != null ? p.altitude_km + ' km' : '—'}</span></div>
            <div class="map-tooltip__row"><span>Velocity</span><span>${p.velocity_kms != null ? p.velocity_kms + ' km/s' : '—'}</span></div>
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', SATELLITES_LAYER, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });

      // ── Sentiment circle hover ────────────────────────────────────────────
      map.on('mouseenter', SENTIMENT_LAYER_CIRCLES, (e) => {
        map.getCanvas().style.cursor = 'pointer';
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const sentimentEmoji =
          p.sentiment_label === 'negative' ? '🔴' :
          p.sentiment_label === 'positive' ? '🟢' : '🟡';
        const html = `
          <div class="map-tooltip">
            <div class="map-tooltip__title">${sentimentEmoji} ${escapeHtml(p.place_name || 'Unknown location')}</div>
            <div class="map-tooltip__row"><span>Sentiment</span><span>${escapeHtml(p.sentiment_label || '—')}</span></div>
            <div class="map-tooltip__row"><span>Score</span><span>${p.sentiment_score ?? '—'}</span></div>
            <div class="map-tooltip__row"><span>Posts</span><span>${p.post_count ?? 0}</span></div>
          </div>`;
        showTooltip(map, tooltipRef, f.geometry.coordinates as [number, number], html);
      });
      map.on('mouseleave', SENTIMENT_LAYER_CIRCLES, () => {
        map.getCanvas().style.cursor = '';
        tooltipRef.current?.remove();
        tooltipRef.current = null;
      });
      map.on('click', SENTIMENT_LAYER_CIRCLES, (e) => {
        const f = e.features?.[0];
        if (!f || f.geometry.type !== 'Point') return;
        const p = f.properties ?? {};
        const sentimentColor =
          p.sentiment_label === 'negative' ? '#ef4444' :
          p.sentiment_label === 'positive' ? '#22c55e' : '#eab308';
        const sentimentEmoji =
          p.sentiment_label === 'negative' ? '🔴' :
          p.sentiment_label === 'positive' ? '🟢' : '🟡';
        const html = `
          <div class="map-popup">
            <div class="map-popup__source-badge" style="color:${sentimentColor}">
              <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${sentimentColor};flex-shrink:0"></span>
              SENTIMENT ANALYSIS
            </div>
            <div class="map-popup__author">${escapeHtml(p.place_name || 'Unknown location')}</div>
            <div class="map-popup__content">
              ${sentimentEmoji} <strong>${escapeHtml(p.sentiment_label || 'neutral')}</strong>
              (score: ${p.sentiment_score ?? 0})<br>
              Posts analyzed: <strong>${p.post_count ?? 0}</strong>
            </div>
            <div class="map-popup__footer">
              <a class="map-popup__link" data-navigate="/feed?source=&q=${encodeURIComponent(p.place_name || '')}" href="#">View in Feed →</a>
            </div>
          </div>`;
        if (popupRef.current) popupRef.current.remove();
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '280px', offset: 10 })
          .setLngLat(f.geometry.coordinates as [number, number])
          .setHTML(html)
          .addTo(map);
      });
    });

    // Global handler for data-navigate links in popups (avoids full page reload which wipes auth)
    map.getContainer().addEventListener('click', (evt) => {
      const link = (evt.target as HTMLElement).closest('[data-navigate]');
      if (link) {
        evt.preventDefault();
        const path = link.getAttribute('data-navigate');
        if (path) navigate(path);
      }
    });

    mapRef.current = map;
    (window as unknown as Record<string, unknown>).__owMap = map;
    return () => {
      map.remove();
      mapRef.current = null;
      mapReadyRef.current = false;
    };
  }, []);

  // Update events GeoJSON
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    const source = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
    if (!source) return;
    source.setData(eventsToGeoJSON(filteredEvents));
  }, [filteredEvents, mapReady]);

  // Toggle cluster layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    const vis = filters.showClusters ? 'visible' : 'none';
    if (map.getLayer(CLUSTER_LAYER)) map.setLayoutProperty(CLUSTER_LAYER, 'visibility', vis);
    if (map.getLayer(CLUSTER_COUNT_LAYER)) map.setLayoutProperty(CLUSTER_COUNT_LAYER, 'visibility', vis);
    if (map.getLayer(UNCLUSTERED_LAYER)) map.setLayoutProperty(UNCLUSTERED_LAYER, 'visibility', vis);
  }, [filters.showClusters]);

  // Toggle heatmap
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReadyRef.current) return;
    const vis = filters.showHeatmap ? 'visible' : 'none';
    if (map.getLayer(HEATMAP_LAYER)) map.setLayoutProperty(HEATMAP_LAYER, 'visibility', vis);
  }, [filters.showHeatmap]);

  // Fullscreen
  const handleFullscreen = useCallback(() => {
    const el = mapContainer.current?.parentElement;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen?.();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen?.();
      setIsFullscreen(false);
    }
  }, []);

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  const handleFiltersChange = useCallback((partial: Partial<SidebarFilters>) => {
    setFilters((prev) => ({ ...prev, ...partial }));
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="map-container">
      <div ref={mapContainer} className="map-canvas" />

      {/* Backdrop for mobile panels */}
      <div
        className={`map-panel-backdrop${mobileSidebarOpen || mobileLayersOpen ? ' map-panel-backdrop--visible' : ''}`}
        onClick={() => { setMobileSidebarOpen(false); setMobileLayersOpen(false); }}
      />

      <MapSidebar
        collapsed={sidebarCollapsed && !mobileSidebarOpen}
        onToggle={() => setSidebarCollapsed((v) => !v)}
        filters={filters}
        onFiltersChange={handleFiltersChange}
        stats={stats}
        extraClassName={mobileSidebarOpen ? 'map-sidebar--mobile-sheet' : undefined}
      />

      <MapControls
        zoom={zoom}
        eventCount={filteredEvents.length}
        loading={loading}
        onRefresh={fetchEvents}
        onFullscreen={handleFullscreen}
        isFullscreen={isFullscreen}
        baseLayer={baseLayer}
        onBaseLayerChange={setBaseLayer}
        layerPanelOpen={!layerPanelCollapsed || mobileLayersOpen}
      />

      {/* ── Mobile FABs (hidden on desktop via CSS) ── */}
      <div className="map-fabs">
        <button
          className={`map-fab${mobileSidebarOpen ? ' map-fab--active' : ''}`}
          onClick={() => { setMobileSidebarOpen((v) => !v); setMobileLayersOpen(false); }}
        >
          🔍 Filters
        </button>
        <button
          className={`map-fab${mobileLayersOpen ? ' map-fab--active' : ''}`}
          onClick={() => { setMobileLayersOpen((v) => !v); setMobileSidebarOpen(false); }}
        >
          ☰ Layers
        </button>
      </div>

      {/* ── Event Detail Panel (slides in from right) ─────────────────────── */}
      {selectedEvent && (
        <div className="map-event-detail">
          <div className="map-event-detail__header">
            <span className="map-event-detail__title">Event Detail</span>
            <button className="map-event-detail__close" onClick={() => setSelectedEvent(null)}>✕</button>
          </div>

          <div className="map-event-detail__body">
            <div className="map-event-detail__source-row">
              <span className="map-event-detail__source-badge" style={{ color: getSourceColor(selectedEvent.post.source_type) }}>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: getSourceColor(selectedEvent.post.source_type) }} />
                {selectedEvent.post.source_type.toUpperCase()}
              </span>
              <span className="map-event-detail__time">{relativeTime(selectedEvent.post.timestamp)}</span>
            </div>

            {selectedEvent.post.author && (
              <div className="map-event-detail__author">{selectedEvent.post.author}</div>
            )}

            {selectedEvent.place_name && (
              <div className="map-event-detail__place">📍 {selectedEvent.place_name}</div>
            )}

            <div className="map-event-detail__content">
              {selectedEvent.post.content?.replace(/\*\*/g, '') || 'No content'}
            </div>

            <div className="map-event-detail__meta">
              <div className="map-event-detail__meta-row">
                <span className="map-event-detail__meta-label">Coordinates</span>
                <span className="map-event-detail__meta-value">{selectedEvent.lat.toFixed(4)}, {selectedEvent.lng.toFixed(4)}</span>
              </div>
              <div className="map-event-detail__meta-row">
                <span className="map-event-detail__meta-label">Confidence</span>
                <span className="map-event-detail__meta-value">{(selectedEvent.confidence * 100).toFixed(0)}%</span>
              </div>
              {selectedEvent.precision && (
                <div className="map-event-detail__meta-row">
                  <span className="map-event-detail__meta-label">Precision</span>
                  <span className="map-event-detail__meta-value">{selectedEvent.precision}</span>
                </div>
              )}
              <div className="map-event-detail__meta-row">
                <span className="map-event-detail__meta-label">Timestamp</span>
                <span className="map-event-detail__meta-value">{new Date(selectedEvent.post.timestamp).toLocaleString()}</span>
              </div>
            </div>

            <a className="map-event-detail__feed-link" href={`/feed?post=${selectedEvent.post.id}`}>
              View in Feed →
            </a>
          </div>
        </div>
      )}

      {/* ── Layers Panel (right side) ─────────────────────────────────────── */}
      <div className={`map-layers-panel${layerPanelCollapsed && !mobileLayersOpen ? ' map-layers-panel--collapsed' : ''}${mobileLayersOpen ? ' map-layers-panel--mobile-sheet' : ''}`}>
        <button
          className="map-layers-panel__toggle"
          onClick={() => setLayerPanelCollapsed((v) => !v)}
          title="Toggle layers panel"
        >
          {layerPanelCollapsed ? '◁' : '▷'}
        </button>

        <div className="map-layers-panel__header">
          <span className="map-layers-panel__title">Layers</span>
        </div>

        <div className="map-layers-panel__body">
          {/* ── OSINT Events ── */}
          <div className="map-layers-section">
            <div className="map-layers-section__label">OSINT Events</div>

            <label className="map-layer-row">
              <span className="map-layer-row__name">Events</span>
              <span className="map-layer-row__count">{filteredEvents.length}</span>
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={filters.showClusters}
                  onChange={(e) => handleFiltersChange({ showClusters: e.target.checked })}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            <label className="map-layer-row map-layer-row--sub">
              <span className="map-layer-row__name" style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                Include country-level
              </span>
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={includeCountryLevel}
                  onChange={(e) => setIncludeCountryLevel(e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            <label className="map-layer-row">
              <span className="map-layer-row__name">Heatmap</span>
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={filters.showHeatmap}
                  onChange={(e) => handleFiltersChange({ showHeatmap: e.target.checked })}
                />
                <span className="toggle-slider" />
              </span>
            </label>
          </div>

          {/* ── Real-Time Tracking ── */}
          <div className="map-layers-section">
            <div className="map-layers-section__label">Real-Time Tracking</div>

            {([
              { key: 'flights' as const, label: '✈ Flights', color: '#3b82f6' },
              { key: 'ships' as const, label: '⚓ Ships', color: '#06b6d4' },
              { key: 'firms' as const, label: '🔥 FIRMS Thermal', color: '#f97316' },
            ] as const).map(({ key, label, color }) => (
              <label key={key} className="map-layer-row">
                <span className="map-layer-row__dot" style={{ background: color }} />
                <span className="map-layer-row__name">{label}</span>
                {layers[key] && (
                  <span className={`map-layer-row__count${layerCounts[key] === 0 ? ' map-layer-row__count--zero' : ''}`}>
                    {layerCounts[key] || 0}
                  </span>
                )}
                <span className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={layers[key]}
                    onChange={(e) => toggleLayer(key, e.target.checked)}
                  />
                  <span className="toggle-slider" />
                </span>
              </label>
            ))}
            {layers.ships && layerCounts.ships === 0 && (
              <div className="map-layer-hint">Requires AIS API key — <a href="/settings/credentials" onClick={(e) => { e.preventDefault(); navigate('/settings/credentials'); }}>Configure</a></div>
            )}
          </div>

          {/* ── Intel Overlays ── */}
          <div className="map-layers-section">
            <div className="map-layers-section__label">Intel Overlays</div>

            <label className="map-layer-row">
              <span className="map-layer-row__dot" style={{ background: '#ef4444' }} />
              <span className="map-layer-row__name">Frontlines</span>
              {layers.frontlines && (
                <span className={`map-layer-row__count${layerCounts.frontlines === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.frontlines || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.frontlines}
                  onChange={(e) => toggleLayer('frontlines', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {layers.frontlines && frontlineSources.length > 0 && (
              <div className="frontline-source-selector">
                <div className="frontline-source-selector__label">Source</div>
                <select
                  className="frontline-source-selector__select"
                  value={frontlineSource}
                  onChange={(e) => setFrontlineSource(e.target.value)}
                >
                  {frontlineSources.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}{s.cached ? ' ✓' : ''}
                    </option>
                  ))}
                </select>
                {frontlineSources.find((s) => s.id === frontlineSource) && (
                  <div className="frontline-source-selector__desc">
                    {frontlineSources.find((s) => s.id === frontlineSource)!.description}
                  </div>
                )}
              </div>
            )}

            <label className="map-layer-row">
              <span className="map-layer-row__dot" style={{ background: '#22c55e' }} />
              <span className="map-layer-row__name">🛰 Satellites</span>
              {layers.satellites && (
                <span className={`map-layer-row__count${layerCounts.satellites === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.satellites || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.satellites}
                  onChange={(e) => toggleLayer('satellites', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {/* Sentiment Heatmap */}
            <label className="map-layer-row">
              <span className="map-layer-row__dot" style={{ background: '#eab308' }} />
              <span className="map-layer-row__name">🎯 Sentiment</span>
              {layers.sentiment && (
                <span className={`map-layer-row__count${layerCounts.sentiment === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.sentiment || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.sentiment}
                  onChange={(e) => toggleLayer('sentiment', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {layers.sentiment && (
              <div className="sentiment-controls">
                <div className="sentiment-controls__row">
                  <span className="sentiment-controls__label">Time window</span>
                  <select
                    className="sentiment-controls__select"
                    value={sentimentHours}
                    onChange={(e) => setSentimentHours(Number(e.target.value))}
                  >
                    <option value={6}>6h</option>
                    <option value={24}>24h</option>
                    <option value={48}>48h</option>
                    <option value={72}>3d</option>
                    <option value={168}>7d</option>
                  </select>
                </div>
                <div className="sentiment-legend">
                  <div className="sentiment-legend__title">Legend</div>
                  <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#ef4444' }} />High Threat (&lt;−0.3)</div>
                  <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#f97316' }} />Elevated (−0.3 to −0.1)</div>
                  <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#eab308' }} />Neutral (−0.1 to 0.1)</div>
                  <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#84cc16' }} />Positive (0.1 to 0.3)</div>
                  <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#22c55e' }} />Very Positive (&gt;0.3)</div>
                </div>
              </div>
            )}

            {/* GDELT Media Attention */}
            <label className="map-layer-row">
              <span className="map-layer-row__dot" style={{ background: '#f97316' }} />
              <span className="map-layer-row__name">📰 Media Attention</span>
              {layers.gdelt && (
                <span className={`map-layer-row__count${layerCounts.gdelt === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.gdelt || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.gdelt}
                  onChange={(e) => toggleLayer('gdelt', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {layers.gdelt && (
              <div className="sentiment-controls">
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, marginBottom: 4 }}>
                  GDELT Keyword
                </div>
                <div className="gdelt-keyword-input">
                  <input
                    type="text"
                    placeholder="e.g. conflict"
                    value={gdeltInputValue}
                    onChange={(e) => {
                      setGdeltInputValue(e.target.value);
                      if (gdeltDebounceRef.current) clearTimeout(gdeltDebounceRef.current);
                      gdeltDebounceRef.current = setTimeout(() => {
                        if (e.target.value.trim()) {
                          setGdeltKeyword(e.target.value.trim());
                        }
                      }, 800);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && gdeltInputValue.trim()) {
                        if (gdeltDebounceRef.current) clearTimeout(gdeltDebounceRef.current);
                        setGdeltKeyword(gdeltInputValue.trim());
                      }
                    }}
                  />
                </div>
                <div className="gdelt-presets">
                  {['conflict', 'nuclear', 'terrorism', 'protest', 'cyber attack'].map((preset) => (
                    <button
                      key={preset}
                      className={`gdelt-preset-btn${gdeltKeyword === preset ? ' gdelt-preset-btn--active' : ''}`}
                      onClick={() => {
                        setGdeltInputValue(preset);
                        setGdeltKeyword(preset);
                      }}
                    >
                      {preset}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ── Conflict Intelligence ── */}
          <div className="map-layers-section">
            <div className="map-layers-section__label">Conflict Intelligence</div>

            <label className="map-layer-row">
              <span className="map-layer-row__dot" style={{ background: '#ef4444' }} />
              <span className="map-layer-row__name">⚔️ Conflict Events</span>
              {layers.acled && (
                <span className={`map-layer-row__count${layerCounts.acled === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.acled || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.acled}
                  onChange={(e) => toggleLayer('acled', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {layers.acled && layerCounts.acled === 0 && (
              <div className="map-layer-hint">Requires ACLED API key — <a href="/settings/credentials" onClick={(e) => { e.preventDefault(); navigate('/settings/credentials'); }}>Configure</a></div>
            )}

            {layers.acled && layerCounts.acled > 0 && (
              <div className="sentiment-legend" style={{ marginTop: 6 }}>
                <div className="sentiment-legend__title">Event Types</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#ef4444' }} />Battles</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#f97316' }} />Explosions/Remote Violence</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#991b1b' }} />Violence vs Civilians</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#eab308' }} />Protests</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#a855f7' }} />Riots</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#3b82f6' }} />Strategic Developments</div>
              </div>
            )}

            {/* NOTAM row */}
            <label className="map-layer-row" style={{ marginTop: 8 }}>
              <span className="map-layer-row__dot" style={{
                background: 'transparent',
                border: '5px solid transparent',
                borderBottom: '9px solid #fbbf24',
                width: 0,
                height: 0,
                borderRadius: 0,
                display: 'inline-block',
                marginRight: 4,
              }} />
              <span className="map-layer-row__name">⚠️ NOTAMs</span>
              {layers.notams && (
                <span className={`map-layer-row__count${layerCounts.notams === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.notams || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.notams}
                  onChange={(e) => toggleLayer('notams', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {layers.notams && layerCounts.notams === 0 && (
              <div className="map-layer-hint">Polling {22} military FIRs. NOTAMs appear as data is collected.</div>
            )}

            {layers.notams && layerCounts.notams > 0 && (
              <div className="sentiment-legend" style={{ marginTop: 6 }}>
                <div className="sentiment-legend__title">NOTAM Types</div>
                <div className="sentiment-legend__row">
                  <span style={{ display: 'inline-block', width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderBottom: '9px solid #f97316', marginRight: 6, verticalAlign: 'middle' }} />
                  Military/Exercise
                </div>
                <div className="sentiment-legend__row">
                  <span style={{ display: 'inline-block', width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderBottom: '9px solid #ef4444', marginRight: 6, verticalAlign: 'middle' }} />
                  GPS Jamming
                </div>
                <div className="sentiment-legend__row">
                  <span style={{ display: 'inline-block', width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderBottom: '9px solid #fbbf24', marginRight: 6, verticalAlign: 'middle' }} />
                  TFR / Standard
                </div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                  22 military FIRs · refreshes every 15 min
                </div>
              </div>
            )}
          </div>

          {/* ── Fused Intelligence ── */}
          <div className="map-layers-section">
            <div className="map-layers-section__label">Fused Intelligence</div>

            <label className="map-layer-row">
              <span className="map-layer-row__dot" style={{ background: 'linear-gradient(135deg, #ef4444, #3b82f6)', borderRadius: 0, transform: 'rotate(45deg)', width: 8, height: 8 }} />
              <span className="map-layer-row__name">◆ Multi-Source Fusion</span>
              {layers.fusion && (
                <span className={`map-layer-row__count${layerCounts.fusion === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.fusion || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.fusion}
                  onChange={(e) => toggleLayer('fusion', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {layers.fusion && layerCounts.fusion === 0 && (
              <div className="map-layer-hint">No multi-source clusters detected yet. Events from 2+ sources within 50km/6h will appear here.</div>
            )}

            {layers.fusion && layerCounts.fusion > 0 && (
              <div className="sentiment-legend" style={{ marginTop: 6 }}>
                <div className="sentiment-legend__title">Severity</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#ef4444', borderRadius: 0, transform: 'rotate(45deg)', width: 8, height: 8, display: 'inline-block', marginRight: 6 }} />Flash (4+ sources or 10+ posts)</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#f97316', borderRadius: 0, transform: 'rotate(45deg)', width: 8, height: 8, display: 'inline-block', marginRight: 6 }} />Urgent (3 sources)</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#3b82f6', borderRadius: 0, transform: 'rotate(45deg)', width: 8, height: 8, display: 'inline-block', marginRight: 6 }} />Routine (2 sources)</div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                  Auto-detected every 5 min within 50km / 6h windows
                </div>
              </div>
            )}
          </div>

          {/* ── Maritime Domain Awareness ── */}
          <div className="map-layers-section">
            <div className="map-layers-section__label">Maritime Domain Awareness</div>

            <label className="map-layer-row">
              <span className="map-layer-row__dot" style={{ background: '#f97316' }} />
              <span className="map-layer-row__name">🚨 Maritime Events</span>
              {layers.maritime && (
                <span className={`map-layer-row__count${layerCounts.maritime === 0 ? ' map-layer-row__count--zero' : ''}`}>{layerCounts.maritime || 0}</span>
              )}
              <span className="toggle-switch">
                <input
                  type="checkbox"
                  checked={layers.maritime}
                  onChange={(e) => toggleLayer('maritime', e.target.checked)}
                />
                <span className="toggle-slider" />
              </span>
            </label>

            {layers.maritime && layerCounts.maritime === 0 && (
              <div className="map-layer-hint">No maritime events detected yet. Events appear as AIS data is collected.</div>
            )}

            {layers.maritime && (
              <div className="sentiment-legend" style={{ marginTop: 6 }}>
                <div className="sentiment-legend__title">Event Types</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#ef4444' }} />🚫 Dark Ship (AIS off)</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#f97316' }} />🔄 STS Transfer</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#3b82f6' }} />⚓ Port Call</div>
                <div className="sentiment-legend__row"><span className="sentiment-legend__dot" style={{ background: '#64748b' }} />🏭 Monitored Port</div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                  Analysis runs every 15 min — requires AIS data
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

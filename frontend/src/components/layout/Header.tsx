import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useWebSocket } from '../../hooks/useWebSocket';
import { useAlertStore } from '../../stores/alertStore';
import { StatusDot } from '../common/StatusDot';
import api from '../../services/api';
import '../../styles/alerts.css';
import '../../styles/search.css';

// ── Types ──────────────────────────────────────────────────────────────────

interface PostResult {
  id: string;
  source_type: string;
  author: string;
  snippet: string;
  timestamp: string | null;
}

interface EntityResult {
  id: string;
  name: string;
  type: string;
  mention_count: number;
}

interface EventResult {
  id: string;
  place_name: string;
  lat: number | null;
  lng: number | null;
  post_id: string;
  timestamp: string | null;
}

interface BriefResult {
  id: string;
  title: string;
  model_id: string;
  created_at: string | null;
  snippet: string;
}

interface SearchResults {
  query: string;
  results: {
    posts: PostResult[];
    entities: EntityResult[];
    events: EventResult[];
    briefs: BriefResult[];
  };
  counts: Record<string, number>;
  total: number;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function highlight(text: string, query: string): React.ReactNode {
  if (!query || !text) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase()
      ? <mark key={i}>{part}</mark>
      : part
  );
}

function relativeTime(isoStr: string | null): string {
  if (!isoStr) return '';
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Search Dropdown ──────────────────────────────────────────────────────────

interface DropdownProps {
  results: SearchResults;
  query: string;
  onClose: () => void;
}

function SearchDropdown({ results, query, onClose }: DropdownProps) {
  const navigate = useNavigate();

  const hasAny = results.total > 0;

  const go = (path: string) => {
    navigate(path);
    onClose();
  };

  const LIMIT = 5;

  return (
    <div className="search-dropdown" role="listbox">
      {!hasAny && (
        <div className="search-dropdown__empty">
          <div className="search-dropdown__empty-icon">🔍</div>
          No results for &ldquo;{query}&rdquo;
        </div>
      )}

      {results.results.posts.length > 0 && (
        <div className="search-result-group">
          <div className="search-result-group__header">
            Posts
            <span className="search-result-group__count">{results.counts.posts}</span>
          </div>
          {results.results.posts.slice(0, LIMIT).map((p) => (
            <button
              key={p.id}
              className="search-result-item"
              onClick={() => go(`/feed?post=${p.id}`)}
              role="option"
            >
              <span className="search-result-item__title">
                {highlight(p.snippet || p.author || 'Post', query)}
              </span>
              <span className="search-result-item__meta">
                <span className={`search-result-item__badge search-result-item__badge--post`}>
                  {p.source_type}
                </span>
                {p.author && <span>{p.author}</span>}
                {p.timestamp && <span>{relativeTime(p.timestamp)}</span>}
              </span>
            </button>
          ))}
          {results.counts.posts > LIMIT && (
            <button
              className="search-result-viewall"
              onClick={() => go(`/search?q=${encodeURIComponent(query)}&type=posts`)}
            >
              View all {results.counts.posts} posts →
            </button>
          )}
        </div>
      )}

      {results.results.entities.length > 0 && (
        <div className="search-result-group">
          <div className="search-result-group__header">
            Entities
            <span className="search-result-group__count">{results.counts.entities}</span>
          </div>
          {results.results.entities.slice(0, LIMIT).map((e) => (
            <button
              key={e.id}
              className="search-result-item"
              onClick={() => go(`/entities/${e.id}`)}
              role="option"
            >
              <span className="search-result-item__title">
                {highlight(e.name, query)}
              </span>
              <span className="search-result-item__meta">
                <span className={`search-result-item__badge search-result-item__badge--entity-${e.type}`}>
                  {e.type}
                </span>
                <span>{e.mention_count} mention{e.mention_count !== 1 ? 's' : ''}</span>
              </span>
            </button>
          ))}
          {results.counts.entities > LIMIT && (
            <button
              className="search-result-viewall"
              onClick={() => go(`/search?q=${encodeURIComponent(query)}&type=entities`)}
            >
              View all {results.counts.entities} entities →
            </button>
          )}
        </div>
      )}

      {results.results.events.length > 0 && (
        <div className="search-result-group">
          <div className="search-result-group__header">
            Events
            <span className="search-result-group__count">{results.counts.events}</span>
          </div>
          {results.results.events.slice(0, LIMIT).map((ev) => (
            <button
              key={ev.id}
              className="search-result-item"
              onClick={() => go(`/map?lat=${ev.lat}&lng=${ev.lng}&post=${ev.post_id}`)}
              role="option"
            >
              <span className="search-result-item__title">
                {highlight(ev.place_name, query)}
              </span>
              <span className="search-result-item__meta">
                <span className="search-result-item__badge search-result-item__badge--event">
                  EVENT
                </span>
                {ev.lat != null && ev.lng != null && (
                  <span>{ev.lat.toFixed(2)}, {ev.lng.toFixed(2)}</span>
                )}
                {ev.timestamp && <span>{relativeTime(ev.timestamp)}</span>}
              </span>
            </button>
          ))}
          {results.counts.events > LIMIT && (
            <button
              className="search-result-viewall"
              onClick={() => go(`/search?q=${encodeURIComponent(query)}&type=events`)}
            >
              View all {results.counts.events} events →
            </button>
          )}
        </div>
      )}

      {results.results.briefs.length > 0 && (
        <div className="search-result-group">
          <div className="search-result-group__header">
            Briefs
            <span className="search-result-group__count">{results.counts.briefs}</span>
          </div>
          {results.results.briefs.slice(0, LIMIT).map((b) => (
            <button
              key={b.id}
              className="search-result-item"
              onClick={() => go(`/briefs`)}
              role="option"
            >
              <span className="search-result-item__title">
                {highlight(b.title, query)}
              </span>
              <span className="search-result-item__meta">
                <span className="search-result-item__badge search-result-item__badge--brief">
                  BRIEF
                </span>
                <span>{b.model_id}</span>
                {b.created_at && <span>{relativeTime(b.created_at)}</span>}
              </span>
              {b.snippet && (
                <span className="search-result-item__snippet">
                  {highlight(b.snippet, query)}
                </span>
              )}
            </button>
          ))}
          {results.counts.briefs > LIMIT && (
            <button
              className="search-result-viewall"
              onClick={() => go(`/search?q=${encodeURIComponent(query)}&type=briefs`)}
            >
              View all {results.counts.briefs} briefs →
            </button>
          )}
        </div>
      )}

      {hasAny && (
        <div style={{ borderTop: '1px solid var(--border)' }}>
          <button
            className="search-result-viewall"
            style={{ textAlign: 'center', width: '100%', padding: '10px' }}
            onClick={() => go(`/search?q=${encodeURIComponent(query)}`)}
          >
            View all {results.total} results for &ldquo;{query}&rdquo;
          </button>
        </div>
      )}
    </div>
  );
}

// ── Global Search Bar ────────────────────────────────────────────────────────

function GlobalSearch() {
  const [value, setValue] = useState('');
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchResults | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigate = useNavigate();

  // Cmd+K / Ctrl+K shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Click-outside to close
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) {
      setResults(null);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const res = await api.get('/search', { params: { q, limit: 10 } });
      setResults(res.data as SearchResults);
      setOpen(true);
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value;
    setValue(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(q), 300);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setOpen(false);
      inputRef.current?.blur();
    }
    if (e.key === 'Enter' && value.length >= 2) {
      setOpen(false);
      navigate(`/search?q=${encodeURIComponent(value)}`);
    }
  };

  return (
    <div className="search-bar" ref={containerRef}>
      <div className="search-bar__input-wrap">
        <span className="search-bar__icon">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="6.5" cy="6.5" r="5" stroke="currentColor" strokeWidth="1.5"/>
            <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </span>
        <input
          ref={inputRef}
          className="search-bar__input"
          type="search"
          placeholder="Search posts, entities, events..."
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (results) setOpen(true); }}
          autoComplete="off"
          spellCheck={false}
        />
        {loading
          ? <span className="search-bar__spinner" />
          : <span className="search-bar__shortcut">⌘K</span>
        }
      </div>
      {open && results && (
        <SearchDropdown
          results={results}
          query={value}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

// ── Route titles map ─────────────────────────────────────────────────────────

const ROUTE_TITLES: Record<string, string> = {
  '/feed': 'Live Feed',
  '/map': 'Map',
  '/entities': 'Entities',
  '/briefs': 'Briefs',
  '/search': 'Search',
  '/settings/sources': 'Sources',
  '/settings/credentials': 'Credentials',
  '/settings/alerts': 'Alert Rules',
  '/settings/telegram': 'Telegram Setup',
};

interface HeaderProps {
  onSearch?: (value: string) => void;
  searchValue?: string;
}

export function Header({ onSearch, searchValue = '' }: HeaderProps) {
  const location = useLocation();
  const { connected, reconnecting } = useWebSocket();
  const unacknowledgedCount = useAlertStore((s) => s.unacknowledgedCount);

  const title = ROUTE_TITLES[location.pathname] ?? 'Orthanc';
  const wsStatus = connected ? 'active' : reconnecting ? 'warning' : 'error';
  const wsLabel = connected ? 'Live' : reconnecting ? 'Reconnecting...' : 'Disconnected';

  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 20px',
      height: '48px',
      borderBottom: '1px solid var(--border)',
      backgroundColor: 'var(--bg-surface)',
      flexShrink: 0,
      gap: '12px',
    }}>
      <span style={{
        fontSize: '13px',
        fontWeight: 600,
        color: 'var(--text-primary)',
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        flexShrink: 0,
      }}>
        {title}
      </span>

      {/* Global search — always visible */}
      <GlobalSearch />

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
        {/* Legacy per-page search (keep for backward compat) */}
        {onSearch !== undefined && (
          <input
            className="input"
            style={{ width: '180px', height: '30px', padding: '4px 10px' }}
            type="text"
            placeholder="Filter..."
            value={searchValue}
            onChange={(e) => onSearch(e.target.value)}
          />
        )}

        {/* Alert bell */}
        <Link to="/settings/alerts" className="alert-bell" title="Alert Rules">
          🔔
          {unacknowledgedCount > 0 && (
            <span className="alert-bell-count">
              {unacknowledgedCount > 99 ? '99+' : unacknowledgedCount}
            </span>
          )}
        </Link>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: 'var(--text-muted)' }}>
          <StatusDot status={wsStatus} />
          <span>{wsLabel}</span>
        </div>
      </div>
    </header>
  );
}



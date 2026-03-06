import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api from '../../services/api';
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

type TabType = 'all' | 'posts' | 'entities' | 'events' | 'briefs';

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
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatTs(isoStr: string | null): string {
  if (!isoStr) return '';
  return new Date(isoStr).toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

// ── Result Cards ─────────────────────────────────────────────────────────────

function PostCard({ p, query }: { p: PostResult; query: string }) {
  const navigate = useNavigate();
  return (
    <div
      className="search-card"
      onClick={() => navigate(`/feed?post=${p.id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && navigate(`/feed?post=${p.id}`)}
    >
      <div className="search-card__header">
        <span className="search-result-item__badge search-result-item__badge--post">{p.source_type}</span>
        {p.author && <span className="search-card__title">{p.author}</span>}
      </div>
      {p.snippet && (
        <p className="search-card__snippet">{highlight(p.snippet, query)}</p>
      )}
      <div className="search-card__meta">
        {p.timestamp && <span title={formatTs(p.timestamp)}>{relativeTime(p.timestamp)}</span>}
        <span style={{ opacity: 0.4, fontSize: '10px' }}>{p.id.slice(0, 8)}…</span>
      </div>
    </div>
  );
}

function EntityCard({ e, query }: { e: EntityResult; query: string }) {
  const navigate = useNavigate();
  return (
    <div
      className="search-card"
      onClick={() => navigate(`/entities/${e.id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(ev) => ev.key === 'Enter' && navigate(`/entities/${e.id}`)}
    >
      <div className="search-card__header">
        <span className={`search-result-item__badge search-result-item__badge--entity-${e.type}`}>{e.type}</span>
        <span className="search-card__title">{highlight(e.name, query)}</span>
      </div>
      <div className="search-card__meta">
        <span>{e.mention_count} mention{e.mention_count !== 1 ? 's' : ''}</span>
      </div>
    </div>
  );
}

function EventCard({ ev, query }: { ev: EventResult; query: string }) {
  const navigate = useNavigate();
  const mapUrl = ev.lat != null && ev.lng != null
    ? `/map?lat=${ev.lat}&lng=${ev.lng}&post=${ev.post_id}`
    : `/map`;
  return (
    <div
      className="search-card"
      onClick={() => navigate(mapUrl)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && navigate(mapUrl)}
    >
      <div className="search-card__header">
        <span className="search-result-item__badge search-result-item__badge--event">GEO</span>
        <span className="search-card__title">{highlight(ev.place_name, query)}</span>
      </div>
      <div className="search-card__meta">
        {ev.lat != null && ev.lng != null && (
          <span>{ev.lat.toFixed(4)}°, {ev.lng.toFixed(4)}°</span>
        )}
        {ev.timestamp && <span title={formatTs(ev.timestamp)}>{relativeTime(ev.timestamp)}</span>}
      </div>
    </div>
  );
}

function BriefCard({ b, query }: { b: BriefResult; query: string }) {
  const navigate = useNavigate();
  return (
    <div
      className="search-card"
      onClick={() => navigate('/briefs')}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && navigate('/briefs')}
    >
      <div className="search-card__header">
        <span className="search-result-item__badge search-result-item__badge--brief">BRIEF</span>
        <span className="search-card__title">{highlight(b.title, query)}</span>
      </div>
      {b.snippet && (
        <p className="search-card__snippet">{highlight(b.snippet, query)}</p>
      )}
      <div className="search-card__meta">
        <span>{b.model_id}</span>
        {b.created_at && <span title={formatTs(b.created_at)}>{relativeTime(b.created_at)}</span>}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export function SearchResults() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const initialQ = searchParams.get('q') || '';
  const initialTab = (searchParams.get('type') as TabType) || 'all';

  const [inputValue, setInputValue] = useState(initialQ);
  const [query, setQuery] = useState(initialQ);
  const [activeTab, setActiveTab] = useState<TabType>(initialTab);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchResults | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string, tab: TabType) => {
    if (!q.trim()) { setResults(null); return; }
    setLoading(true);
    try {
      const params: Record<string, string | number> = { q, limit: 50 };
      if (tab !== 'all') params.types = tab;
      const res = await api.get('/search', { params });
      setResults(res.data as SearchResults);
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Sync URL → state
  useEffect(() => {
    const q = searchParams.get('q') || '';
    const tab = (searchParams.get('type') as TabType) || 'all';
    setInputValue(q);
    setQuery(q);
    setActiveTab(tab);
    if (q) doSearch(q, tab);
  }, [searchParams, doSearch]);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setInputValue(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearchParams({ q: val, ...(activeTab !== 'all' ? { type: activeTab } : {}) });
    }, 400);
  };

  const handleTabChange = (tab: TabType) => {
    setActiveTab(tab);
    setSearchParams({ q: inputValue, ...(tab !== 'all' ? { type: tab } : {}) });
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      navigate(-1);
    }
  };

  const counts = results?.counts ?? {};
  const tabCounts: Record<TabType, number> = {
    all: results?.total ?? 0,
    posts: counts.posts ?? 0,
    entities: counts.entities ?? 0,
    events: counts.events ?? 0,
    briefs: counts.briefs ?? 0,
  };

  const tabs: { key: TabType; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'posts', label: 'Posts' },
    { key: 'entities', label: 'Entities' },
    { key: 'events', label: 'Events' },
    { key: 'briefs', label: 'Briefs' },
  ];

  const showPosts = (activeTab === 'all' || activeTab === 'posts') && (results?.results.posts.length ?? 0) > 0;
  const showEntities = (activeTab === 'all' || activeTab === 'entities') && (results?.results.entities.length ?? 0) > 0;
  const showEvents = (activeTab === 'all' || activeTab === 'events') && (results?.results.events.length ?? 0) > 0;
  const showBriefs = (activeTab === 'all' || activeTab === 'briefs') && (results?.results.briefs.length ?? 0) > 0;
  const nothingFound = results && results.total === 0 && !loading;

  return (
    <div className="search-page">
      {/* Header */}
      <div className="search-page__header">
        <div className="search-page__input-row">
          <input
            className="search-page__input"
            type="search"
            placeholder="Search posts, entities, events, briefs..."
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            autoFocus
            autoComplete="off"
          />
          {loading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-muted)', fontSize: '13px' }}>
              <div className="search-page__spinner" />
              Searching…
            </div>
          )}
          {results && !loading && (
            <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              {results.total} result{results.total !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        {/* Tabs */}
        <div className="search-page__tabs">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={`search-page__tab${activeTab === tab.key ? ' search-page__tab--active' : ''}`}
              onClick={() => handleTabChange(tab.key)}
            >
              {tab.label}
              {tabCounts[tab.key] > 0 && (
                <span style={{
                  marginLeft: '5px',
                  background: 'var(--bg-primary)',
                  border: '1px solid var(--border)',
                  borderRadius: '10px',
                  padding: '0 5px',
                  fontSize: '10px',
                  color: 'var(--text-muted)',
                }}>
                  {tabCounts[tab.key]}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="search-page__body">
        {!query && (
          <div className="search-page__empty">
            <div className="search-page__empty-icon">🔍</div>
            Enter a search term to begin
          </div>
        )}

        {loading && (
          <div className="search-page__loading">
            <div className="search-page__spinner" />
            Searching across all data…
          </div>
        )}

        {nothingFound && (
          <div className="search-page__empty">
            <div className="search-page__empty-icon">📭</div>
            No results found for &ldquo;{query}&rdquo;
            <br />
            <span style={{ fontSize: '12px', marginTop: '8px', display: 'block' }}>
              Try a different search term or adjust your filters.
            </span>
          </div>
        )}

        {!loading && results && (
          <>
            {showPosts && (
              <div className="search-page__section">
                <div className="search-page__section-title">
                  Posts ({results.results.posts.length}{results.counts.posts > results.results.posts.length ? '+' : ''})
                </div>
                {results.results.posts.map((p) => (
                  <PostCard key={p.id} p={p} query={query} />
                ))}
              </div>
            )}

            {showEntities && (
              <div className="search-page__section">
                <div className="search-page__section-title">
                  Entities ({results.results.entities.length})
                </div>
                {results.results.entities.map((e) => (
                  <EntityCard key={e.id} e={e} query={query} />
                ))}
              </div>
            )}

            {showEvents && (
              <div className="search-page__section">
                <div className="search-page__section-title">
                  Events ({results.results.events.length})
                </div>
                {results.results.events.map((ev) => (
                  <EventCard key={ev.id} ev={ev} query={query} />
                ))}
              </div>
            )}

            {showBriefs && (
              <div className="search-page__section">
                <div className="search-page__section-title">
                  Briefs ({results.results.briefs.length})
                </div>
                {results.results.briefs.map((b) => (
                  <BriefCard key={b.id} b={b} query={query} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

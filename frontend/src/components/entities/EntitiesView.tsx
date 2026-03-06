import { useEffect, useState, useMemo } from 'react';
import { useSearchParams, useParams } from 'react-router-dom';
import api from '../../services/api';
import { EntityDetail } from './EntityDetail';
import { EntityGraph } from './EntityGraph';
import '../../styles/entities.css';

// ── Types ──────────────────────────────────────────────────
interface Entity {
  id: number;
  name: string;
  type: string;
  canonical_name?: string;
  mention_count: number;
  first_seen: string;
  last_seen: string;
}

type SortKey = 'mention_count' | 'last_seen' | 'name';
type SortDir = 'asc' | 'desc';

const PAGE_SIZE = 50;

const ENTITY_TYPES = ['All', 'PERSON', 'ORG', 'GPE', 'EVENT', 'NORP'];

// ── Helpers ────────────────────────────────────────────────
function entityTypeClass(type: string): string {
  const map: Record<string, string> = {
    PERSON: 'person',
    ORG: 'org',
    GPE: 'gpe',
    EVENT: 'event',
    NORP: 'norp',
  };
  return map[type?.toUpperCase()] ?? 'norp';
}

function formatDate(ts: string | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: '2-digit',
  });
}

type ViewTab = 'table' | 'graph';

// ── Component ──────────────────────────────────────────────
export function EntitiesView() {
  const [searchParams] = useSearchParams();
  const { id: routeId } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<ViewTab>('table');
  const [entities, setEntities] = useState<Entity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters — initialise from URL params
  const [search, setSearch] = useState(() => searchParams.get('search') || '');
  const [typeFilter, setTypeFilter] = useState('All');
  const [sortKey, setSortKey] = useState<SortKey>('mention_count');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  // Pagination
  const [page, setPage] = useState(0);

  // Selection — initialise from URL params or route id
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    if (routeId) return parseInt(routeId, 10);
    const sel = searchParams.get('selected');
    return sel ? parseInt(sel, 10) : null;
  });

  useEffect(() => {
    let cancelled = false;

    async function fetch() {
      setLoading(true);
      setError(null);
      try {
        const res = await api.get('/entities/', {
          params: { sort_by: 'mention_count', limit: 500 },
        });
        if (!cancelled) {
          setEntities(res.data);
          // If ?selected= param or route :id is set, find and select the entity
          const selParam = routeId || searchParams.get('selected');
          const searchParam = searchParams.get('search');
          if (selParam && !selectedId) {
            const selId = parseInt(selParam, 10);
            if (!isNaN(selId)) setSelectedId(selId);
          }
          // If ?search= param and the entity matches, auto-select first result
          if (searchParam && !selParam) {
            const match = (res.data as Entity[]).find(
              (e) => e.name.toLowerCase() === searchParam.toLowerCase()
            );
            if (match) setSelectedId(match.id);
          }
        }
      } catch (err: unknown) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : 'Failed to load entities';
          setError(msg);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetch();
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Filter + sort
  const filtered = useMemo(() => {
    let list = entities;

    if (typeFilter !== 'All') {
      list = list.filter((e) => e.type === typeFilter);
    }

    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (e) =>
          e.name.toLowerCase().includes(q) ||
          (e.canonical_name?.toLowerCase().includes(q) ?? false)
      );
    }

    list = [...list].sort((a, b) => {
      let cmp = 0;
      if (sortKey === 'mention_count') {
        cmp = a.mention_count - b.mention_count;
      } else if (sortKey === 'last_seen') {
        cmp = new Date(a.last_seen).getTime() - new Date(b.last_seen).getTime();
      } else if (sortKey === 'name') {
        cmp = a.name.localeCompare(b.name);
      }
      return sortDir === 'desc' ? -cmp : cmp;
    });

    return list;
  }, [entities, typeFilter, search, sortKey, sortDir]);

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
    setPage(0);
  }

  function handleSearchChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSearch(e.target.value);
    setPage(0);
  }

  function handleTypeChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setTypeFilter(e.target.value);
    setPage(0);
  }

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return <span className="entities-table__sort-icon">↕</span>;
    return (
      <span className="entities-table__sort-icon">
        {sortDir === 'desc' ? '↓' : '↑'}
      </span>
    );
  }

  return (
    <div className="entities-outer">
      {/* Tab bar */}
      <div className="entities-tab-bar">
        <button
          className={`entities-tab${activeTab === 'table' ? ' entities-tab--active' : ''}`}
          onClick={() => setActiveTab('table')}
        >
          ☰ Table
        </button>
        <button
          className={`entities-tab${activeTab === 'graph' ? ' entities-tab--active' : ''}`}
          onClick={() => setActiveTab('graph')}
        >
          ⬡ Network
        </button>
      </div>

      {/* Graph view */}
      {activeTab === 'graph' && <EntityGraph />}

      {/* Table view */}
      {activeTab === 'table' && <div className="entities-view">
      {/* Left panel */}
      <div className="entities-panel">
        {/* Header */}
        <div className="entities-panel__header">
          <span className="entities-panel__title">Entities</span>
          <span className="entities-panel__count">
            {filtered.length} of {entities.length}
          </span>
        </div>

        {/* Filter bar */}
        <div className="entities-filters">
          <div className="entities-filters__search">
            <input
              className="input"
              type="text"
              placeholder="Search entities…"
              value={search}
              onChange={handleSearchChange}
            />
          </div>
          <div className="entities-filters__select">
            <select
              className="select"
              value={typeFilter}
              onChange={handleTypeChange}
            >
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t === 'All' ? 'All Types' : t}
                </option>
              ))}
            </select>
          </div>
          <div style={{ width: 130, flexShrink: 0 }}>
            <select
              className="select"
              value={sortKey}
              onChange={(e) => {
                setSortKey(e.target.value as SortKey);
                setPage(0);
              }}
            >
              <option value="mention_count">Sort: Mentions</option>
              <option value="last_seen">Sort: Recent</option>
              <option value="name">Sort: Name</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="entities-table-wrap">
          {loading ? (
            <div className="entities-loading">
              <span className="spinner" />
              Loading entities…
            </div>
          ) : error ? (
            <div className="entities-error">⚠ {error}</div>
          ) : (
            <table className="entities-table">
              <thead>
                <tr>
                  <th
                    className={sortKey === 'name' ? 'sorted' : ''}
                    onClick={() => handleSort('name')}
                  >
                    Name {sortIcon('name')}
                  </th>
                  <th>Type</th>
                  <th
                    className={sortKey === 'mention_count' ? 'sorted' : ''}
                    onClick={() => handleSort('mention_count')}
                    style={{ textAlign: 'right' }}
                  >
                    Mentions {sortIcon('mention_count')}
                  </th>
                  <th
                    className={sortKey === 'last_seen' ? 'sorted' : ''}
                    onClick={() => handleSort('last_seen')}
                  >
                    First Seen {sortIcon('last_seen')}
                  </th>
                  <th>Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {paginated.length === 0 ? (
                  <tr>
                    <td
                      colSpan={5}
                      style={{
                        textAlign: 'center',
                        color: 'var(--text-muted)',
                        padding: '32px',
                      }}
                    >
                      No entities match filters
                    </td>
                  </tr>
                ) : (
                  paginated.map((entity) => (
                    <tr
                      key={entity.id}
                      className={`entities-table__row${selectedId === entity.id ? ' entities-table__row--selected' : ''}`}
                      onClick={() =>
                        setSelectedId((prev) =>
                          prev === entity.id ? null : entity.id
                        )
                      }
                    >
                      <td className="entities-table__name">{entity.name}</td>
                      <td>
                        <span
                          className={`badge badge--${entityTypeClass(entity.type)}`}
                        >
                          {entity.type}
                        </span>
                      </td>
                      <td
                        className="entities-table__mono"
                        style={{ textAlign: 'right' }}
                      >
                        {entity.mention_count}
                      </td>
                      <td className="entities-table__mono">
                        {formatDate(entity.first_seen)}
                      </td>
                      <td className="entities-table__mono">
                        {formatDate(entity.last_seen)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {!loading && !error && totalPages > 1 && (
          <div className="entities-pagination">
            <span>
              Page {page + 1} of {totalPages} ·{' '}
              {page * PAGE_SIZE + 1}–
              {Math.min((page + 1) * PAGE_SIZE, filtered.length)} of{' '}
              {filtered.length}
            </span>
            <div className="entities-pagination__controls">
              <button
                className="btn btn-secondary btn-sm"
                disabled={page === 0}
                onClick={() => setPage((p) => p - 1)}
              >
                ← Prev
              </button>
              <button
                className="btn btn-secondary btn-sm"
                disabled={page >= totalPages - 1}
                onClick={() => setPage((p) => p + 1)}
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Right detail panel */}
      <div className="entities-detail">
        {selectedId === null ? (
          <div className="entities-detail__empty">
            <span className="entities-detail__empty-icon">🔗</span>
            <span className="entities-detail__empty-title">Select an entity to view details</span>
            <span className="entities-detail__empty-sub">
              Select an entity from the table to view mentions, connections, and timeline
            </span>
            {entities.length > 0 && (
              <div className="entities-detail__stats">
                {(['PERSON', 'ORG', 'GPE', 'EVENT', 'NORP'] as const).map((t) => {
                  const count = entities.filter((e) => e.type === t).length;
                  if (count === 0) return null;
                  return (
                    <div key={t} className="entities-detail__stat-item">
                      <span className={`badge badge--${entityTypeClass(t)}`}>{t}</span>
                      <span className="entities-detail__stat-count">{count}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <EntityDetail entityId={selectedId} />
        )}
      </div>
      </div>}
    </div>
  );
}

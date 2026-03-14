import { useEffect, useRef, useState } from 'react';
import { useSearchParams, useParams } from 'react-router-dom';
import api from '../../services/api';
import { EntityDetail } from './EntityDetail';
import { EntityGraph } from './EntityGraph';
import { MergeCandidatesView } from './MergeCandidatesView';
import '../../styles/entities.css';

// ── Types ──────────────────────────────────────────────────
interface Entity {
  id: string;
  name: string;
  type: string;
  canonical_name?: string;
  mention_count: number;
  first_seen: string;
  last_seen: string;
}

interface PagedResponse {
  items: Entity[];
  total: number;
  limit: number;
  offset: number;
}

type SortKey = 'mention_count' | 'last_seen' | 'name';

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

type ViewTab = 'table' | 'graph' | 'merge';

// ── Component ──────────────────────────────────────────────
export function EntitiesView() {
  const [searchParams] = useSearchParams();
  const { id: routeId } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<ViewTab>('table');
  const [entities, setEntities] = useState<Entity[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters — initialise from URL params
  const [search, setSearch] = useState(() => searchParams.get('search') || '');
  const [typeFilter, setTypeFilter] = useState('All');
  const [sortKey, setSortKey] = useState<SortKey>('mention_count');

  // Debounced search to avoid firing on every keystroke
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Pagination
  const [page, setPage] = useState(0);

  // Selection — initialise from URL params or route id
  const [selectedId, setSelectedId] = useState<string | null>(() => {
    if (routeId) return routeId;
    const sel = searchParams.get('selected');
    return sel || null;
  });

  // Initial URL-param auto-selection — only fire once after first load
  const initialSelectionDone = useRef(false);

  // Debounce search input — 300 ms
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedSearch(search), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [search]);

  // Reset to page 0 whenever filter/sort changes
  useEffect(() => {
    setPage(0);
  }, [debouncedSearch, typeFilter, sortKey]);

  // ── Backend-driven fetch ─────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const params: Record<string, unknown> = {
      sort_by: sortKey,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    };
    if (debouncedSearch.trim()) params.q = debouncedSearch.trim();
    if (typeFilter !== 'All') params.type = typeFilter;

    api
      .get('/entities/search', { params })
      .then((res) => {
        if (cancelled) return;
        const data = res.data as PagedResponse;
        setEntities(data.items);
        setTotal(data.total);

        // Handle initial auto-selection from URL params (only first time)
        if (!initialSelectionDone.current) {
          initialSelectionDone.current = true;
          const selParam = routeId || searchParams.get('selected');
          const searchParam = searchParams.get('search');

          if (selParam && !selectedId) {
            setSelectedId(selParam);
          } else if (searchParam && !selParam && data.items.length > 0) {
            const match = data.items.find(
              (e) => e.name.toLowerCase() === searchParam.toLowerCase()
            );
            if (match) setSelectedId(match.id);
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg =
            err instanceof Error ? err.message : 'Failed to load entities';
          setError(msg);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [debouncedSearch, typeFilter, sortKey, page]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalPages = Math.ceil(total / PAGE_SIZE);

  // ── Sort handler ─────────────────────────────────────────
  function handleSort(key: SortKey) {
    if (sortKey !== key) {
      setSortKey(key);
      setPage(0);
    }
  }

  function handleSearchChange(e: React.ChangeEvent<HTMLInputElement>) {
    setSearch(e.target.value);
  }

  function handleTypeChange(e: React.ChangeEvent<HTMLSelectElement>) {
    setTypeFilter(e.target.value);
    setPage(0);
  }

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return <span className="entities-table__sort-icon">↕</span>;
    // Backend sort: name → asc, mention_count/last_seen → desc
    const dir = key === 'name' ? '↑' : '↓';
    return <span className="entities-table__sort-icon">{dir}</span>;
  }

  // ── Display range string ─────────────────────────────────
  const rangeStart = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const rangeEnd = Math.min((page + 1) * PAGE_SIZE, total);

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
        <button
          className={`entities-tab${activeTab === 'merge' ? ' entities-tab--active' : ''}`}
          onClick={() => setActiveTab('merge')}
        >
          🔀 Merge Review
        </button>
      </div>

      {/* Graph view */}
      {activeTab === 'graph' && <EntityGraph />}

      {/* Merge review view */}
      {activeTab === 'merge' && (
        <MergeCandidatesView
          onMergeComplete={() => {
            // Trigger a reload of the entity table if the user switches back
            setPage(0);
            // Clear selection — merged entity may have been deleted
            setSelectedId(null);
          }}
        />
      )}

      {/* Table view */}
      {activeTab === 'table' && (
        <div className="entities-view">
          {/* Left panel */}
          <div className="entities-panel">
            {/* Header */}
            <div className="entities-panel__header">
              <span className="entities-panel__title">Entities</span>
              <span className="entities-panel__count">
                {loading
                  ? '…'
                  : total === 0
                  ? '0'
                  : `${rangeStart}–${rangeEnd} of ${total.toLocaleString()}`}
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
                      <th>First Seen</th>
                      <th
                        className={sortKey === 'last_seen' ? 'sorted' : ''}
                        onClick={() => handleSort('last_seen')}
                      >
                        Last Seen {sortIcon('last_seen')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {entities.length === 0 ? (
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
                      entities.map((entity) => (
                        <tr
                          key={entity.id}
                          className={`entities-table__row${
                            selectedId === entity.id
                              ? ' entities-table__row--selected'
                              : ''
                          }`}
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
                  Displaying {rangeStart}–{rangeEnd} of {total.toLocaleString()}
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
                <span className="entities-detail__empty-title">
                  Select an entity to view details
                </span>
                <span className="entities-detail__empty-sub">
                  Select an entity from the table to view mentions, connections,
                  and timeline
                </span>
                {total > 0 && (
                  <div className="entities-detail__stats">
                    <div className="entities-detail__stat-item">
                      <span
                        style={{ fontSize: 12, color: 'var(--text-muted)' }}
                      >
                        {total.toLocaleString()} entities in database
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <EntityDetail entityId={selectedId} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

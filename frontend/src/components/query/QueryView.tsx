/**
 * QueryView — OQL + Natural Language query interface.
 *
 * Supports two modes:
 *   OQL  — structured Orthanc Query Language with table/JSON views
 *   NL   — existing natural language AI query (delegated to /query endpoint)
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import api from '../../services/api';
import { VizBuilder } from './VizBuilder';
import '../../styles/oql.css';
import '../../styles/nlquery.css';
import '../../styles/charts.css';

// ── Types ────────────────────────────────────────────────────────────────────

type QueryMode = 'oql' | 'nl';

interface OQLColumn {
  name: string;
  type: string;
}

interface OQLResponse {
  columns: OQLColumn[];
  rows: Record<string, unknown>[];
  total: number;
  query_time_ms: number;
  visualization_hint: string;
}

interface HistoryEntry {
  id: string;
  query_text: string;
  executed_at: string | null;
  row_count: number | null;
  duration_ms: number | null;
}

interface SavedEntry {
  id: string;
  name: string;
  query_text: string;
  description: string | null;
  is_pinned: boolean;
}

type SortDir = 'asc' | 'desc' | null;

// ── Helpers ──────────────────────────────────────────────────────────────────

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function downloadBlob(content: string, filename: string, mime: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = filename;
  a.click();
}

function exportCSV(columns: OQLColumn[], rows: Record<string, unknown>[]) {
  const header = columns.map((c) => c.name).join(',');
  const body = rows.map((r) =>
    columns.map((c) => {
      const v = r[c.name];
      if (v === null || v === undefined) return '';
      const s = String(v);
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? `"${s.replace(/"/g, '""')}"`
        : s;
    }).join(',')
  );
  downloadBlob([header, ...body].join('\n'), 'oql-results.csv', 'text/csv');
}

function exportJSON(rows: Record<string, unknown>[]) {
  downloadBlob(JSON.stringify(rows, null, 2), 'oql-results.json', 'application/json');
}

function vizLabel(hint: string): string {
  switch (hint) {
    case 'timeseries': return 'time series chart';
    case 'bar': return 'bar chart';
    case 'pie': return 'pie chart';
    case 'map': return 'map';
    default: return 'table';
  }
}

// Number types for monospace rendering
const NUM_TYPES = new Set(['integer', 'float', 'mixed']);
const UUID_TYPES = new Set(['uuid']);

// ── Results Table ─────────────────────────────────────────────────────────────

function ResultsTable({
  columns,
  rows,
  onRowClick,
}: {
  columns: OQLColumn[];
  rows: Record<string, unknown>[];
  onRowClick: (row: Record<string, unknown>) => void;
}) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);

  const handleSort = (colName: string) => {
    if (sortCol === colName) {
      setSortDir((d) => (d === 'asc' ? 'desc' : d === 'desc' ? null : 'asc'));
      if (sortDir === 'desc') setSortCol(null);
    } else {
      setSortCol(colName);
      setSortDir('asc');
    }
  };

  const sorted = [...rows].sort((a, b) => {
    if (!sortCol || !sortDir) return 0;
    const av = a[sortCol];
    const bv = b[sortCol];
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    const cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
    return sortDir === 'asc' ? cmp : -cmp;
  });

  if (rows.length === 0) {
    return <div className="oql-empty">No results</div>;
  }

  return (
    <div className="oql-table-wrap">
      <table className="oql-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.name}
                className={sortCol === col.name ? 'sort-active' : ''}
                onClick={() => handleSort(col.name)}
              >
                {col.name}
                <span className="oql-sort-icon">
                  {sortCol === col.name ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={i} onClick={() => onRowClick(row)}>
              {columns.map((col) => {
                const val = row[col.name];
                const display = val === null || val === undefined ? '—' : String(val);
                let cls = '';
                if (NUM_TYPES.has(col.type)) cls = 'num';
                else if (UUID_TYPES.has(col.type)) cls = 'uuid';
                else if (col.name === 'content') cls = 'content-cell';
                return (
                  <td key={col.name} className={cls} title={display}>
                    {display}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Save Dialog ───────────────────────────────────────────────────────────────

function SaveDialog({
  queryText,
  onClose,
  onSaved,
}: {
  queryText: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSave = async () => {
    if (!name.trim()) { setError('Name is required'); return; }
    setSaving(true);
    try {
      await api.post('/oql/save', { name: name.trim(), query_text: queryText, description: desc || null });
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e?.response?.data?.detail?.error ?? e?.message ?? 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="oql-save-dialog" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="oql-save-dialog-box">
        <div className="oql-save-dialog-title">Save Query</div>
        <input
          className="oql-dialog-input"
          placeholder="Query name…"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <input
          className="oql-dialog-input"
          placeholder="Description (optional)"
          value={desc}
          onChange={(e) => setDesc(e.target.value)}
        />
        {error && <div style={{ color: 'var(--danger)', fontSize: 12 }}>{error}</div>}
        <div className="oql-dialog-actions">
          <button className="oql-btn-secondary" onClick={onClose}>Cancel</button>
          <button className="oql-btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Example Queries ────────────────────────────────────────────────────────────

const EXAMPLE_QUERIES = [
  { label: 'Posts by source',   query: '| stats count by source_type | sort -count' },
  { label: 'Telegram authors',  query: 'source_type=telegram | stats count by author | sort -count' },
  { label: 'Post volume (24h)', query: '| timechart span=1h count' },
  { label: 'Top entities',      query: 'entities: | top 10 name' },
  { label: 'Recent media',      query: 'has_media=true | head 20 | table author, timestamp, media_type' },
  { label: 'Top locations',     query: 'events: | top 15 place_name' },
  { label: 'Iran mentions',     query: 'content="*Iran*" | stats count by source_type' },
  { label: 'Org entities',      query: 'entities: type=ORG | sort -mention_count | head 20 | table name, mention_count' },
];

// ── OQL Mode ─────────────────────────────────────────────────────────────────

function OQLMode({ initialQuery }: { initialQuery?: string }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState(initialQuery ?? '');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OQLResponse | null>(null);
  const [error, setError] = useState<{ error: string; position: number } | null>(null);
  const [viewMode, setViewMode] = useState<'table' | 'json'>('table');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [saved, setSaved] = useState<SavedEntry[]>([]);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const loadHistory = useCallback(async () => {
    try {
      const res = await api.get('/oql/history?limit=20');
      setHistory(res.data.history ?? []);
    } catch { /* ignore */ }
  }, []);

  const loadSaved = useCallback(async () => {
    try {
      const res = await api.get('/oql/saved');
      setSaved(res.data.saved ?? []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadHistory();
    loadSaved();
  }, [loadHistory, loadSaved]);

  // Auto-execute if launched with an initial query (e.g. from Feed "Open as Query")
  useEffect(() => {
    if (initialQuery) {
      setTimeout(() => execute(initialQuery), 300);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [query]);

  const execute = async (q?: string) => {
    const qstr = (q ?? query).trim();
    if (!qstr || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setHistoryIdx(-1);

    try {
      const res = await api.post('/oql/execute', { query: qstr, limit: 1000 });
      setResult(res.data as OQLResponse);
      setViewMode('table');
      // Reload history
      await loadHistory();
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (detail && typeof detail === 'object' && 'error' in detail) {
        setError(detail as { error: string; position: number });
      } else {
        setError({ error: detail ?? e?.message ?? 'Request failed', position: -1 });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      execute();
      return;
    }
    // Arrow up/down navigate history when query is empty
    if (e.key === 'ArrowUp' && !query.trim()) {
      e.preventDefault();
      const nextIdx = Math.min(historyIdx + 1, history.length - 1);
      setHistoryIdx(nextIdx);
      if (history[nextIdx]) setQuery(history[nextIdx].query_text);
    }
    if (e.key === 'ArrowDown' && historyIdx >= 0) {
      e.preventDefault();
      const nextIdx = historyIdx - 1;
      setHistoryIdx(nextIdx);
      setQuery(nextIdx >= 0 ? history[nextIdx].query_text : '');
    }
  };

  const handleRowClick = (row: Record<string, unknown>) => {
    if (row.id && row.source_type !== undefined) {
      navigate(`/feed?post=${row.id}`);
    } else if (row.id && row.mention_count !== undefined) {
      navigate(`/entities/${row.id}`);
    } else if (row.lat !== undefined && row.lng !== undefined) {
      navigate(`/map?lat=${row.lat}&lng=${row.lng}`);
    }
  };

  const handleDeleteSaved = async (id: string) => {
    try {
      await api.delete(`/oql/saved/${id}`);
      setSaved((prev) => prev.filter((s) => s.id !== id));
    } catch { /* ignore */ }
  };

  return (
    <div className="oql-layout">
      <div className="oql-main">
        {/* Query bar */}
        <div className="oql-bar">
          <div className="oql-input-row">
            <textarea
              ref={textareaRef}
              className="oql-input"
              placeholder="source_type=telegram | stats count by author | sort -count"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              spellCheck={false}
            />
            <button
              className="oql-execute-btn"
              onClick={() => execute()}
              disabled={loading || !query.trim()}
            >
              {loading ? <span className="oql-spinner" /> : '▶'}
              {loading ? 'Running…' : 'Execute'}
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="oql-error">
              <span className="oql-error-icon">⚠</span>
              <span>{error.error}{error.position >= 0 ? ` (pos ${error.position})` : ''}</span>
            </div>
          )}

          <div className="oql-bar-footer">
            <span className="oql-bar-hint">Ctrl+Enter to execute · ↑↓ navigate history</span>
          </div>
        </div>

        {/* Example queries — shown when query is empty and no results yet */}
        {!query.trim() && !result && !loading && (
          <div className="oql-examples">
            <div className="oql-examples__title">Example Queries</div>
            <div className="oql-examples__grid">
              {EXAMPLE_QUERIES.map((ex) => (
                <button
                  key={ex.label}
                  className="oql-example-card"
                  onClick={() => setQuery(ex.query)}
                >
                  <span className="oql-example-card__label">{ex.label}</span>
                  <code className="oql-example-card__query">{ex.query}</code>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Results */}
        {loading && (
          <div className="oql-loading">
            <span className="oql-spinner" />
            Executing query…
          </div>
        )}

        {result && !loading && (
          <div className="oql-results">
            {/* Stats bar */}
            <div className="oql-stats-bar">
              <span className="oql-stats-text">
                {result.total.toLocaleString()} result{result.total !== 1 ? 's' : ''} in{' '}
                {result.query_time_ms.toFixed(1)}ms
                {result.rows.length < result.total
                  ? ` (showing ${result.rows.length.toLocaleString()})`
                  : ''}
              </span>

              {/* vizLabel kept for future use */}

              <div className="oql-stats-actions">
                <div className="oql-view-toggle">
                  <button
                    className={`oql-view-btn ${viewMode === 'table' ? 'active' : ''}`}
                    onClick={() => setViewMode('table')}
                  >
                    Table
                  </button>
                  <button
                    className={`oql-view-btn ${viewMode === 'json' ? 'active' : ''}`}
                    onClick={() => setViewMode('json')}
                  >
                    JSON
                  </button>
                </div>
                <button className="oql-action-btn" onClick={() => exportCSV(result.columns, result.rows)}>
                  ⬇ CSV
                </button>
                <button className="oql-action-btn" onClick={() => exportJSON(result.rows)}>
                  ⬇ JSON
                </button>
                <button className="oql-action-btn" onClick={() => setShowSaveDialog(true)}>
                  💾 Save
                </button>
              </div>
            </div>

            {viewMode === 'table' ? (
              <ResultsTable
                columns={result.columns}
                rows={result.rows}
                onRowClick={handleRowClick}
              />
            ) : (
              <div className="oql-json-view">
                <pre>{JSON.stringify({ columns: result.columns, rows: result.rows }, null, 2)}</pre>
              </div>
            )}

            {/* Visualization Builder */}
            {result.rows.length > 0 && (
              <VizBuilder
                columns={result.columns}
                rows={result.rows}
                visualizationHint={result.visualization_hint}
                queryText={query}
              />
            )}
          </div>
        )}
      </div>

      {/* Sidebar */}
      <aside className="oql-sidebar">
        <div className="oql-sidebar-header">
          <span>Query History</span>
        </div>

        <div className="oql-sidebar-section">
          {history.length === 0 ? (
            <div className="oql-sidebar-empty">No queries yet</div>
          ) : (
            history.map((h) => (
              <button
                key={h.id}
                className="oql-history-item"
                onClick={() => { setQuery(h.query_text); textareaRef.current?.focus(); }}
              >
                <div className="oql-history-query">{h.query_text}</div>
                <div className="oql-history-meta">
                  <span>{relativeTime(h.executed_at)}</span>
                  {h.row_count !== null && <span>· {h.row_count.toLocaleString()} rows</span>}
                  {h.duration_ms !== null && <span>· {h.duration_ms.toFixed(0)}ms</span>}
                </div>
              </button>
            ))
          )}

          {/* Saved queries */}
          <div className="oql-sidebar-section-title">
            <span>Saved Queries</span>
          </div>

          {saved.length === 0 ? (
            <div className="oql-sidebar-empty">No saved queries</div>
          ) : (
            saved.map((s) => (
              <div key={s.id} className="oql-saved-item">
                <button
                  className="oql-saved-load"
                  onClick={() => { setQuery(s.query_text); textareaRef.current?.focus(); }}
                >
                  <div className="oql-saved-name">{s.name}</div>
                  <div className="oql-saved-query-preview">{s.query_text}</div>
                </button>
                <button
                  className="oql-saved-delete"
                  onClick={() => handleDeleteSaved(s.id)}
                  title="Delete saved query"
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      {/* Save dialog */}
      {showSaveDialog && (
        <SaveDialog
          queryText={query}
          onClose={() => setShowSaveDialog(false)}
          onSaved={loadSaved}
        />
      )}
    </div>
  );
}

// ── NL Mode (thin wrapper around existing component) ──────────────────────────

function NLMode() {
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [question]);

  const submit = async () => {
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setAnswer(null);
    setErrorMsg(null);
    try {
      const res = await api.post('/query', { question: q });
      setAnswer(res.data.answer ?? JSON.stringify(res.data));
    } catch (e: any) {
      setErrorMsg(e?.response?.data?.detail ?? e?.message ?? 'Request failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="nlquery-layout" style={{ flex: 1 }}>
      <main className="nlquery-main">
        <div className="nlquery-input-card">
          <div className="nlquery-input-header">
            <span className="nlquery-brain">🧠</span>
            <h1 className="nlquery-title">Ask AI</h1>
            <span className="nlquery-subtitle">Query your intelligence data in plain English</span>
          </div>
          <textarea
            ref={textareaRef}
            className="nlquery-input"
            placeholder="Ask anything about your intelligence data…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); submit(); }
            }}
            rows={3}
          />
          <div className="nlquery-input-footer">
            <span className="nlquery-hint">Ctrl+Enter to submit</span>
            <button
              className="nlquery-submit-btn"
              onClick={submit}
              disabled={loading || !question.trim()}
            >
              {loading ? <><span className="nlquery-spinner" /> Analyzing…</> : <><span>🔍</span> Ask AI</>}
            </button>
          </div>
        </div>

        {loading && (
          <div className="nlquery-loading">
            <div className="nlquery-loading-dots"><span /><span /><span /></div>
            <div className="nlquery-loading-text">Analyzing your question…</div>
          </div>
        )}

        {errorMsg && (
          <div className="nlquery-error">
            <span className="nlquery-error-icon">⚠️</span>
            <div><strong>Error:</strong> {errorMsg}</div>
          </div>
        )}

        {answer && !loading && (
          <div className="nlquery-answer">
            <div className="nlquery-answer-header">
              <span className="nlquery-answer-icon">💡</span>
              <span className="nlquery-answer-label">AI Analysis</span>
            </div>
            <div className="nlquery-answer-text">{answer}</div>
          </div>
        )}
      </main>
    </div>
  );
}

// ── Root Component ────────────────────────────────────────────────────────────

export function QueryView() {
  const [searchParams] = useSearchParams();
  const [mode, setMode] = useState<QueryMode>('oql');
  const initialOQL = searchParams.get('oql') ?? undefined;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Mode toggle bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 20px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-surface)',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Query</span>
        <div className="oql-mode-toggle">
          <button
            className={`oql-mode-btn ${mode === 'oql' ? 'active' : ''}`}
            onClick={() => setMode('oql')}
          >
            OQL
          </button>
          <button
            className={`oql-mode-btn ${mode === 'nl' ? 'active' : ''}`}
            onClick={() => setMode('nl')}
          >
            Natural Language
          </button>
        </div>
        {mode === 'oql' && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 8 }}>
            Orthanc Query Language — structured, powerful, instant
          </span>
        )}
      </div>

      {/* Mode content */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {mode === 'oql' ? <OQLMode initialQuery={initialOQL} /> : <NLMode />}
      </div>
    </div>
  );
}

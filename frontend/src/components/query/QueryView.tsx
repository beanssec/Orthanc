import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '../../services/api';
import '../../styles/nlquery.css';

// ── Types ────────────────────────────────────────────────────────────────────

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
  mention_count?: number;
  recent_mentions?: number;
  last_seen?: string;
}

interface EventResult {
  id: string;
  place_name: string;
  lat: number | null;
  lng: number | null;
  post_id: string;
  timestamp?: string;
  snippet?: string;
  source_type?: string;
  distance_km?: number;
}

interface SignalResult {
  id: string;
  signal_type: string;
  severity?: string;
  title: string;
  summary: string;
  affected_tickers?: string;
  generated_at?: string;
}

interface QueryResponse {
  question: string;
  plan: string;
  answer: string;
  data: {
    posts: PostResult[];
    entities: EntityResult[];
    events: EventResult[];
    signals: SignalResult[];
  };
  metadata: {
    model_used: string;
    queries_executed: number;
    total_results: number;
  };
  error?: string;
}

interface HistoryEntry {
  id: string;
  question: string;
  answer: string;
  timestamp: number;
  total_results: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function relativeTime(isoStr: string | null | undefined): string {
  if (!isoStr) return '';
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const EXAMPLE_QUERIES = [
  'What entities are most mentioned in the last 24 hours?',
  'Summarize what\'s happening globally today',
  'Any activity near the Strait of Hormuz?',
  'Which tickers are affected by recent events?',
  'Show me the latest geopolitical events',
  'What organizations are generating the most OSINT signals?',
];

function HISTORY_KEY() { return 'orthanc_nlquery_history'; }

function loadHistory(): HistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY());
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveHistory(entries: HistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY(), JSON.stringify(entries.slice(0, 10)));
  } catch {
    /* ignore quota errors */
  }
}

// ── Collapsible section ──────────────────────────────────────────────────────

function DataSection({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  if (count === 0) return null;
  return (
    <div className="nlquery-data-section">
      <button className="nlquery-section-toggle" onClick={() => setOpen((o) => !o)}>
        <span>{title}</span>
        <span className="nlquery-section-count">{count}</span>
        <span className="nlquery-section-chevron">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="nlquery-section-body">{children}</div>}
    </div>
  );
}

// ── Main view ────────────────────────────────────────────────────────────────

export function QueryView() {
  const [searchParams] = useSearchParams();
  const [question, setQuestion] = useState(searchParams.get('q') ?? '');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>(loadHistory);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const submittedRef = useRef(false);

  // Auto-submit if ?q= param is set
  useEffect(() => {
    const q = searchParams.get('q');
    if (q && !submittedRef.current) {
      submittedRef.current = true;
      submit(q);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [question]);

  const submit = async (q?: string) => {
    const query = (q ?? question).trim();
    if (!query || loading) return;

    setLoading(true);
    setResult(null);

    try {
      const res = await api.post('/query', { question: query });
      const data = res.data as QueryResponse;
      setResult(data);

      if (!data.error) {
        const entry: HistoryEntry = {
          id: Date.now().toString(),
          question: query,
          answer: data.answer?.substring(0, 120) ?? '',
          timestamp: Date.now(),
          total_results: data.metadata?.total_results ?? 0,
        };
        const updated = [entry, ...history.filter((h) => h.question !== query)];
        setHistory(updated);
        saveHistory(updated);
      }
    } catch (err: any) {
      setResult({
        question: query,
        plan: '',
        answer: '',
        data: { posts: [], entities: [], events: [], signals: [] },
        metadata: { model_used: '', queries_executed: 0, total_results: 0 },
        error: err?.response?.data?.detail ?? err?.message ?? 'Request failed',
      });
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      submit();
    }
  };

  const clearHistory = () => {
    setHistory([]);
    localStorage.removeItem(HISTORY_KEY());
  };

  return (
    <div className="nlquery-layout">
      {/* Sidebar: history */}
      <aside className="nlquery-sidebar">
        <div className="nlquery-sidebar-header">
          <span>Query History</span>
          {history.length > 0 && (
            <button className="nlquery-clear-btn" onClick={clearHistory} title="Clear history">
              ✕
            </button>
          )}
        </div>

        {history.length === 0 ? (
          <div className="nlquery-sidebar-empty">No queries yet</div>
        ) : (
          <div className="nlquery-history-list">
            {history.map((h) => (
              <button
                key={h.id}
                className="nlquery-history-item"
                onClick={() => {
                  setQuestion(h.question);
                  submit(h.question);
                }}
              >
                <div className="nlquery-history-question">{h.question}</div>
                {h.answer && (
                  <div className="nlquery-history-preview">{h.answer}…</div>
                )}
                <div className="nlquery-history-meta">
                  {relativeTime(new Date(h.timestamp).toISOString())}
                  {h.total_results > 0 && ` · ${h.total_results} results`}
                </div>
              </button>
            ))}
          </div>
        )}
      </aside>

      {/* Main area */}
      <main className="nlquery-main">
        {/* Input */}
        <div className="nlquery-input-card">
          <div className="nlquery-input-header">
            <span className="nlquery-brain">🧠</span>
            <h1 className="nlquery-title">Ask AI</h1>
            <span className="nlquery-subtitle">Query your intelligence data in plain English</span>
          </div>

          <textarea
            ref={textareaRef}
            className="nlquery-input"
            placeholder="Ask anything about your intelligence data…&#10;e.g. 'What entities are most mentioned with Russia this week?'"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={3}
          />

          <div className="nlquery-input-footer">
            <span className="nlquery-hint">Ctrl+Enter to submit</span>
            <button
              className="nlquery-submit-btn"
              onClick={() => submit()}
              disabled={loading || !question.trim()}
            >
              {loading ? (
                <>
                  <span className="nlquery-spinner" />
                  Analyzing…
                </>
              ) : (
                <>
                  <span>🔍</span>
                  Ask AI
                </>
              )}
            </button>
          </div>

          {/* Example queries */}
          {!result && !loading && (
            <div className="nlquery-examples">
              <div className="nlquery-examples-label">Try asking:</div>
              <div className="nlquery-examples-grid">
                {EXAMPLE_QUERIES.map((eq) => (
                  <button
                    key={eq}
                    className="nlquery-example-chip"
                    onClick={() => {
                      setQuestion(eq);
                      submit(eq);
                    }}
                  >
                    {eq}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Loading state */}
        {loading && (
          <div className="nlquery-loading">
            <div className="nlquery-loading-dots">
              <span /><span /><span />
            </div>
            <div className="nlquery-loading-text">Analyzing your question…</div>
            <div className="nlquery-loading-sub">Querying database and generating insights</div>
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <div className="nlquery-results">
            {/* Error */}
            {result.error && (
              <div className="nlquery-error">
                <span className="nlquery-error-icon">⚠️</span>
                <div>
                  <strong>Error:</strong> {result.error}
                  {result.error.includes('credentials') && (
                    <div style={{ marginTop: 6, fontSize: 12 }}>
                      <Link to="/settings/credentials" style={{ color: 'var(--accent)' }}>
                        Configure API credentials →
                      </Link>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Plan metadata */}
            {result.plan && (
              <div className="nlquery-plan">
                <span className="nlquery-plan-label">Query plan:</span> {result.plan}
                {result.metadata?.model_used && (
                  <span className="nlquery-model-badge">{result.metadata.model_used}</span>
                )}
              </div>
            )}

            {/* AI Answer */}
            {result.answer && (
              <div className="nlquery-answer">
                <div className="nlquery-answer-header">
                  <span className="nlquery-answer-icon">💡</span>
                  <span className="nlquery-answer-label">AI Analysis</span>
                </div>
                <div className="nlquery-answer-text">{result.answer}</div>
              </div>
            )}

            {/* Metadata summary */}
            {result.metadata && (
              <div className="nlquery-meta-row">
                <span>{result.metadata.queries_executed} queries executed</span>
                <span>·</span>
                <span>{result.metadata.total_results} total results</span>
                {result.metadata.model_used && (
                  <>
                    <span>·</span>
                    <span>{result.metadata.model_used}</span>
                  </>
                )}
              </div>
            )}

            {/* Data sections */}
            {result.data && (
              <div className="nlquery-data">
                {/* Posts */}
                <DataSection title="📰 Posts" count={result.data.posts.length}>
                  {result.data.posts.map((p) => (
                    <div key={p.id} className="nlquery-item">
                      <div className="nlquery-item-header">
                        <span className="nlquery-badge nlquery-badge--source">{p.source_type}</span>
                        {p.author && <span className="nlquery-item-author">{p.author}</span>}
                        {p.timestamp && (
                          <span className="nlquery-item-time">{relativeTime(p.timestamp)}</span>
                        )}
                      </div>
                      <div className="nlquery-item-content">{p.snippet}</div>
                      <Link
                        to={`/feed?post=${p.id}`}
                        className="nlquery-item-link"
                      >
                        View post →
                      </Link>
                    </div>
                  ))}
                </DataSection>

                {/* Entities */}
                <DataSection title="🔗 Entities" count={result.data.entities.length}>
                  <div className="nlquery-entity-grid">
                    {result.data.entities.map((e) => (
                      <Link key={e.id} to={`/entities/${e.id}`} className="nlquery-entity-card">
                        <div className="nlquery-entity-name">{e.name}</div>
                        <div className="nlquery-entity-meta">
                          <span className={`nlquery-badge nlquery-badge--entity-${e.type}`}>{e.type}</span>
                          <span>
                            {(e.mention_count ?? e.recent_mentions ?? 0)} mentions
                          </span>
                        </div>
                      </Link>
                    ))}
                  </div>
                </DataSection>

                {/* Events */}
                <DataSection title="🗺️ Geo Events" count={result.data.events.length}>
                  {result.data.events.map((ev) => (
                    <div key={ev.id} className="nlquery-item">
                      <div className="nlquery-item-header">
                        <span className="nlquery-badge nlquery-badge--geo">GEO</span>
                        <strong className="nlquery-item-place">{ev.place_name}</strong>
                        {ev.distance_km !== undefined && (
                          <span className="nlquery-item-dist">{ev.distance_km} km</span>
                        )}
                        {ev.timestamp && (
                          <span className="nlquery-item-time">{relativeTime(ev.timestamp)}</span>
                        )}
                      </div>
                      {ev.snippet && (
                        <div className="nlquery-item-content">{ev.snippet}</div>
                      )}
                      {ev.lat != null && ev.lng != null && (
                        <Link
                          to={`/map?lat=${ev.lat}&lng=${ev.lng}&post=${ev.post_id}`}
                          className="nlquery-item-link"
                        >
                          View on map →
                        </Link>
                      )}
                    </div>
                  ))}
                </DataSection>

                {/* Signals */}
                <DataSection title="📈 Market Signals" count={result.data.signals.length}>
                  {result.data.signals.map((s) => (
                    <div key={s.id} className="nlquery-item">
                      <div className="nlquery-item-header">
                        <span className={`nlquery-badge nlquery-badge--signal-${s.signal_type}`}>
                          {s.signal_type}
                        </span>
                        {s.severity && (
                          <span className={`nlquery-badge nlquery-badge--sev-${s.severity}`}>
                            {s.severity}
                          </span>
                        )}
                        {s.generated_at && (
                          <span className="nlquery-item-time">{relativeTime(s.generated_at)}</span>
                        )}
                      </div>
                      <strong className="nlquery-signal-title">{s.title}</strong>
                      <div className="nlquery-item-content">{s.summary}</div>
                      {s.affected_tickers && (
                        <div className="nlquery-signal-tickers">
                          Tickers: {s.affected_tickers}
                        </div>
                      )}
                    </div>
                  ))}
                </DataSection>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

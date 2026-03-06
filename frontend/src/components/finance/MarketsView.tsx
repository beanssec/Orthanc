import { useEffect, useRef, useState } from 'react';
import { useFinanceStore, type Quote, type CashtagPost } from '../../stores/financeStore';
import '../../styles/finance.css';

// ── Currency symbol map ─────────────────────────────────────
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$', AUD: 'A$', EUR: '€', GBP: '£', JPY: '¥', CAD: 'C$',
  CHF: 'CHF ', HKD: 'HK$', SGD: 'S$', NZD: 'NZ$', CNY: '¥',
};

function currencySymbol(code: string | null | undefined): string {
  if (!code) return '$';
  return CURRENCY_SYMBOLS[code.toUpperCase()] ?? (code + ' ');
}

// ── Helpers ────────────────────────────────────────────────

function fmt(value: number | null | undefined, decimals = 2): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function formatPrice(price: number, category: string): string {
  const decimals = category?.toLowerCase() === 'forex' ? 4 : 2;
  return fmt(price, decimals);
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—';
  const sign = value >= 0 ? '+' : '';
  return sign + value.toFixed(2) + '%';
}

function plClass(value: number | null | undefined): string {
  if (value == null) return '';
  if (value > 0) return 'fin-positive';
  if (value < 0) return 'fin-negative';
  return 'fin-neutral';
}

function sentimentClass(sentiment: string | undefined): string {
  if (!sentiment) return 'cashtag-sentiment--neutral';
  const s = sentiment.toLowerCase();
  if (s === 'bullish') return 'cashtag-sentiment--bullish';
  if (s === 'bearish') return 'cashtag-sentiment--bearish';
  return 'cashtag-sentiment--neutral';
}

function sentimentLabel(sentiment: string | undefined): string {
  if (!sentiment) return 'NEUTRAL';
  return sentiment.toUpperCase();
}

function formatTime(ts: string | null | undefined): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return '';
  return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function extractTicker(post: CashtagPost): string {
  // Try raw_json.ticker first, then parse from content
  if (post.raw_json?.ticker) return String(post.raw_json.ticker);
  const match = post.content?.match(/\$([A-Z]{1,6})/);
  return match ? match[1] : '';
}

// ── Watchlist Group ────────────────────────────────────────

interface WatchlistGroupProps {
  title: string;
  icon: string;
  quotes: Quote[];
  category?: string;
}

function WatchlistGroup({ title, icon, quotes, category = '' }: WatchlistGroupProps) {
  return (
    <div className="watchlist-group">
      <div className="watchlist-group__header">
        <span className="watchlist-group__icon">{icon}</span>
        {title}
      </div>
      {quotes.length === 0 ? (
        <div style={{ padding: '10px 12px', fontSize: 12, color: 'var(--text-muted)' }}>
          No data available
        </div>
      ) : (
        quotes.map((q) => (
          <div key={q.ticker} className="watchlist-quote-row">
            <span className="watchlist-quote__ticker">{q.ticker}</span>
            <span className="watchlist-quote__price">
              {q.price != null ? (
                <span className="fin-mono">{currencySymbol(q.currency)}{formatPrice(q.price, category)}</span>
              ) : (
                <span className="watchlist-no-price">N/A</span>
              )}
            </span>
            <span className={`watchlist-quote__change fin-mono ${plClass(q.change_pct)}`}>
              {fmtPct(q.change_pct)}
            </span>
            <div className="watchlist-quote__sparkline">
              <div className="watchlist-quote__spark-mini" style={{
                width: '60px', height: '20px', background: `linear-gradient(90deg, transparent, ${(q.change_pct ?? 0) >= 0 ? 'var(--success)' : 'var(--alert)'}20)`,
                borderRadius: '3px',
              }} />
            </div>
          </div>
        ))
      )}
    </div>
  );
}

// ── Cashtag Feed ───────────────────────────────────────────

interface CashtagFeedProps {
  posts: CashtagPost[];
  loading: boolean;
  error: string | null;
}

function CashtagFeed({ posts, loading, error }: CashtagFeedProps) {
  const [tickerFilter, setTickerFilter] = useState('');

  const tickers = Array.from(
    new Set(posts.map(extractTicker).filter(Boolean))
  ).sort();

  const filtered = tickerFilter
    ? posts.filter((p) => extractTicker(p) === tickerFilter)
    : posts;

  if (loading) {
    return (
      <div className="fin-loading">
        <span className="spinner" /> Loading cashtag feed…
      </div>
    );
  }

  if (error) {
    return <div className="fin-error">⚠ {error}</div>;
  }

  return (
    <div className="cashtag-section">
      <div className="cashtag-section__toolbar">
        <span className="fin-section-title" style={{ marginBottom: 0 }}>X Cashtag Mentions</span>
        {tickers.length > 0 && (
          <select
            className="select select-sm"
            style={{ width: 140 }}
            value={tickerFilter}
            onChange={(e) => setTickerFilter(e.target.value)}
          >
            <option value="">All Tickers</option>
            {tickers.map((t) => (
              <option key={t} value={t}>${t}</option>
            ))}
          </select>
        )}
        {tickerFilter && (
          <button className="btn btn-ghost btn-sm" onClick={() => setTickerFilter('')}>
            ✕ Clear
          </button>
        )}
      </div>

      {posts.length === 0 ? (
        <div className="cashtag-empty">
          <div style={{ fontSize: 24, marginBottom: 8 }}>🐦</div>
          <div>
            Cashtag monitoring uses your xAI API key to track $TICKER mentions on X.
            <br />
            Add holdings and configure your xAI key to start.
          </div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="cashtag-empty">No cashtag posts matching filter</div>
      ) : (
        <div className="cashtag-feed">
          {filtered.map((post, idx) => {
            const ticker = extractTicker(post);
            const sentiment = post.raw_json?.sentiment as string | undefined;
            const ts = (post.raw_json?.timestamp as string | undefined) ?? null;

            return (
              <div key={idx} className="cashtag-item">
                <div className="cashtag-item__meta">
                  {ticker && <span className="cashtag-item__ticker">${ticker}</span>}
                  {post.author && <span className="cashtag-item__author">{post.author.startsWith('@') ? post.author : '@' + post.author}</span>}
                  {sentiment && (
                    <span className={`cashtag-item__sentiment ${sentimentClass(sentiment)}`}>
                      {sentimentLabel(sentiment)}
                    </span>
                  )}
                  <span className="cashtag-item__time">{formatTime(ts)}</span>
                </div>
                {post.content && (
                  <div className="cashtag-item__content">{post.content}</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────

export function MarketsView() {
  const {
    watchlist,
    watchlistLoading,
    watchlistError,
    fetchWatchlist,
    cashtags,
    cashtagsLoading,
    cashtagsError,
    fetchCashtags,
  } = useFinanceStore();

  const watchlistIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cashtagsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  useEffect(() => {
    // Initial fetch
    fetchWatchlist().then(() => setLastRefresh(new Date()));
    fetchCashtags();

    // Auto-refresh every 60s for watchlist
    watchlistIntervalRef.current = setInterval(() => {
      fetchWatchlist().then(() => setLastRefresh(new Date()));
    }, 60_000);

    // Auto-refresh every 120s for cashtags
    cashtagsIntervalRef.current = setInterval(() => {
      fetchCashtags();
    }, 120_000);

    return () => {
      if (watchlistIntervalRef.current) clearInterval(watchlistIntervalRef.current);
      if (cashtagsIntervalRef.current) clearInterval(cashtagsIntervalRef.current);
    };
  }, [fetchWatchlist, fetchCashtags]);

  const indices = watchlist?.indices ?? [];
  const commodities = watchlist?.commodities ?? [];
  const forex = watchlist?.forex ?? [];
  const crypto = watchlist?.crypto ?? [];

  return (
    <div className="markets-view">
      {/* ── Header ── */}
      <div className="markets-header">
        <span className="markets-header__title">📈 Markets</span>
        <div className="markets-header__refresh">
          {watchlistLoading && <span className="spinner" style={{ width: 12, height: 12 }} />}
          {lastRefresh && (
            <span>Updated {lastRefresh.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
          )}
          <span>· Refreshes every 60s</span>
        </div>
      </div>

      {/* ── Market Overview ── */}
      <div className="watchlist-section">
        <div className="fin-section-title">Market Overview</div>

        {watchlistLoading && !watchlist ? (
          <div className="fin-loading">
            <span className="spinner" /> Loading market data…
          </div>
        ) : watchlistError ? (
          <div className="fin-error">⚠ {watchlistError}</div>
        ) : (
          <div className="watchlist-groups">
            <WatchlistGroup title="Indices" icon="📊" quotes={indices} category="indices" />
            <WatchlistGroup title="Commodities" icon="🛢️" quotes={commodities} category="commodities" />
            <WatchlistGroup title="Forex" icon="💱" quotes={forex} category="forex" />
            <WatchlistGroup title="Crypto" icon="₿" quotes={crypto} category="crypto" />
          </div>
        )}
      </div>

      {/* ── Cashtag Feed ── */}
      <CashtagFeed
        posts={cashtags}
        loading={cashtagsLoading}
        error={cashtagsError}
      />
    </div>
  );
}

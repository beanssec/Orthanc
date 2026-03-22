import { useEffect, useState } from 'react';
import api from '../../services/api';
import { StrikeChart } from './StrikeChart';

// ── Types ──────────────────────────────────────────────────

export interface WidgetConfig {
  id: string;
  type: 'builtin' | 'api';
  title?: string;
  icon?: string;
  // builtin
  component?: string;
  // api
  endpoint?: string;
  viz?: 'table' | 'feed' | 'stat_cards';
  // grid position
  grid: { x: number; y: number; w: number; h: number };
}

interface WidgetCardProps {
  widget: WidgetConfig;
  onDelete?: (id: string) => void;
}

// ── Builtin Component Registry ─────────────────────────────

const BUILTIN_COMPONENTS: Record<string, React.ComponentType> = {
  StrikeChart: StrikeChart,
};

// ── API Widget Renderer ────────────────────────────────────

function ApiWidgetContent({
  endpoint,
  viz,
}: {
  endpoint: string;
  viz?: string;
}) {
  const [data, setData] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        setLoading(true);
        const res = await api.get(endpoint);
        if (!cancelled) {
          setData(res.data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load data');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => { cancelled = true; };
  }, [endpoint]);

  if (loading) {
    return <div className="widget-placeholder">⟳ Loading…</div>;
  }

  if (error) {
    return <div className="widget-error">⚠ {error}</div>;
  }

  // Feed viz
  if (viz === 'feed') {
    const items = Array.isArray(data) ? data : (data as { items?: unknown[] })?.items ?? [];
    return (
      <div className="widget-feed">
        {(items as Array<{ id?: string | number; title?: string; content?: string; summary?: string; published_at?: string; created_at?: string }>)
          .slice(0, 20)
          .map((item, i) => (
            <div key={item.id ?? i} className="widget-feed__item">
              {(item.title || item.summary) && (
                <div className="widget-feed__title">{item.title ?? item.summary}</div>
              )}
              {item.content && (
                <div className="widget-feed__content">{item.content}</div>
              )}
              {(item.published_at || item.created_at) && (
                <div className="widget-feed__time">
                  {formatRelativeTime(item.published_at ?? item.created_at)}
                </div>
              )}
            </div>
          ))}
        {items.length === 0 && <div className="widget-placeholder">No data</div>}
      </div>
    );
  }

  // Stat cards viz
  if (viz === 'stat_cards') {
    const items = Array.isArray(data) ? data : Object.entries(data as Record<string, number>).map(([label, value]) => ({ label, value }));
    return (
      <div className="widget-stat-cards">
        {(items as Array<{ label?: string; value?: string | number; key?: string }>).map((item, i) => (
          <div key={i} className="widget-stat-card">
            <div className="widget-stat-card__value">{item.value ?? '—'}</div>
            <div className="widget-stat-card__label">{item.label ?? item.key ?? `Item ${i + 1}`}</div>
          </div>
        ))}
      </div>
    );
  }

  // Table viz (default)
  const rows = Array.isArray(data) ? data : (data as { items?: unknown[] })?.items ?? [];
  if (rows.length === 0) {
    return <div className="widget-placeholder">No data</div>;
  }
  const cols = Object.keys((rows[0] as Record<string, unknown>) ?? {}).slice(0, 6);
  return (
    <table className="widget-table">
      <thead>
        <tr>
          {cols.map((col) => (
            <th key={col}>{col.replace(/_/g, ' ')}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {(rows as Array<Record<string, unknown>>).slice(0, 50).map((row, i) => (
          <tr key={i}>
            {cols.map((col) => (
              <td key={col}>
                {String(row[col] ?? '')}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Helper ─────────────────────────────────────────────────

function formatRelativeTime(ts?: string | null): string {
  if (!ts) return '';
  const d = new Date(ts);
  const diffMs = Date.now() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return d.toLocaleDateString();
}

// ── WidgetCard ─────────────────────────────────────────────

export function WidgetCard({ widget, onDelete }: WidgetCardProps) {
  const renderContent = () => {
    if (widget.type === 'builtin') {
      const name = widget.component ?? '';
      const Component = BUILTIN_COMPONENTS[name];
      if (Component) {
        return <Component />;
      }
      return (
        <div className="widget-placeholder">
          📦 Widget: {name || '(unnamed)'}
        </div>
      );
    }

    if (widget.type === 'api') {
      if (!widget.endpoint) {
        return <div className="widget-error">No endpoint configured</div>;
      }
      return <ApiWidgetContent endpoint={widget.endpoint} viz={widget.viz} />;
    }

    return <div className="widget-placeholder">Unknown widget type</div>;
  };

  const hasPad = widget.type === 'builtin' && BUILTIN_COMPONENTS[widget.component ?? ''];

  return (
    <div className="widget-card">
      {widget.title && (
        <div className="widget-card__header">
          {widget.icon && <span className="widget-card__icon">{widget.icon}</span>}
          <span className="widget-card__title">{widget.title}</span>
          {onDelete && (
            <div className="widget-card__actions">
              <button
                className="widget-card__action widget-card__action--delete"
                onClick={() => onDelete(widget.id)}
                title="Remove widget"
              >
                ✕
              </button>
            </div>
          )}
        </div>
      )}
      {!widget.title && onDelete && (
        <div className="widget-card__header" style={{ justifyContent: 'flex-end', minHeight: 'unset', padding: '4px 8px', background: 'transparent', border: 'none' }}>
          <div className="widget-card__actions" style={{ opacity: 1 }}>
            <button
              className="widget-card__action widget-card__action--delete"
              onClick={() => onDelete(widget.id)}
              title="Remove widget"
            >
              ✕
            </button>
          </div>
        </div>
      )}
      <div className={`widget-card__body${hasPad ? ' widget-card__body--no-pad' : ''}`}>
        {renderContent()}
      </div>
    </div>
  );
}

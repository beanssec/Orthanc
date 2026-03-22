import { useEffect, useState } from 'react';
import api from '../../services/api';
import { StrikeChart } from './StrikeChart';
import { WidgetEditModal } from './WidgetEditModal';

// ── Types ──────────────────────────────────────────────────

export interface WidgetConfig {
  id: string;
  type: 'builtin' | 'api';
  title?: string;
  icon?: string;
  // builtin
  component?: string;
  // api (legacy direct)
  endpoint?: string;
  // api (preferred)
  data_source?: {
    endpoint: string;
    params?: Record<string, unknown>;
  };
  viz?: 'table' | 'feed' | 'stat_cards' | 'line_chart' | 'bar_chart' | 'donut';
  config?: Record<string, unknown>;
  // grid position
  grid: { x: number; y: number; w: number; h: number };
}

interface WidgetCardProps {
  widget: WidgetConfig;
  onDelete?: (id: string) => void;
  onEdit?: (updated: WidgetConfig) => void;
}

// ── Builtin Component Registry ─────────────────────────────

const BUILTIN_COMPONENTS: Record<string, React.ComponentType> = {
  StrikeChart: StrikeChart,
};

// ── OQL Result Shape Detection ─────────────────────────────

function detectOqlViz(data: unknown): WidgetConfig['viz'] {
  // Single number
  if (typeof data === 'number') return 'stat_cards';

  // Object with a single numeric value (e.g. { count: 42 })
  if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
    const vals = Object.values(data as Record<string, unknown>);
    if (vals.length === 1 && typeof vals[0] === 'number') return 'stat_cards';
  }

  if (Array.isArray(data) && data.length > 0) {
    const first = data[0] as Record<string, unknown>;
    const keys = Object.keys(first);

    // Array of {date/time, value} → line chart
    if (
      keys.length === 2 &&
      keys.some((k) => /date|time|day|hour|ts|timestamp/.test(k.toLowerCase())) &&
      keys.some((k) => /value|count|total|num/.test(k.toLowerCase()))
    ) {
      return 'line_chart';
    }

    // Array of {label, value} → bar chart
    if (
      keys.length === 2 &&
      keys.some((k) => /label|name|key|group|category/.test(k.toLowerCase())) &&
      keys.some((k) => /value|count|total|num/.test(k.toLowerCase()))
    ) {
      return 'bar_chart';
    }
  }

  // Default to table
  return 'table';
}

// ── API Widget Renderer ────────────────────────────────────

function ApiWidgetContent({ widget }: { widget: WidgetConfig }) {
  const endpoint = widget.data_source?.endpoint ?? widget.endpoint ?? '';
  const params = widget.data_source?.params ?? {};
  const viz = widget.viz;

  const [data, setData] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!endpoint) {
      setError('No endpoint configured');
      setLoading(false);
      return;
    }

    let cancelled = false;
    const fetchData = async () => {
      try {
        setLoading(true);

        // Build URL with params
        const searchParams = new URLSearchParams();
        for (const [key, value] of Object.entries(params)) {
          if (Array.isArray(value)) {
            value.forEach((v) => searchParams.append(key, String(v)));
          } else if (value !== null && value !== undefined) {
            searchParams.set(key, String(value));
          }
        }
        const url = searchParams.toString() ? `${endpoint}?${searchParams}` : endpoint;

        const res = await api.get(url);
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
  // Stringify params to detect deep changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, JSON.stringify(params)]);

  if (loading) {
    return <div className="widget-placeholder">⟳ Loading…</div>;
  }

  if (error) {
    return <div className="widget-error">⚠ {error}</div>;
  }

  // OQL auto-detection: if endpoint is /query, pick the best viz based on data shape
  const isOql = endpoint === '/query';
  const resolvedViz = isOql ? detectOqlViz(data) : viz;

  // Feed viz
  if (resolvedViz === 'feed') {
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
  if (resolvedViz === 'stat_cards') {
    const items = Array.isArray(data)
      ? data
      : Object.entries(data as Record<string, number>).map(([label, value]) => ({ label, value }));
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

  // Bar chart viz (simple horizontal bars)
  if (resolvedViz === 'bar_chart') {
    const rows = Array.isArray(data) ? data : [];
    const items = rows as Array<Record<string, unknown>>;
    const keys = items.length > 0 ? Object.keys(items[0]) : [];
    const labelKey = keys.find((k) => /label|name|key|group|category/.test(k.toLowerCase())) ?? keys[0];
    const valueKey = keys.find((k) => /value|count|total|num/.test(k.toLowerCase())) ?? keys[1];
    if (!labelKey || !valueKey) {
      // Fallback to table
    } else {
      const maxVal = Math.max(...items.map((r) => Number(r[valueKey] ?? 0)), 1);
      return (
        <div className="widget-bar-chart">
          {items.slice(0, 20).map((row, i) => {
            const pct = (Number(row[valueKey] ?? 0) / maxVal) * 100;
            return (
              <div key={i} className="widget-bar-chart__row">
                <div className="widget-bar-chart__label">{String(row[labelKey] ?? '')}</div>
                <div className="widget-bar-chart__track">
                  <div className="widget-bar-chart__bar" style={{ width: `${pct}%` }} />
                </div>
                <div className="widget-bar-chart__value">{String(row[valueKey] ?? '')}</div>
              </div>
            );
          })}
        </div>
      );
    }
  }

  // Line chart viz (simple sparkline-style using CSS)
  if (resolvedViz === 'line_chart') {
    const rows = Array.isArray(data) ? data : [];
    const items = rows as Array<Record<string, unknown>>;
    if (items.length > 0) {
      const keys = Object.keys(items[0]);
      const dateKey = keys.find((k) => /date|time|day|hour|ts|timestamp/.test(k.toLowerCase())) ?? keys[0];
      const valueKey = keys.find((k) => /value|count|total|num/.test(k.toLowerCase())) ?? keys[1];
      const maxVal = Math.max(...items.map((r) => Number(r[valueKey] ?? 0)), 1);
      return (
        <div className="widget-line-chart">
          <div className="widget-line-chart__bars">
            {items.slice(-30).map((row, i) => {
              const pct = (Number(row[valueKey] ?? 0) / maxVal) * 100;
              return (
                <div
                  key={i}
                  className="widget-line-chart__col"
                  title={`${row[dateKey]}: ${row[valueKey]}`}
                >
                  <div className="widget-line-chart__bar" style={{ height: `${pct}%` }} />
                </div>
              );
            })}
          </div>
          {items.length > 0 && (
            <div className="widget-line-chart__labels">
              <span>{String(items[0][dateKey] ?? '')}</span>
              <span>{String(items[items.length - 1][dateKey] ?? '')}</span>
            </div>
          )}
        </div>
      );
    }
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

export function WidgetCard({ widget, onDelete, onEdit }: WidgetCardProps) {
  const [showEditModal, setShowEditModal] = useState(false);

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
      const endpoint = widget.data_source?.endpoint ?? widget.endpoint;
      if (!endpoint) {
        return <div className="widget-error">No endpoint configured</div>;
      }
      return <ApiWidgetContent widget={widget} />;
    }

    return <div className="widget-placeholder">Unknown widget type</div>;
  };

  const hasPad = widget.type === 'builtin' && BUILTIN_COMPONENTS[widget.component ?? ''];

  const handleSaveEdit = (updated: WidgetConfig) => {
    setShowEditModal(false);
    onEdit?.(updated);
  };

  const renderActions = () => (
    <div className="widget-card__actions">
      {onEdit && (
        <button
          className="widget-card__action"
          onClick={() => setShowEditModal(true)}
          title="Edit widget"
          style={{ color: 'var(--text-muted)' }}
        >
          ✎
        </button>
      )}
      {onDelete && (
        <button
          className="widget-card__action widget-card__action--delete"
          onClick={() => onDelete(widget.id)}
          title="Remove widget"
        >
          ✕
        </button>
      )}
    </div>
  );

  return (
    <>
      <div className="widget-card">
        {widget.title ? (
          <div className="widget-card__header">
            {widget.icon && <span className="widget-card__icon">{widget.icon}</span>}
            <span className="widget-card__title">{widget.title}</span>
            {(onDelete || onEdit) && renderActions()}
          </div>
        ) : (onDelete || onEdit) ? (
          <div
            className="widget-card__header"
            style={{
              justifyContent: 'flex-end',
              minHeight: 'unset',
              padding: '4px 8px',
              background: 'transparent',
              border: 'none',
            }}
          >
            <div style={{ opacity: 1 }}>
              {renderActions()}
            </div>
          </div>
        ) : null}
        <div className={`widget-card__body${hasPad ? ' widget-card__body--no-pad' : ''}`}>
          {renderContent()}
        </div>
      </div>

      {showEditModal && (
        <WidgetEditModal
          widget={widget}
          onSave={handleSaveEdit}
          onCancel={() => setShowEditModal(false)}
        />
      )}
    </>
  );
}

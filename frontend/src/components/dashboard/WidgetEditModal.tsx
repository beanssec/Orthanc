import { useState } from 'react';
import { WidgetConfig } from './WidgetCard';

// ── Known builtin components ───────────────────────────────
const BUILTIN_OPTIONS = [
  'StrikeChart',
  'KPIStrip',
  'SourceHealthStrip',
  'VelocityChart',
  'TrendingEntities',
  'TrendingNarratives',
  'GeoHotspots',
  'RecentAlerts',
  'ActivityFeed',
  'PortfolioSummary',
];

const VIZ_OPTIONS: Array<{ value: WidgetConfig['viz']; label: string }> = [
  { value: 'table', label: 'Table' },
  { value: 'feed', label: 'Feed' },
  { value: 'stat_cards', label: 'Stat Cards' },
  { value: 'line_chart', label: 'Line Chart' },
  { value: 'bar_chart', label: 'Bar Chart' },
  { value: 'donut', label: 'Donut Chart' },
];

// ── Param pair type ────────────────────────────────────────
interface ParamPair {
  key: string;
  value: string;
}

function paramsToArray(params: Record<string, unknown>): ParamPair[] {
  return Object.entries(params).map(([key, value]) => ({
    key,
    value: Array.isArray(value) ? value.join(',') : String(value ?? ''),
  }));
}

function arrayToParams(pairs: ParamPair[]): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const { key, value } of pairs) {
    if (!key.trim()) continue;
    // If value contains commas, treat as array
    if (value.includes(',')) {
      result[key.trim()] = value.split(',').map((v) => v.trim()).filter(Boolean);
    } else {
      // Coerce numeric strings
      const num = Number(value);
      result[key.trim()] = value !== '' && !isNaN(num) ? num : value;
    }
  }
  return result;
}

// ── Modal ──────────────────────────────────────────────────

interface WidgetEditModalProps {
  widget: WidgetConfig;
  onSave: (updated: WidgetConfig) => void;
  onCancel: () => void;
}

export function WidgetEditModal({ widget, onSave, onCancel }: WidgetEditModalProps) {
  const [title, setTitle] = useState(widget.title ?? '');
  const [icon, setIcon] = useState(widget.icon ?? '');
  const [type, setType] = useState<'builtin' | 'api'>(widget.type);
  const [component, setComponent] = useState(widget.component ?? BUILTIN_OPTIONS[0]);

  // Resolve endpoint from data_source or legacy endpoint field
  const initialEndpoint = widget.data_source?.endpoint ?? widget.endpoint ?? '';
  const initialParams = widget.data_source?.params ?? {};

  const [endpoint, setEndpoint] = useState(initialEndpoint);
  const [paramPairs, setParamPairs] = useState<ParamPair[]>(
    paramsToArray(initialParams).length > 0
      ? paramsToArray(initialParams)
      : [{ key: '', value: '' }]
  );
  const [viz, setViz] = useState<WidgetConfig['viz']>(widget.viz ?? 'table');

  const [gridW, setGridW] = useState(widget.grid.w);
  const [gridH, setGridH] = useState(widget.grid.h);

  const handleParamChange = (i: number, field: 'key' | 'value', val: string) => {
    setParamPairs((prev) => prev.map((p, idx) => idx === i ? { ...p, [field]: val } : p));
  };

  const handleAddParam = () => {
    setParamPairs((prev) => [...prev, { key: '', value: '' }]);
  };

  const handleRemoveParam = (i: number) => {
    setParamPairs((prev) => prev.filter((_, idx) => idx !== i));
  };

  const handleSave = () => {
    const updatedParams = arrayToParams(paramPairs);
    const updated: WidgetConfig = {
      ...widget,
      title: title || undefined,
      icon: icon || undefined,
      type,
      grid: { ...widget.grid, w: gridW, h: gridH },
    };

    if (type === 'builtin') {
      updated.component = component;
      delete updated.endpoint;
      delete updated.data_source;
      delete updated.viz;
    } else {
      // API type
      updated.data_source = {
        endpoint,
        params: Object.keys(updatedParams).length > 0 ? updatedParams : undefined,
      };
      updated.viz = viz;
      delete updated.endpoint; // remove legacy field
      delete updated.component;
    }

    onSave(updated);
  };

  // ── Styles ───────────────────────────────────────────────
  const overlayStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.6)',
    zIndex: 1000,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  };

  const modalStyle: React.CSSProperties = {
    background: 'var(--bg-surface, #1a1f2e)',
    border: '1px solid var(--border, #2a3040)',
    borderRadius: '10px',
    padding: '24px',
    minWidth: '420px',
    maxWidth: '560px',
    width: '100%',
    maxHeight: '90vh',
    overflowY: 'auto',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  };

  const titleStyle: React.CSSProperties = {
    fontSize: '15px',
    fontWeight: 600,
    color: 'var(--text, #e2e8f0)',
    marginBottom: '4px',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: '11px',
    fontWeight: 500,
    color: 'var(--text-muted, #6b7280)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginBottom: '4px',
    display: 'block',
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    background: 'var(--bg, #0f1117)',
    border: '1px solid var(--border, #2a3040)',
    borderRadius: '6px',
    color: 'var(--text, #e2e8f0)',
    padding: '7px 10px',
    fontSize: '13px',
    outline: 'none',
    boxSizing: 'border-box',
  };

  const selectStyle: React.CSSProperties = {
    ...inputStyle,
    cursor: 'pointer',
  };

  const rowStyle: React.CSSProperties = {
    display: 'flex',
    gap: '8px',
    alignItems: 'flex-start',
  };

  const fieldStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
  };

  const sectionStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
    paddingTop: '4px',
    borderTop: '1px solid var(--border, #2a3040)',
  };

  const btnSmStyle: React.CSSProperties = {
    padding: '4px 10px',
    borderRadius: '5px',
    border: '1px solid var(--border, #2a3040)',
    background: 'transparent',
    color: 'var(--text-muted, #6b7280)',
    fontSize: '12px',
    cursor: 'pointer',
  };

  const btnDangerStyle: React.CSSProperties = {
    ...btnSmStyle,
    color: '#ef4444',
    borderColor: '#ef444440',
  };

  return (
    <div style={overlayStyle} onClick={onCancel}>
      <div style={modalStyle} onClick={(e) => e.stopPropagation()}>
        <div style={titleStyle}>✎ Edit Widget</div>

        {/* Title + Icon row */}
        <div style={rowStyle}>
          <div style={{ ...fieldStyle, maxWidth: '60px' }}>
            <label style={labelStyle}>Icon</label>
            <input
              style={inputStyle}
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              placeholder="📊"
              maxLength={4}
            />
          </div>
          <div style={fieldStyle}>
            <label style={labelStyle}>Title</label>
            <input
              style={inputStyle}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Widget title (optional)"
              maxLength={64}
            />
          </div>
        </div>

        {/* Widget Type */}
        <div style={fieldStyle}>
          <label style={labelStyle}>Widget Type</label>
          <select
            style={selectStyle}
            value={type}
            onChange={(e) => setType(e.target.value as 'builtin' | 'api')}
          >
            <option value="builtin">Built-in Component</option>
            <option value="api">API / Data Feed</option>
          </select>
        </div>

        {/* Type-specific fields */}
        {type === 'builtin' ? (
          <div style={sectionStyle}>
            <div style={fieldStyle}>
              <label style={labelStyle}>Component</label>
              <select
                style={selectStyle}
                value={component}
                onChange={(e) => setComponent(e.target.value)}
              >
                {BUILTIN_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <div style={sectionStyle}>
            {/* Endpoint */}
            <div style={fieldStyle}>
              <label style={labelStyle}>Endpoint URL</label>
              <input
                style={inputStyle}
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                placeholder="/narratives/"
              />
            </div>

            {/* Params */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={labelStyle}>Query Parameters</label>
              {paramPairs.map((pair, i) => (
                <div key={i} style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                  <input
                    style={{ ...inputStyle, flex: '0 0 35%' }}
                    value={pair.key}
                    onChange={(e) => handleParamChange(i, 'key', e.target.value)}
                    placeholder="key"
                  />
                  <input
                    style={{ ...inputStyle, flex: 1 }}
                    value={pair.value}
                    onChange={(e) => handleParamChange(i, 'value', e.target.value)}
                    placeholder="value (use commas for arrays)"
                  />
                  <button
                    style={{ ...btnDangerStyle, padding: '5px 8px', flexShrink: 0 }}
                    onClick={() => handleRemoveParam(i)}
                    title="Remove parameter"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button style={btnSmStyle} onClick={handleAddParam}>
                + Add Parameter
              </button>
            </div>

            {/* Viz type */}
            <div style={fieldStyle}>
              <label style={labelStyle}>Visualization</label>
              <select
                style={selectStyle}
                value={viz ?? 'table'}
                onChange={(e) => setViz(e.target.value as WidgetConfig['viz'])}
              >
                {VIZ_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Grid Size */}
        <div style={sectionStyle}>
          <label style={labelStyle}>Grid Size</label>
          <div style={rowStyle}>
            <div style={fieldStyle}>
              <label style={{ ...labelStyle, textTransform: 'none', fontWeight: 400 }}>Width (1–12 cols)</label>
              <input
                style={inputStyle}
                type="number"
                min={1}
                max={12}
                value={gridW}
                onChange={(e) => setGridW(Math.max(1, Math.min(12, Number(e.target.value))))}
              />
            </div>
            <div style={fieldStyle}>
              <label style={{ ...labelStyle, textTransform: 'none', fontWeight: 400 }}>Height (1–8 rows)</label>
              <input
                style={inputStyle}
                type="number"
                min={1}
                max={8}
                value={gridH}
                onChange={(e) => setGridH(Math.max(1, Math.min(8, Number(e.target.value))))}
              />
            </div>
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', paddingTop: '4px' }}>
          <button
            style={{ ...btnSmStyle, padding: '7px 16px' }}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            style={{
              padding: '7px 16px',
              borderRadius: '6px',
              border: 'none',
              background: 'var(--accent, #3b82f6)',
              color: '#fff',
              fontSize: '13px',
              fontWeight: 500,
              cursor: 'pointer',
            }}
            onClick={handleSave}
          >
            Save Widget
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * VizBuilder — Visualization selector and renderer for OQL query results.
 * Sits below the results table in QueryView. Auto-selects chart type from
 * visualization_hint. Allows override via toolbar. Saves to dashboard.
 */
import { useState } from 'react';
import api from '../../services/api';
import { BarChart } from '../charts/BarChart';
import { DonutChart } from '../charts/DonutChart';
import { StatCard } from '../charts/StatCard';
import { TimeSeriesChart } from '../charts/TimeSeriesChart';

// ── Types ────────────────────────────────────────────────────────────────────

interface OQLColumn {
  name: string;
  type: string;
}

export interface VizBuilderProps {
  columns: OQLColumn[];
  rows: Record<string, unknown>[];
  visualizationHint: string;
  queryText: string;
}

type VizType = 'table' | 'bar' | 'line' | 'donut' | 'stat';

interface VizConfig {
  type: VizType;
  x_field?: string;
  y_field?: string;
  series?: string[];
  title?: string;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_ICONS: Record<VizType, string> = {
  table: '📋',
  bar: '📊',
  line: '📈',
  donut: '🍩',
  stat: '🔢',
};

const TYPE_LABELS: Record<VizType, string> = {
  table: 'Table',
  bar: 'Bar',
  line: 'Line',
  donut: 'Donut',
  stat: 'Stat',
};

const NUM_COL_TYPES = new Set(['int', 'integer', 'float', 'numeric', 'mixed', 'count', 'number']);

function isNumericColumn(col: OQLColumn): boolean {
  return (
    NUM_COL_TYPES.has(col.type.toLowerCase()) ||
    col.name === 'count' ||
    col.name.startsWith('count') ||
    col.name.endsWith('_count') ||
    col.name === 'value' ||
    col.name === 'total'
  );
}

function isStringColumn(col: OQLColumn): boolean {
  return !isNumericColumn(col) && col.name !== 'bucket';
}

/** Determine the initial viz type from the hint + data shape */
function autoSelectType(
  hint: string,
  columns: OQLColumn[],
  rows: Record<string, unknown>[]
): VizType {
  // Single row, single numeric col → stat card
  if (rows.length === 1) {
    const numericCols = columns.filter(isNumericColumn);
    if (numericCols.length === 1 && columns.length <= 2) {
      return 'stat';
    }
  }

  switch (hint) {
    case 'bar': return 'bar';
    case 'pie': return 'donut';
    case 'timeseries': return 'line';
    default: return 'table';
  }
}

/** Build BarChart data from columns+rows (finds string col as label, numeric col as value) */
function buildBarData(
  columns: OQLColumn[],
  rows: Record<string, unknown>[]
): Array<{ label: string; value: number }> {
  const labelCol = columns.find(isStringColumn);
  const valueCol = columns.find(isNumericColumn);
  if (!labelCol || !valueCol) return [];

  return rows.map((row) => ({
    label: String(row[labelCol.name] ?? ''),
    value: Number(row[valueCol.name]) || 0,
  }));
}

/** Build TimeSeriesChart data from columns+rows */
function buildTimeSeriesData(
  columns: OQLColumn[],
  rows: Record<string, unknown>[]
): { data: Array<{ bucket: string; [key: string]: string | number }>; series: string[] } {
  const bucketCol = columns.find((c) => c.name === 'bucket');
  if (!bucketCol) {
    // Fallback: first string col as bucket
    const strCol = columns.find(isStringColumn);
    if (!strCol) return { data: [], series: [] };
    const seriesCols = columns.filter(isNumericColumn);
    const data = rows.map((row) => {
      const entry: Record<string, string | number> = { bucket: String(row[strCol.name] ?? '') };
      for (const s of seriesCols) entry[s.name] = Number(row[s.name]) || 0;
      return entry;
    });
    return { data, series: seriesCols.map((c) => c.name) };
  }

  const seriesCols = columns.filter((c) => c.name !== 'bucket' && isNumericColumn(c));
  const data = rows.map((row) => {
    const entry: Record<string, string | number> = { bucket: String(row[bucketCol.name] ?? '') };
    for (const s of seriesCols) entry[s.name] = Number(row[s.name]) || 0;
    return entry;
  });
  return { data, series: seriesCols.map((c) => c.name) };
}

/** Build StatCard props from first row + first numeric col */
function buildStatData(
  columns: OQLColumn[],
  rows: Record<string, unknown>[]
): { value: number | string; label: string } | null {
  if (!rows.length) return null;
  const numCol = columns.find(isNumericColumn);
  if (!numCol) return null;
  const labelCol = columns.find(isStringColumn);
  return {
    value: Number(rows[0][numCol.name]) || 0,
    label: labelCol ? String(rows[0][labelCol.name] ?? numCol.name) : numCol.name,
  };
}

/** Build VizConfig for saving */
function buildVizConfig(
  type: VizType,
  columns: OQLColumn[],
  rows: Record<string, unknown>[]
): VizConfig {
  const labelCol = columns.find(isStringColumn);
  const valueCol = columns.find(isNumericColumn);
  const seriesCols = columns.filter(isNumericColumn);

  return {
    type,
    x_field: labelCol?.name ?? columns.find((c) => c.name === 'bucket')?.name,
    y_field: valueCol?.name,
    series: seriesCols.map((c) => c.name),
    title: buildDefaultTitle(type, labelCol?.name, valueCol?.name),
  };
}

function buildDefaultTitle(
  type: VizType,
  xField?: string,
  yField?: string
): string {
  if (type === 'stat' && yField) return yField;
  if (xField && yField) return `${yField} by ${xField}`;
  if (xField) return `by ${xField}`;
  return 'Query Result';
}

// ── Save Dialog ───────────────────────────────────────────────────────────────

function VizSaveDialog({
  queryText,
  vizConfig,
  onClose,
  onSaved,
}: {
  queryText: string;
  vizConfig: VizConfig;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(vizConfig.title ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSave = async () => {
    const trimmed = name.trim();
    if (!trimmed) { setError('Name is required'); return; }
    setSaving(true);
    setError('');
    try {
      await api.post('/oql/save', {
        name: trimmed,
        query_text: queryText,
        description: `Visualization: ${vizConfig.type}`,
        is_pinned: true,
        visualization_config: vizConfig,
      });
      onSaved();
      onClose();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: { error?: string } | string } }; message?: string };
      const detail = err?.response?.data?.detail;
      const msg =
        typeof detail === 'object' && detail !== null && 'error' in detail
          ? detail.error
          : typeof detail === 'string'
          ? detail
          : err?.message ?? 'Save failed';
      setError(String(msg));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="viz-save-dialog-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="viz-save-dialog">
        <h3>Save to Dashboard</h3>
        <input
          className="viz-dialog-input"
          placeholder="Panel name…"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
        />
        {error && <div className="viz-dialog-error">{error}</div>}
        <div className="viz-dialog-actions">
          <button className="oql-btn-secondary" onClick={onClose}>Cancel</button>
          <button className="oql-btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : '📌 Pin to Dashboard'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── VizBuilder ────────────────────────────────────────────────────────────────

export function VizBuilder({ columns, rows, visualizationHint, queryText }: VizBuilderProps) {
  const [activeType, setActiveType] = useState<VizType>(() =>
    autoSelectType(visualizationHint, columns, rows)
  );
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [savedMsg, setSavedMsg] = useState(false);

  // Don't render if there's no data or it's pure table mode
  if (!rows.length || !columns.length) return null;
  // Only render if there's a visualization to show (skip plain table results)
  if (visualizationHint === 'table' && activeType === 'table') return null;

  const vizConfig = buildVizConfig(activeType, columns, rows);

  const VIZ_TYPES: VizType[] = ['table', 'bar', 'line', 'donut', 'stat'];

  const renderChart = () => {
    switch (activeType) {
      case 'bar': {
        const barData = buildBarData(columns, rows);
        if (!barData.length) {
          return <div className="chart-empty">Cannot map columns to bar chart</div>;
        }
        return <BarChart data={barData} />;
      }

      case 'donut': {
        const donutData = buildBarData(columns, rows);
        if (!donutData.length) {
          return <div className="chart-empty">Cannot map columns to donut chart</div>;
        }
        return <DonutChart data={donutData} size={220} />;
      }

      case 'line': {
        const { data: tsData, series } = buildTimeSeriesData(columns, rows);
        if (!tsData.length || !series.length) {
          return <div className="chart-empty">Cannot map columns to time series</div>;
        }
        return <TimeSeriesChart data={tsData} series={series} />;
      }

      case 'stat': {
        const statData = buildStatData(columns, rows);
        if (!statData) {
          return <div className="chart-empty">Cannot map columns to stat card</div>;
        }
        return <StatCard value={statData.value} label={statData.label} />;
      }

      case 'table':
      default:
        return null;
    }
  };

  const chart = renderChart();
  if (activeType === 'table' && !chart) return null;

  return (
    <div className="viz-builder">
      {/* Toolbar */}
      <div className="viz-toolbar">
        <span className="viz-toolbar-label">Viz</span>
        {VIZ_TYPES.map((t) => (
          <button
            key={t}
            className={`viz-type-btn${activeType === t ? ' active' : ''}`}
            onClick={() => setActiveType(t)}
            title={TYPE_LABELS[t]}
          >
            {TYPE_ICONS[t]} {TYPE_LABELS[t]}
          </button>
        ))}
        <button
          className="viz-save-btn"
          onClick={() => setShowSaveDialog(true)}
          title="Save visualization to dashboard"
        >
          {savedMsg ? '✓ Saved!' : '📌 Save to Dashboard'}
        </button>
      </div>

      {/* Chart area */}
      {chart && (
        <div className="viz-chart-area">
          {chart}
        </div>
      )}

      {/* Save dialog */}
      {showSaveDialog && (
        <VizSaveDialog
          queryText={queryText}
          vizConfig={vizConfig}
          onClose={() => setShowSaveDialog(false)}
          onSaved={() => {
            setSavedMsg(true);
            setTimeout(() => setSavedMsg(false), 3000);
          }}
        />
      )}
    </div>
  );
}

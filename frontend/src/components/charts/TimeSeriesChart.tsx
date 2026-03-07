import React from 'react'
/**
 * TimeSeriesChart — SVG line/area chart for time-bucketed data.
 * Uses ResizeObserver for responsive sizing. No external libraries.
 */
import { useEffect, useRef, useState } from 'react';

const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
  '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16',
];

export interface TimeSeriesChartProps {
  data: Array<{ bucket: string; [key: string]: string | number }>;
  series: string[];
  width?: number;
  height?: number;
  onPointClick?: (bucket: string) => void;
}

type Span = 'minutes' | 'hours' | 'days';

function detectSpan(data: Array<{ bucket: string }>): Span {
  if (data.length < 2) return 'hours';
  const first = new Date(data[0].bucket);
  const last = new Date(data[data.length - 1].bucket);
  const diffMs = Math.abs(last.getTime() - first.getTime());
  const diffHours = diffMs / (1000 * 60 * 60);
  if (diffHours <= 2) return 'minutes';
  if (diffHours <= 48) return 'hours';
  return 'days';
}

function formatBucket(bucket: string, span: Span): string {
  const d = new Date(bucket);
  if (isNaN(d.getTime())) return bucket;
  if (span === 'minutes') {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  if (span === 'hours') {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function formatValue(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return String(Math.round(v));
}

export function TimeSeriesChart({ data, series, onPointClick }: TimeSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 600, h: 280 });
  const [crosshairIdx, setCrosshairIdx] = useState<number | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const { width } = entries[0].contentRect;
      if (width > 0) {
        setDims({ w: width, h: Math.max(200, Math.min(400, width * 0.4)) });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (!data.length || !series.length) {
    return <div className="chart-container"><div className="chart-empty">No data</div></div>;
  }

  const pad = { left: 54, right: 20, top: 16, bottom: 40 };
  const plotW = Math.max(dims.w - pad.left - pad.right, 1);
  const plotH = Math.max(dims.h - pad.top - pad.bottom, 1);
  const span = detectSpan(data);

  // Compute Y range across all series (always start from 0)
  let maxY = 1;
  for (const row of data) {
    for (const s of series) {
      const v = Number(row[s]) || 0;
      if (v > maxY) maxY = v;
    }
  }
  const minY = 0;

  const xScale = (i: number) =>
    pad.left + (data.length <= 1 ? plotW / 2 : (i / (data.length - 1)) * plotW);
  const yScale = (v: number) =>
    pad.top + (1 - (v - minY) / (maxY - minY)) * plotH;

  // Y-axis ticks (5 ticks)
  const Y_TICKS = 5;
  const yTickValues = Array.from({ length: Y_TICKS + 1 }, (_, i) =>
    minY + (i / Y_TICKS) * (maxY - minY)
  );

  // X-axis ticks (max 8)
  const xTickCount = Math.min(8, data.length);
  const xTickStep = Math.max(1, Math.floor((data.length - 1) / (xTickCount - 1)));
  const xTickIndices = Array.from(new Set([
    ...Array.from({ length: xTickCount }, (_, i) => Math.min(i * xTickStep, data.length - 1)),
    data.length - 1,
  ])).sort((a, b) => a - b);

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    let closest = 0;
    let closestDist = Infinity;
    for (let i = 0; i < data.length; i++) {
      const dist = Math.abs(xScale(i) - mouseX);
      if (dist < closestDist) {
        closestDist = dist;
        closest = i;
      }
    }
    setCrosshairIdx(closest);
  };

  const handleMouseLeave = () => setCrosshairIdx(null);
  const handleClick = () => {
    if (crosshairIdx !== null && onPointClick) {
      onPointClick(data[crosshairIdx].bucket);
    }
  };

  const crosshairX = crosshairIdx !== null ? xScale(crosshairIdx) : null;

  return (
    <div className="chart-container timeseries-chart" ref={containerRef}>
      <svg
        width={dims.w}
        height={dims.h}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
      >
        {/* Y-axis grid lines and labels */}
        {yTickValues.map((v, i) => (
          <g key={i}>
            <line
              x1={pad.left}
              x2={dims.w - pad.right}
              y1={yScale(v)}
              y2={yScale(v)}
              className="chart-grid-line"
            />
            <text
              x={pad.left - 6}
              y={yScale(v) + 4}
              textAnchor="end"
              className="chart-axis-label"
            >
              {formatValue(v)}
            </text>
          </g>
        ))}

        {/* X-axis labels */}
        {xTickIndices.map((idx) => (
          <text
            key={idx}
            x={xScale(idx)}
            y={dims.h - pad.bottom + 16}
            textAnchor="middle"
            className="chart-axis-label"
          >
            {formatBucket(data[idx].bucket, span)}
          </text>
        ))}

        {/* Axis baseline */}
        <line
          x1={pad.left}
          x2={dims.w - pad.right}
          y1={pad.top + plotH}
          y2={pad.top + plotH}
          stroke="var(--border)"
          strokeWidth={1}
        />

        {/* Series areas and lines */}
        {series.map((s, si) => {
          const color = COLORS[si % COLORS.length];
          const points = data.map((row, i) => ({
            x: xScale(i),
            y: yScale(Number(row[s]) || 0),
          }));

          if (points.length === 0) return null;

          const linePath = points
            .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
            .join(' ');

          const areaPath = [
            ...points.map((p, i) =>
              `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`
            ),
            `L ${points[points.length - 1].x.toFixed(1)} ${(pad.top + plotH).toFixed(1)}`,
            `L ${points[0].x.toFixed(1)} ${(pad.top + plotH).toFixed(1)}`,
            'Z',
          ].join(' ');

          return (
            <g key={s}>
              <path d={areaPath} fill={color} fillOpacity={0.12} stroke="none" />
              <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
              {/* Only render dots for small datasets to avoid clutter */}
              {data.length <= 60 && points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={2.5} fill={color} />
              ))}
            </g>
          );
        })}

        {/* Crosshair */}
        {crosshairX !== null && crosshairIdx !== null && (
          <>
            <line
              x1={crosshairX}
              x2={crosshairX}
              y1={pad.top}
              y2={pad.top + plotH}
              className="chart-crosshair"
            />
            {series.map((s, si) => {
              const v = Number(data[crosshairIdx][s]) || 0;
              return (
                <circle
                  key={s}
                  cx={crosshairX}
                  cy={yScale(v)}
                  r={5}
                  fill={COLORS[si % COLORS.length]}
                  stroke="var(--bg-surface)"
                  strokeWidth={2}
                />
              );
            })}
          </>
        )}
      </svg>

      {/* Hover tooltip */}
      {crosshairX !== null && crosshairIdx !== null && (
        <div
          className="chart-tooltip"
          style={{
            left: Math.min(crosshairX + 14, dims.w - 160),
            top: 24,
          }}
        >
          <div style={{ marginBottom: 5, color: 'var(--text-muted)', fontSize: 11 }}>
            {formatBucket(data[crosshairIdx].bucket, span)}
          </div>
          {series.map((s, si) => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <span style={{ color: COLORS[si % COLORS.length] }}>●</span>
              <span style={{ color: 'var(--text-secondary)' }}>{s}:</span>
              <strong>{(Number(data[crosshairIdx][s]) || 0).toLocaleString()}</strong>
            </div>
          ))}
        </div>
      )}

      {/* Legend (only when multiple series) */}
      {series.length > 1 && (
        <div className="chart-legend">
          {series.map((s, si) => (
            <span key={s} className="chart-legend__item">
              <span
                className="chart-legend__dot"
                style={{ background: COLORS[si % COLORS.length] }}
              />
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default TimeSeriesChart

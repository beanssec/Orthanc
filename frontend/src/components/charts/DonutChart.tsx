import React from 'react'
/**
 * DonutChart — SVG donut/pie chart using path-based arcs.
 * Max 8 segments, remainder grouped as "Other". Hover expands segment.
 */
import { useState } from 'react';

const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
  '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16',
];

export interface DonutChartProps {
  data: Array<{ label: string; value: number; color?: string }>;
  size?: number;
  onSegmentClick?: (label: string) => void;
}

interface Segment {
  label: string;
  value: number;
  color: string;
  startAngle: number;
  endAngle: number;
  percentage: number;
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  segment: Segment | null;
}

function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: cx + r * Math.cos(rad),
    y: cy + r * Math.sin(rad),
  };
}

function describeArc(
  cx: number,
  cy: number,
  outerR: number,
  innerR: number,
  startAngle: number,
  endAngle: number
): string {
  // Clamp to just under 360 to avoid degenerate full-circle arc
  const sweep = Math.min(endAngle - startAngle, 359.999);
  const end = startAngle + sweep;
  const largeArc = sweep > 180 ? 1 : 0;

  const o1 = polarToCartesian(cx, cy, outerR, startAngle);
  const o2 = polarToCartesian(cx, cy, outerR, end);
  const i1 = polarToCartesian(cx, cy, innerR, startAngle);
  const i2 = polarToCartesian(cx, cy, innerR, end);

  return [
    `M ${o1.x.toFixed(2)} ${o1.y.toFixed(2)}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${o2.x.toFixed(2)} ${o2.y.toFixed(2)}`,
    `L ${i2.x.toFixed(2)} ${i2.y.toFixed(2)}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${i1.x.toFixed(2)} ${i1.y.toFixed(2)}`,
    'Z',
  ].join(' ');
}

function buildSegments(
  data: Array<{ label: string; value: number; color?: string }>
): Segment[] {
  // Sort descending, keep top 7, group rest
  const sorted = [...data].sort((a, b) => b.value - a.value);
  let items = sorted.slice(0, 7);
  const rest = sorted.slice(7);

  if (rest.length > 0) {
    const otherValue = rest.reduce((s, d) => s + d.value, 0);
    items = [...items, { label: 'Other', value: otherValue }];
  }

  const total = items.reduce((s, d) => s + d.value, 0) || 1;
  let angle = 0;

  return items.map((d, i) => {
    const pct = d.value / total;
    const sweep = pct * 360;
    const seg: Segment = {
      label: d.label,
      value: d.value,
      color: d.color ?? COLORS[i % COLORS.length],
      startAngle: angle,
      endAngle: angle + sweep,
      percentage: pct * 100,
    };
    angle += sweep;
    return seg;
  });
}

export function DonutChart({ data, size = 200, onSegmentClick }: DonutChartProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    segment: null,
  });
  const svgRef = { current: null as SVGSVGElement | null };

  if (!data.length) {
    return <div className="chart-container"><div className="chart-empty">No data</div></div>;
  }

  const segments = buildSegments(data);
  const total = data.reduce((s, d) => s + d.value, 0);

  const cx = size / 2;
  const cy = size / 2;
  const outerR = size / 2 - 10;
  const innerR = outerR * 0.6;
  const hoveredOuterR = outerR + 8;

  const handleMouseEnter = (
    e: React.MouseEvent<SVGPathElement>,
    idx: number,
    seg: Segment
  ) => {
    const rect = (e.currentTarget.closest('svg') as SVGSVGElement)
      ?.getBoundingClientRect();
    setHoveredIdx(idx);
    setTooltip({
      visible: true,
      x: e.clientX - (rect?.left ?? 0),
      y: e.clientY - (rect?.top ?? 0),
      segment: seg,
    });
  };

  const handleMouseMove = (e: React.MouseEvent<SVGPathElement>) => {
    const rect = (e.currentTarget.closest('svg') as SVGSVGElement)
      ?.getBoundingClientRect();
    setTooltip((t) => ({
      ...t,
      x: e.clientX - (rect?.left ?? 0),
      y: e.clientY - (rect?.top ?? 0),
    }));
  };

  const handleMouseLeave = () => {
    setHoveredIdx(null);
    setTooltip((t) => ({ ...t, visible: false }));
  };

  return (
    <div className="chart-container donut-chart">
      <div className="donut-svg-wrap" style={{ position: 'relative', display: 'inline-block' }}>
        <svg
          ref={(el) => { svgRef.current = el; }}
          width={size + 20}
          height={size + 20}
          style={{ overflow: 'visible' }}
        >
          {segments.map((seg, i) => {
            const isHovered = hoveredIdx === i;
            const r = isHovered ? hoveredOuterR : outerR;
            const d = describeArc(cx + 10, cy + 10, r, innerR, seg.startAngle, seg.endAngle);
            return (
              <path
                key={seg.label}
                d={d}
                fill={seg.color}
                fillOpacity={isHovered ? 1 : 0.85}
                className="donut-segment"
                onMouseEnter={(e) => handleMouseEnter(e, i, seg)}
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseLeave}
                onClick={() => onSegmentClick?.(seg.label)}
                style={{ filter: isHovered ? `drop-shadow(0 0 6px ${seg.color}66)` : undefined }}
              />
            );
          })}
        </svg>

        {/* Center text */}
        <div className="donut-center-text" style={{ top: (size + 20) / 2, left: (size + 20) / 2 }}>
          <span className="donut-center-value">
            {total >= 1_000_000
              ? `${(total / 1_000_000).toFixed(1)}M`
              : total >= 1_000
              ? `${(total / 1_000).toFixed(1)}k`
              : total.toLocaleString()}
          </span>
          <span className="donut-center-label">total</span>
        </div>

        {/* Tooltip */}
        {tooltip.visible && tooltip.segment && (
          <div
            className="chart-tooltip"
            style={{ left: tooltip.x + 12, top: tooltip.y - 10 }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{tooltip.segment.label}</div>
            <div>{tooltip.segment.value.toLocaleString()}</div>
            <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
              {tooltip.segment.percentage.toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="chart-legend" style={{ justifyContent: 'center', flexWrap: 'wrap' }}>
        {segments.map((seg) => (
          <span
            key={seg.label}
            className="chart-legend__item"
            style={{ cursor: onSegmentClick ? 'pointer' : undefined }}
            onClick={() => onSegmentClick?.(seg.label)}
          >
            <span className="chart-legend__dot" style={{ background: seg.color }} />
            {seg.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export default DonutChart

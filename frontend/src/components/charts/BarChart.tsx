import React from 'react'
/**
 * BarChart — Horizontal bar chart, raw SVG-free HTML approach.
 * Uses CSS transitions for animated bar widths. Max 20 bars, scrollable.
 */
import { useEffect, useRef, useState } from 'react';

const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ef4444',
  '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16',
];

export interface BarChartProps {
  data: Array<{ label: string; value: number; color?: string }>;
  width?: number;
  height?: number;
  onBarClick?: (label: string) => void;
}

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  label: string;
  value: number;
}

export function BarChart({ data, onBarClick }: BarChartProps) {
  const [mounted, setMounted] = useState(false);
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    label: '',
    value: 0,
  });
  const containerRef = useRef<HTMLDivElement>(null);

  // Trigger CSS transitions after first paint
  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const visible = data.slice(0, 20);
  const max = Math.max(...visible.map((d) => d.value), 1);

  const handleMouseEnter = (e: React.MouseEvent, label: string, value: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({
      visible: true,
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
      label,
      value,
    });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!tooltip.visible) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip((t) => ({ ...t, x: e.clientX - rect.left, y: e.clientY - rect.top }));
  };

  const handleMouseLeave = () => {
    setTooltip((t) => ({ ...t, visible: false }));
  };

  if (!data.length) {
    return <div className="chart-container"><div className="chart-empty">No data</div></div>;
  }

  return (
    <div className="chart-container bar-chart" ref={containerRef}>
      {visible.map((d, i) => {
        const pct = mounted ? (d.value / max) * 100 : 0;
        const color = d.color ?? COLORS[i % COLORS.length];

        return (
          <div
            key={d.label}
            className="bar-row"
            onClick={() => onBarClick?.(d.label)}
            onMouseEnter={(e) => handleMouseEnter(e, d.label, d.value)}
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
          >
            <div className="bar-label" title={d.label}>{d.label}</div>
            <div className="bar-track">
              <div
                className="bar-fill bar-chart__bar"
                style={{ width: `${pct}%`, background: color }}
              />
            </div>
            <div className="bar-value">{d.value.toLocaleString()}</div>
          </div>
        );
      })}

      {data.length > 20 && (
        <div className="bar-overflow-note">
          Showing 20 of {data.length.toLocaleString()} results
        </div>
      )}

      {tooltip.visible && (
        <div
          className="chart-tooltip"
          style={{ left: tooltip.x + 14, top: tooltip.y - 10 }}
        >
          <strong>{tooltip.label}</strong>: {tooltip.value.toLocaleString()}
        </div>
      )}
    </div>
  );
}

export default BarChart

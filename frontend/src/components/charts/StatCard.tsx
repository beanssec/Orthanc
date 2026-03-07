import React from 'react'
/**
 * StatCard — Big single-number display for scalar query results.
 */

export interface StatCardProps {
  value: number | string;
  label: string;
  trend?: number; // percentage change (positive = up, negative = down)
}

function formatValue(v: number | string): string {
  if (typeof v === 'string') return v;
  if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(2)}B`;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 10_000) return `${(v / 1_000).toFixed(1)}k`;
  return v.toLocaleString();
}

export function StatCard({ value, label, trend }: StatCardProps) {
  const hasTrend = trend !== undefined && trend !== null;
  const isUp = hasTrend && trend! >= 0;

  return (
    <div className="chart-container stat-card">
      <div className="stat-card__value">{formatValue(value)}</div>
      <div className="stat-card__label">{label}</div>
      {hasTrend && (
        <div className={`stat-card__trend stat-card__trend--${isUp ? 'up' : 'down'}`}>
          {isUp ? '▲' : '▼'} {Math.abs(trend!).toFixed(1)}%
        </div>
      )}
    </div>
  );
}

export default StatCard

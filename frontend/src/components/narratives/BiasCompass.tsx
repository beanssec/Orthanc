import { useEffect, useRef, useState } from 'react';
import api from '../../services/api';
import { BiasPoint } from './types';

interface TooltipState {
  x: number;
  y: number;
  point: BiasPoint;
}

export function BiasCompass() {
  const [points, setPoints] = useState<BiasPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 400, height: 240 });

  // Fetch bias data
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .get('/narratives/bias/compass')
      .then((res) => {
        if (!cancelled) {
          const data = res.data;
          setPoints(data?.points ?? []);
        }
      })
      .catch(() => {
        if (!cancelled) setPoints([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  // ResizeObserver for responsive sizing
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        const w = entry.contentRect.width;
        setDims({ width: w, height: Math.max(180, Math.min(280, w * 0.55)) });
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const padding = { top: 24, right: 24, bottom: 32, left: 48 };
  const plotW = dims.width - padding.left - padding.right;
  const plotH = dims.height - padding.top - padding.bottom;

  // Map data coords to SVG coords
  const toSvgX = (x: number) => padding.left + ((x + 1) / 2) * plotW;
  const toSvgY = (y: number) => padding.top + (1 - y) * plotH;

  const handleMouseEnter = (e: React.MouseEvent, pt: BiasPoint) => {
    setTooltip({ x: e.clientX, y: e.clientY, point: pt });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (tooltip) {
      setTooltip((prev) => prev ? { ...prev, x: e.clientX, y: e.clientY } : null);
    }
  };

  const handleMouseLeave = () => setTooltip(null);

  if (loading) {
    return (
      <div className="bias-compass-empty">
        Loading bias data…
      </div>
    );
  }

  if (points.length === 0) {
    return (
      <div className="bias-compass-empty">
        Bias profiles will be computed after narratives accumulate stance data.
      </div>
    );
  }

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <svg
        className="bias-compass-svg"
        width={dims.width}
        height={dims.height}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {/* Grid lines */}
        {/* Vertical grid */}
        {[-0.5, 0, 0.5].map((gx) => (
          <line
            key={`vg-${gx}`}
            className={gx === 0 ? 'bias-compass-axis' : 'bias-compass-grid'}
            x1={toSvgX(gx)}
            y1={padding.top}
            x2={toSvgX(gx)}
            y2={padding.top + plotH}
          />
        ))}
        {/* Horizontal grid */}
        {[0.25, 0.5, 0.75].map((gy) => (
          <line
            key={`hg-${gy}`}
            className={gy === 0.5 ? 'bias-compass-axis' : 'bias-compass-grid'}
            x1={padding.left}
            y1={toSvgY(gy)}
            x2={padding.left + plotW}
            y2={toSvgY(gy)}
          />
        ))}

        {/* Axes */}
        {/* X axis (y=0 bottom) */}
        <line
          className="bias-compass-axis"
          x1={padding.left}
          y1={padding.top + plotH}
          x2={padding.left + plotW}
          y2={padding.top + plotH}
        />
        {/* Y axis (x=-1 left) */}
        <line
          className="bias-compass-axis"
          x1={padding.left}
          y1={padding.top}
          x2={padding.left}
          y2={padding.top + plotH}
        />

        {/* X axis labels */}
        <text
          className="bias-compass-label"
          x={padding.left}
          y={dims.height - 4}
          textAnchor="middle"
        >
          Western
        </text>
        <text
          className="bias-compass-label"
          x={padding.left + plotW / 2}
          y={dims.height - 4}
          textAnchor="middle"
        >
          ← Bias →
        </text>
        <text
          className="bias-compass-label"
          x={padding.left + plotW}
          y={dims.height - 4}
          textAnchor="middle"
        >
          Eastern
        </text>

        {/* Y axis labels */}
        <text
          className="bias-compass-label"
          x={padding.left - 8}
          y={padding.top + plotH}
          textAnchor="end"
          dominantBaseline="middle"
        >
          Low
        </text>
        <text
          className="bias-compass-label"
          x={padding.left - 8}
          y={padding.top + plotH / 2}
          textAnchor="end"
          dominantBaseline="middle"
        >
          Rel.
        </text>
        <text
          className="bias-compass-label"
          x={padding.left - 8}
          y={padding.top}
          textAnchor="end"
          dominantBaseline="middle"
        >
          High
        </text>

        {/* Data points */}
        {points.map((pt) => (
          <circle
            key={pt.source_id}
            className="bias-compass-dot"
            cx={toSvgX(pt.x)}
            cy={toSvgY(pt.y)}
            r={6}
            fill={pt.color}
            fillOpacity={0.85}
            stroke="rgba(255,255,255,0.15)"
            strokeWidth={1}
            onMouseEnter={(e) => handleMouseEnter(e, pt)}
          />
        ))}
      </svg>

      {tooltip && (
        <div
          className="bias-compass-tooltip"
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 8,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>{tooltip.point.source_name}</div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
            Group: {tooltip.point.group}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
            Type: {tooltip.point.source_type}
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', fontFamily: 'var(--font-mono)' }}>
            Bias: {tooltip.point.x.toFixed(2)} &nbsp; Reliability: {tooltip.point.y.toFixed(2)}
          </div>
        </div>
      )}
    </div>
  );
}

export default BiasCompass;

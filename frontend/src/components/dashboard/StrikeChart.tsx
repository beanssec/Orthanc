import { useEffect, useRef, useState } from 'react';
import api from '../../services/api';

interface StrikeDataPoint {
  date: string;
  counts: Record<string, number>;
}

interface StrikeChartData {
  days: number;
  data: StrikeDataPoint[];
}

const ACTOR_COLORS: Record<string, string> = {
  us:        '#3b82f6', // blue
  israel:    '#06b6d4', // cyan
  iran:      '#ef4444', // red
  hezbollah: '#f97316', // orange
};

const ACTOR_LABELS: Record<string, string> = {
  us:        'US / CENTCOM',
  israel:    'Israel / IDF',
  iran:      'Iran / IRGC',
  hezbollah: 'Hezbollah',
};

function formatDateShort(iso: string): string {
  try {
    const d = new Date(iso + 'T12:00:00Z');
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  } catch {
    return iso.slice(5); // MM-DD
  }
}

export function StrikeChart() {
  const [data, setData] = useState<StrikeDataPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [backfilling, setBackfilling] = useState(false);
  const [days, setDays] = useState(14);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    point: StrikeDataPoint;
  } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 560, h: 200 });

  useEffect(() => {
    const measure = () => {
      if (wrapRef.current) {
        const rect = wrapRef.current.getBoundingClientRect();
        setDims({ w: Math.max(200, rect.width), h: Math.max(120, rect.height) });
      }
    };
    measure();
    const obs = new ResizeObserver(measure);
    if (wrapRef.current) obs.observe(wrapRef.current);
    return () => obs.disconnect();
  }, []);

  const fetchData = async () => {
    try {
      const res = await api.get<StrikeChartData>(`/dashboard/strikes?days=${days}`);
      setData(res.data.data ?? []);
    } catch {
      // endpoint may return empty if no data yet
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [days]);

  const handleBackfill = async () => {
    setBackfilling(true);
    try {
      await api.post(`/dashboard/strikes/backfill?days=${days}`);
      await fetchData();
    } catch {
      // ignore
    } finally {
      setBackfilling(false);
    }
  };

  // Determine which actors have any data
  const actors = Object.keys(ACTOR_COLORS).filter((actor) =>
    data.some((d) => (d.counts[actor] ?? 0) > 0)
  );

  const allActors = Object.keys(ACTOR_COLORS);

  // Chart geometry
  const W = dims.w;
  const H = dims.h;
  const padL = 32;
  const padR = 12;
  const padT = 10;
  const padB = 28;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const maxVal = Math.max(
    1,
    ...data.flatMap((d) => allActors.map((a) => d.counts[a] ?? 0))
  );

  const n = data.length;
  const xStep = n > 1 ? chartW / (n - 1) : chartW;

  function xPos(i: number) {
    return padL + (n > 1 ? i * xStep : chartW / 2);
  }

  function yPos(val: number) {
    return padT + chartH - (val / maxVal) * chartH;
  }

  function buildPath(actor: string): string {
    const pts = data
      .map((d, i) => {
        const val = d.counts[actor] ?? 0;
        return `${xPos(i)},${yPos(val)}`;
      })
      .join(' L ');
    return pts ? `M ${pts}` : '';
  }

  // Y-axis ticks
  const yTicks = [0, Math.round(maxVal / 2), maxVal];

  if (loading) {
    return (
      <div className="dash-card dash-card--full">
        <div className="dash-card__header">
          <span className="dash-card__title">⚔️ Daily Strike Activity</span>
        </div>
        <div className="dash-card__body" style={{ padding: '1rem', color: 'var(--text-muted)' }}>
          Loading…
        </div>
      </div>
    );
  }

  return (
    <div className="dash-card dash-card--full" style={{ minHeight: '350px', border: '1px solid var(--border)', overflow: 'visible' }}>
      <div className="dash-card__header">
        <span className="dash-card__title">⚔️ Daily Strike Activity</span>
        <span className="dash-card__meta">US · Israel · Iran · Hezbollah — keyword extracted from posts</span>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', marginLeft: 'auto' }}>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            style={{
              background: 'var(--surface-2)',
              color: 'var(--text)',
              border: '1px solid var(--border)',
              borderRadius: '4px',
              padding: '2px 6px',
              fontSize: '12px',
            }}
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
          </select>
          <button
            className="btn btn-ghost btn-sm"
            onClick={handleBackfill}
            disabled={backfilling}
            title="Re-extract strike counts from existing posts"
          >
            {backfilling ? '⟳ Running…' : '↺ Backfill'}
          </button>
        </div>
      </div>
      <div className="dash-card__body dash-card__body--velocity">
        {data.length === 0 ? (
          <div className="dash-empty">
            No strike data yet — click ↺ Backfill to extract from existing posts
          </div>
        ) : (
          <div ref={wrapRef} className="velocity-chart-wrap">
            <svg
              ref={svgRef}
              width={W}
              height={H}
              className="velocity-chart__svg"
              onMouseLeave={() => setTooltip(null)}
            >
              {/* Y-axis gridlines + labels */}
              {yTicks.map((tick) => {
                const y = yPos(tick);
                return (
                  <g key={tick}>
                    <line
                      x1={padL} y1={y} x2={W - padR} y2={y}
                      stroke="var(--border)" strokeWidth={0.5}
                    />
                    <text
                      x={padL - 4} y={y + 3}
                      textAnchor="end"
                      fontSize={8}
                      fill="var(--text-muted)"
                    >
                      {tick}
                    </text>
                  </g>
                );
              })}

              {/* X-axis labels */}
              {data.map((d, i) => {
                const showLabel =
                  i === 0 || i === data.length - 1 || i % Math.ceil(data.length / 6) === 0;
                return showLabel ? (
                  <text
                    key={d.date}
                    x={xPos(i)}
                    y={H - 4}
                    textAnchor="middle"
                    fontSize={7.5}
                    fill="var(--text-muted)"
                  >
                    {formatDateShort(d.date)}
                  </text>
                ) : null;
              })}

              {/* Lines per actor */}
              {allActors.map((actor) => {
                const path = buildPath(actor);
                if (!path) return null;
                return (
                  <path
                    key={actor}
                    d={path}
                    fill="none"
                    stroke={ACTOR_COLORS[actor]}
                    strokeWidth={2}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    opacity={actors.includes(actor) ? 0.9 : 0.2}
                  />
                );
              })}

              {/* Data point dots + hover areas */}
              {data.map((d, i) => (
                <g key={d.date}>
                  {allActors.map((actor) => {
                    const val = d.counts[actor] ?? 0;
                    if (val === 0) return null;
                    return (
                      <circle
                        key={actor}
                        cx={xPos(i)}
                        cy={yPos(val)}
                        r={3}
                        fill={ACTOR_COLORS[actor]}
                        opacity={0.9}
                      />
                    );
                  })}
                  {/* Invisible wide hover strip */}
                  <rect
                    x={xPos(i) - (xStep / 2 || 20)}
                    y={padT}
                    width={xStep || 40}
                    height={chartH}
                    fill="transparent"
                    onMouseEnter={(e) => {
                      const svgRect = svgRef.current?.getBoundingClientRect();
                      if (!svgRect) return;
                      setTooltip({
                        x: e.clientX - svgRect.left,
                        y: e.clientY - svgRect.top,
                        point: d,
                      });
                    }}
                  />
                </g>
              ))}
            </svg>

            {/* Tooltip */}
            {tooltip && (
              <div
                className="velocity-tooltip"
                style={{
                  left: tooltip.x + 8,
                  top: tooltip.y - 10,
                  minWidth: '140px',
                }}
              >
                <div className="velocity-tooltip__hour">
                  {formatDateShort(tooltip.point.date)}
                </div>
                {allActors.map((actor) => {
                  const count = tooltip.point.counts[actor] ?? 0;
                  return (
                    <div key={actor} className="velocity-tooltip__row">
                      <span
                        className="velocity-tooltip__dot"
                        style={{ background: ACTOR_COLORS[actor] }}
                      />
                      <span style={{ opacity: count > 0 ? 1 : 0.4 }}>
                        {ACTOR_LABELS[actor]}: {count}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Legend */}
            <div className="velocity-legend">
              {allActors.map((actor) => (
                <span
                  key={actor}
                  className="velocity-legend__item"
                  style={{ opacity: actors.includes(actor) ? 1 : 0.4 }}
                >
                  <span
                    className="velocity-legend__dot"
                    style={{ background: ACTOR_COLORS[actor] }}
                  />
                  {ACTOR_LABELS[actor]}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

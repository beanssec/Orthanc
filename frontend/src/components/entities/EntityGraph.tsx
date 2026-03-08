import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';

// ── Types ──────────────────────────────────────────────────────────────────

interface GraphNode {
  id: string;
  name: string;
  type: string;
  mentions: number;
  size: number;
  // Simulation state
  x: number;
  y: number;
  vx: number;
  vy: number;
}

interface GraphEdge {
  source: string;
  target: string;
  weight: number;
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ── Constants ──────────────────────────────────────────────────────────────

const NODE_COLORS: Record<string, string> = {
  PERSON: '#3b82f6',
  PER: '#3b82f6',
  ORG: '#10b981',
  GPE: '#f59e0b',
  EVENT: '#ef4444',
  NORP: '#8b5cf6',
};

const ENTITY_TYPES = ['PERSON', 'ORG', 'GPE', 'EVENT', 'NORP'];

function nodeColor(type: string): string {
  return NODE_COLORS[type] ?? '#6b7280';
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s;
}

// ── Force simulation ───────────────────────────────────────────────────────

const REPULSION = 3000;
const SPRING_LENGTH = 120;
const SPRING_STRENGTH = 0.04;
const GRAVITY = 0.02;
const DAMPING = 0.82;
const ITERATIONS = 250;

function runSimulation(nodes: GraphNode[], edges: GraphEdge[], width: number, height: number): GraphNode[] {
  const cx = width / 2;
  const cy = height / 2;

  // Build adjacency map for quick lookup
  const adj: Record<string, Array<{ targetId: string; weight: number }>> = {};
  for (const n of nodes) adj[n.id] = [];
  for (const e of edges) {
    adj[e.source]?.push({ targetId: e.target, weight: e.weight });
    adj[e.target]?.push({ targetId: e.source, weight: e.weight });
  }

  // Initialize positions in a circle if not set
  const positioned = nodes.map((n, i) => {
    if (n.x === 0 && n.y === 0) {
      const angle = (2 * Math.PI * i) / nodes.length;
      return {
        ...n,
        x: cx + Math.cos(angle) * 200,
        y: cy + Math.sin(angle) * 200,
        vx: 0,
        vy: 0,
      };
    }
    return { ...n };
  });

  const byId: Record<string, GraphNode> = {};
  for (const n of positioned) byId[n.id] = n;

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const alpha = 1 - iter / ITERATIONS;

    // Repulsion — all pairs
    const ids = Object.keys(byId);
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = byId[ids[i]];
        const b = byId[ids[j]];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 0.5);
        const force = (REPULSION / (dist * dist)) * alpha;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
    }

    // Attraction — spring along edges
    for (const e of edges) {
      const a = byId[e.source];
      const b = byId[e.target];
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 0.5);
      const targetLen = SPRING_LENGTH / Math.max(Math.log2(e.weight + 1), 1);
      const stretch = dist - targetLen;
      const force = stretch * SPRING_STRENGTH * alpha;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }

    // Center gravity
    for (const n of Object.values(byId)) {
      n.vx += (cx - n.x) * GRAVITY * alpha;
      n.vy += (cy - n.y) * GRAVITY * alpha;
    }

    // Integrate + dampen
    for (const n of Object.values(byId)) {
      n.vx *= DAMPING;
      n.vy *= DAMPING;
      n.x += n.vx;
      n.y += n.vy;
    }
  }

  return Object.values(byId);
}

// ── Component ──────────────────────────────────────────────────────────────

export function EntityGraph() {
  const navigate = useNavigate();
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const [rawData, setRawData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Controls
  const [minWeight, setMinWeight] = useState(3);
  const [activeTypes, setActiveTypes] = useState<Set<string>>(new Set(ENTITY_TYPES));
  const [searchQuery, setSearchQuery] = useState('');

  // Interaction
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: GraphNode } | null>(null);

  // Pan + zoom via viewBox
  const [viewBox, setViewBox] = useState({ x: 0, y: 0, w: 1200, h: 800 });
  const panStart = useRef<{ mx: number; my: number; vx: number; vy: number } | null>(null);

  // ── Fetch ────────────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    api.get<{ nodes: GraphNode[]; edges: GraphEdge[] }>(`/graph/entities?min_weight=${minWeight}&limit=200`)
      .then(res => {
        if (cancelled) return;
        const data = res.data;
        // Initialize simulation fields
        const initialNodes = data.nodes.map(n => ({ ...n, x: 0, y: 0, vx: 0, vy: 0 }));
        setRawData({ nodes: initialNodes, edges: data.edges });
      })
      .catch(err => {
        if (!cancelled) setError(err?.response?.data?.detail ?? 'Failed to load graph');
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [minWeight]);

  // ── Run simulation when data changes ────────────────────────────────────

  useEffect(() => {
    if (!rawData) return;
    const container = containerRef.current;
    const w = container?.clientWidth ?? 1200;
    const h = container?.clientHeight ?? 800;
    setViewBox({ x: 0, y: 0, w, h });

    const simNodes = runSimulation([...rawData.nodes], rawData.edges, w, h);
    setNodes(simNodes);
    setEdges(rawData.edges);
  }, [rawData]);

  // ── Filtering ────────────────────────────────────────────────────────────

  const visibleNodes = nodes.filter(n => activeTypes.has(n.type));
  const visibleNodeIds = new Set(visibleNodes.map(n => n.id));
  const visibleEdges = edges.filter(e => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target));

  const searchMatch = searchQuery.trim().toLowerCase();
  const highlightedIds: Set<string> = searchMatch
    ? new Set(visibleNodes.filter(n => n.name.toLowerCase().includes(searchMatch)).map(n => n.id))
    : new Set();

  const hoveredConnected: Set<string> = new Set();
  if (hoveredId) {
    visibleEdges.forEach(e => {
      if (e.source === hoveredId) hoveredConnected.add(e.target);
      if (e.target === hoveredId) hoveredConnected.add(e.source);
    });
  }

  // ── Pan ──────────────────────────────────────────────────────────────────

  const handleMouseDownSvg = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if ((e.target as SVGElement).closest('.entity-graph__node')) return;
    panStart.current = { mx: e.clientX, my: e.clientY, vx: viewBox.x, vy: viewBox.y };
  }, [viewBox]);

  const handleMouseMoveSvg = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!panStart.current) return;
    const svg = svgRef.current;
    if (!svg) return;
    const scale = viewBox.w / svg.clientWidth;
    const dx = (e.clientX - panStart.current.mx) * scale;
    const dy = (e.clientY - panStart.current.my) * scale;
    setViewBox(v => ({ ...v, x: panStart.current!.vx - dx, y: panStart.current!.vy - dy }));
  }, [viewBox.w]);

  const handleMouseUpSvg = useCallback(() => { panStart.current = null; }, []);

  // ── Zoom ─────────────────────────────────────────────────────────────────

  const handleWheel = useCallback((e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 1.1 : 0.9;
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    setViewBox(v => {
      const scale = v.w / svg.clientWidth;
      const wx = v.x + mouseX * scale;
      const wy = v.y + mouseY * scale;
      const newW = v.w * factor;
      const newH = v.h * factor;
      return {
        x: wx - (mouseX / svg.clientWidth) * newW,
        y: wy - (mouseY / svg.clientHeight) * newH,
        w: newW,
        h: newH,
      };
    });
  }, []);

  const resetZoom = () => {
    const container = containerRef.current;
    setViewBox({ x: 0, y: 0, w: container?.clientWidth ?? 1200, h: container?.clientHeight ?? 800 });
  };

  // ── Type filter toggle ────────────────────────────────────────────────────

  const toggleType = (t: string) => {
    setActiveTypes(prev => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  // ── Max edge weight for opacity scale ────────────────────────────────────
  const maxWeight = Math.max(...visibleEdges.map(e => e.weight), 1);

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="entity-graph entity-graph--loading">
        <div className="entity-graph__spinner">Computing entity relationships…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="entity-graph entity-graph--error">
        <div className="entity-graph__error-msg">{error}</div>
      </div>
    );
  }

  if (visibleNodes.length === 0) {
    return (
      <div className="entity-graph entity-graph--empty">
        <div className="entity-graph__empty-msg">
          No entity relationships found with min weight {minWeight}.
          <br />Try lowering the minimum weight or ingesting more posts.
        </div>
      </div>
    );
  }

  const vbStr = `${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`;

  return (
    <div className="entity-graph" ref={containerRef}>
      {/* Controls */}
      <div className="entity-graph__controls">
        <div className="entity-graph__control-group">
          <label className="entity-graph__control-label">
            Min Weight: <strong>{minWeight}</strong>
          </label>
          <input
            type="range"
            className="entity-graph__slider"
            min={1}
            max={20}
            value={minWeight}
            onChange={e => setMinWeight(Number(e.target.value))}
          />
        </div>

        <div className="entity-graph__control-group entity-graph__type-filters">
          {ENTITY_TYPES.map(t => (
            <label key={t} className="entity-graph__type-chip" style={{ '--chip-color': nodeColor(t) } as React.CSSProperties}>
              <input
                type="checkbox"
                checked={activeTypes.has(t)}
                onChange={() => toggleType(t)}
              />
              <span className="entity-graph__type-dot" />
              {t}
            </label>
          ))}
        </div>

        <div className="entity-graph__control-group">
          <input
            type="text"
            className="entity-graph__search"
            placeholder="Search entities…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
        </div>

        <div className="entity-graph__control-group">
          <button className="entity-graph__reset-btn" onClick={resetZoom}>
            Reset Zoom
          </button>
        </div>

        <div className="entity-graph__stats">
          {visibleNodes.length} nodes · {visibleEdges.length} edges
        </div>
      </div>

      {/* SVG Canvas */}
      <svg
        ref={svgRef}
        className="entity-graph__svg"
        viewBox={vbStr}
        onMouseDown={handleMouseDownSvg}
        onMouseMove={handleMouseMoveSvg}
        onMouseUp={handleMouseUpSvg}
        onMouseLeave={handleMouseUpSvg}
        onWheel={handleWheel}
      >
        {/* Edges */}
        <g className="entity-graph__edges">
          {visibleEdges.map(e => {
            const src = visibleNodes.find(n => n.id === e.source);
            const tgt = visibleNodes.find(n => n.id === e.target);
            if (!src || !tgt) return null;

            const isConnectedToHover =
              hoveredId && (e.source === hoveredId || e.target === hoveredId);
            const opacity = hoveredId
              ? isConnectedToHover ? 0.9 : 0.05
              : Math.max(0.15, e.weight / maxWeight);
            const strokeWidth = Math.max(0.5, (e.weight / maxWeight) * 3);

            return (
              <line
                key={`${e.source}-${e.target}`}
                className="entity-graph__edge"
                x1={src.x}
                y1={src.y}
                x2={tgt.x}
                y2={tgt.y}
                strokeOpacity={opacity}
                strokeWidth={strokeWidth}
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g className="entity-graph__nodes">
          {visibleNodes.map(n => {
            const isHovered = n.id === hoveredId;
            const isConnected = hoveredConnected.has(n.id);
            const isHighlighted = highlightedIds.size > 0 && highlightedIds.has(n.id);
            const isDimmed = hoveredId
              ? !isHovered && !isConnected
              : highlightedIds.size > 0 && !isHighlighted;

            return (
              <g
                key={n.id}
                className={`entity-graph__node${isDimmed ? ' entity-graph__node--dimmed' : ''}`}
                transform={`translate(${n.x},${n.y})`}
                onMouseEnter={ev => {
                  setHoveredId(n.id);
                  const svg = svgRef.current;
                  if (!svg) return;
                  const rect = svg.getBoundingClientRect();
                  setTooltip({
                    x: ev.clientX - rect.left + 12,
                    y: ev.clientY - rect.top - 8,
                    node: n,
                  });
                }}
                onMouseLeave={() => {
                  setHoveredId(null);
                  setTooltip(null);
                }}
                onClick={() => navigate(`/entities/${n.id}`)}
              >
                <circle
                  r={n.size}
                  fill={nodeColor(n.type)}
                  stroke={isHovered || isHighlighted ? '#fff' : 'transparent'}
                  strokeWidth={isHovered || isHighlighted ? 2 : 0}
                  fillOpacity={isHovered ? 1 : 0.85}
                />
                <text
                  className="entity-graph__label"
                  x={n.size + 4}
                  y={4}
                  opacity={isDimmed ? 0.3 : 1}
                >
                  {truncate(n.name, 15)}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="entity-graph__tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <div className="entity-graph__tooltip-name">{tooltip.node.name}</div>
          <div className="entity-graph__tooltip-type" style={{ color: nodeColor(tooltip.node.type) }}>
            {tooltip.node.type}
          </div>
          <div className="entity-graph__tooltip-mentions">
            {tooltip.node.mentions} mention{tooltip.node.mentions !== 1 ? 's' : ''}
          </div>
        </div>
      )}
    </div>
  );
}

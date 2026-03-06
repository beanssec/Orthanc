import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';

// ── Types ─────────────────────────────────────────────────
interface GraphNode {
  id: string;
  name: string;
  type: string;
  mentions: number;
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

interface TooltipState {
  x: number;
  y: number;
  node: GraphNode;
}

interface PathStep {
  entity: { id: string; name: string; type: string };
  connecting_posts: number;
}

interface PathResult {
  source: { id: string; name: string; type: string };
  target: { id: string; name: string; type: string };
  path: PathStep[];
  depth: number;
  found: boolean;
}

interface PathState {
  nodeIds: Set<string>;
  edgePairs: Set<string>; // "sourceId|targetId"
}

// ── Constants ─────────────────────────────────────────────
const TYPE_COLORS: Record<string, string> = {
  GPE: '#10b981',
  PERSON: '#a855f7',
  ORG: '#3b82f6',
  NORP: '#6b7280',
  EVENT: '#f97316',
};

const ENTITY_TYPES = ['GPE', 'PERSON', 'ORG', 'NORP', 'EVENT'];
const TICKS_PER_FRAME = 8;
const MAX_TICKS = 300;

// ── Helpers ───────────────────────────────────────────────
function nodeRadius(mentions: number): number {
  return Math.max(6, Math.min(28, 6 + Math.log(Math.max(1, mentions)) * 5));
}

function initNodes(rawNodes: Omit<GraphNode, 'x' | 'y' | 'vx' | 'vy'>[], width: number, height: number): GraphNode[] {
  return rawNodes.map((n) => ({
    ...n,
    x: width / 2 + (Math.random() - 0.5) * width * 0.5,
    y: height / 2 + (Math.random() - 0.5) * height * 0.5,
    vx: 0,
    vy: 0,
  }));
}

function runTick(
  nodes: GraphNode[],
  edges: GraphEdge[],
  nodeMap: Map<string, GraphNode>,
  alpha: number,
  width: number,
  height: number
): void {
  // Repulsion (Coulomb) — stronger to spread nodes
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i];
      const b = nodes[j];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist2 = dx * dx + dy * dy || 0.01;
      const dist = Math.sqrt(dist2);
      // Strong base repulsion; scale with node sizes
      const repulsion = 6000 * alpha;
      const force = repulsion / dist2;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx -= fx;
      a.vy -= fy;
      b.vx += fx;
      b.vy += fy;
    }
  }

  // Attraction (spring with ideal distance)
  const idealDist = 120; // px — desired separation between connected nodes
  for (const edge of edges) {
    const src = nodeMap.get(edge.source);
    const tgt = nodeMap.get(edge.target);
    if (!src || !tgt) continue;
    const dx = tgt.x - src.x;
    const dy = tgt.y - src.y;
    const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
    // Spring: attract if farther than idealDist, repel if closer
    const displacement = dist - idealDist;
    const force = displacement * 0.006 * alpha * Math.sqrt(Math.min(edge.weight, 5));
    src.vx += (dx / dist) * force;
    src.vy += (dy / dist) * force;
    tgt.vx -= (dx / dist) * force;
    tgt.vy -= (dy / dist) * force;
  }

  // Center gravity + damping + integrate
  const cx = width / 2;
  const cy = height / 2;
  for (const n of nodes) {
    n.vx += (cx - n.x) * 0.0008 * alpha;
    n.vy += (cy - n.y) * 0.0008 * alpha;
    n.vx *= 0.88;
    n.vy *= 0.88;
    n.x += n.vx;
    n.y += n.vy;
    const r = nodeRadius(n.mentions);
    n.x = Math.max(r + 12, Math.min(width - r - 12, n.x));
    n.y = Math.max(r + 12, Math.min(height - r - 12, n.y));
  }
}

function drawFrame(
  ctx: CanvasRenderingContext2D,
  nodes: GraphNode[],
  edges: GraphEdge[],
  nodeMap: Map<string, GraphNode>,
  hoveredId: string | null,
  cssWidth: number,
  cssHeight: number,
  dpr: number,
  pathState: PathState | null
): void {
  const W = cssWidth * dpr;
  const H = cssHeight * dpr;
  ctx.clearRect(0, 0, W, H);
  ctx.save();
  ctx.scale(dpr, dpr);

  // Precompute sets for highlight
  const connectedEdgeSet = new Set<number>();
  const connectedNodeSet = new Set<string>();
  if (hoveredId) {
    edges.forEach((e, i) => {
      if (e.source === hoveredId || e.target === hoveredId) {
        connectedEdgeSet.add(i);
        connectedNodeSet.add(e.source === hoveredId ? e.target : e.source);
      }
    });
  }

  // Draw edges
  edges.forEach((edge, i) => {
    const src = nodeMap.get(edge.source);
    const tgt = nodeMap.get(edge.target);
    if (!src || !tgt) return;

    const isConnected = connectedEdgeSet.has(i);
    const edgePairKey1 = `${edge.source}|${edge.target}`;
    const edgePairKey2 = `${edge.target}|${edge.source}`;
    const isPathEdge = pathState ? (pathState.edgePairs.has(edgePairKey1) || pathState.edgePairs.has(edgePairKey2)) : false;

    let edgeAlpha: number;
    if (pathState) {
      edgeAlpha = isPathEdge ? 1.0 : 0.03;
    } else if (hoveredId) {
      edgeAlpha = isConnected ? 0.85 : 0.04;
    } else {
      edgeAlpha = 0.22;
    }
    const lw = Math.max(1, Math.min(4, edge.weight * 0.6));

    ctx.beginPath();
    ctx.moveTo(src.x, src.y);
    ctx.lineTo(tgt.x, tgt.y);
    ctx.strokeStyle = isPathEdge ? `rgba(245,158,11,${edgeAlpha})` : `rgba(156,163,175,${edgeAlpha})`;
    ctx.lineWidth = isPathEdge ? lw + 2 : isConnected ? lw + 1 : lw;
    ctx.stroke();
  });

  // Draw nodes
  for (const node of nodes) {
    const r = nodeRadius(node.mentions);
    const color = TYPE_COLORS[node.type] ?? '#6b7280';
    const isHovered = node.id === hoveredId;
    const isConnected = connectedNodeSet.has(node.id);
    const isPathNode = pathState ? pathState.nodeIds.has(node.id) : false;
    const dimmed = pathState
      ? !isPathNode
      : (!!hoveredId && !isHovered && !isConnected);

    // Path glow ring
    if (isPathNode) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 9, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(245,158,11,0.18)';
      ctx.fill();
    }

    // Hover glow ring
    if (isHovered && !pathState) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + 7, 0, Math.PI * 2);
      ctx.fillStyle = color + '28';
      ctx.fill();
    }

    // Fill
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    if (dimmed) {
      ctx.fillStyle = color + '18';
    } else if (isPathNode) {
      ctx.fillStyle = '#f59e0bdd';
    } else if (isHovered) {
      ctx.fillStyle = color + 'ff';
    } else {
      ctx.fillStyle = color + 'bb';
    }
    ctx.fill();

    // Stroke
    ctx.beginPath();
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
    ctx.strokeStyle = dimmed ? color + '18' : isPathNode ? '#f59e0b' : isHovered ? '#ffffff55' : color + '66';
    ctx.lineWidth = isPathNode ? 2.5 : isHovered ? 2 : 1;
    ctx.stroke();

    // Label
    const showLabel = !dimmed && (node.mentions >= 5 || isHovered || isConnected || isPathNode);
    if (showLabel) {
      const fontSize = Math.max(10, Math.min(14, 9 + Math.log(node.mentions + 1) * 1.5));
      ctx.font = `${(isHovered || isPathNode) ? '600' : '400'} ${fontSize}px Inter, system-ui, sans-serif`;
      ctx.fillStyle = isPathNode ? '#f59e0b' : isHovered ? '#ffffff' : 'rgba(249,250,251,0.82)';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const label = node.name.length > 22 ? node.name.slice(0, 20) + '…' : node.name;
      ctx.shadowColor = 'rgba(0,0,0,0.85)';
      ctx.shadowBlur = 5;
      ctx.fillText(label, node.x, node.y + r + 3);
      ctx.shadowBlur = 0;
    }
  }

  ctx.restore();
}

// ── Component ─────────────────────────────────────────────
export function EntityGraph() {
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Simulation state via refs (avoid re-renders during animation)
  const nodesRef = useRef<GraphNode[]>([]);
  const edgesRef = useRef<GraphEdge[]>([]);
  const nodeMapRef = useRef<Map<string, GraphNode>>(new Map());
  const ticksRef = useRef(0);
  const rafRef = useRef<number>(0);
  const hoveredIdRef = useRef<string | null>(null);
  const sizeRef = useRef({ width: 800, height: 600 });
  const pathStateRef = useRef<PathState | null>(null);

  // React state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);
  const [simDone, setSimDone] = useState(false);
  const [nodeList, setNodeList] = useState<{ id: string; name: string; type: string }[]>([]);

  // Controls
  const [hours, setHours] = useState(48);
  const [minMentions, setMinMentions] = useState(2);
  const [nodeLimit, setNodeLimit] = useState(50);
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set(ENTITY_TYPES));
  const [refreshKey, setRefreshKey] = useState(0);

  // Path finding
  const [pathSource, setPathSource] = useState<string>('');
  const [pathTarget, setPathTarget] = useState<string>('');
  const [pathResult, setPathResult] = useState<PathResult | null>(null);
  const [pathLoading, setPathLoading] = useState(false);

  // ── Animation loop ──────────────────────────────────────
  const startAnimation = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    cancelAnimationFrame(rafRef.current);
    ticksRef.current = 0;
    setSimDone(false);

    function loop() {
      const { width, height } = sizeRef.current;
      const nodes = nodesRef.current;
      const edges = edgesRef.current;
      const nodeMap = nodeMapRef.current;

      if (ticksRef.current < MAX_TICKS) {
        const remaining = MAX_TICKS - ticksRef.current;
        const batchSize = Math.min(TICKS_PER_FRAME, remaining);
        for (let t = 0; t < batchSize; t++) {
          const tick = ticksRef.current + t;
          const alpha = 1 - tick / MAX_TICKS;
          runTick(nodes, edges, nodeMap, alpha, width, height);
        }
        ticksRef.current += batchSize;
      } else {
        setSimDone(true);
      }

      drawFrame(ctx, nodes, edges, nodeMap, hoveredIdRef.current, width, height, window.devicePixelRatio || 1, pathStateRef.current);
      rafRef.current = requestAnimationFrame(loop);
    }

    rafRef.current = requestAnimationFrame(loop);
  }, []);

  // ── Fetch data ──────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    cancelAnimationFrame(rafRef.current);
    setLoading(true);
    setError(null);
    setTooltip(null);
    setSimDone(false);

    api
      .get('/entities/graph', {
        params: { hours, min_mentions: minMentions, limit: nodeLimit },
      })
      .then((res) => {
        if (cancelled) return;
        const raw = res.data as { nodes: Omit<GraphNode, 'x' | 'y' | 'vx' | 'vy'>[]; edges: GraphEdge[] };

        // Apply type filter
        const filteredNodes = raw.nodes.filter((n) => typeFilter.has(n.type));
        const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));
        const filteredEdges = raw.edges.filter(
          (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target)
        );

        const { width, height } = sizeRef.current;
        const nodes = initNodes(filteredNodes, width, height);
        const nodeMap = new Map(nodes.map((n) => [n.id, n]));

        nodesRef.current = nodes;
        edgesRef.current = filteredEdges;
        nodeMapRef.current = nodeMap;
        ticksRef.current = 0;
        hoveredIdRef.current = null;

        setNodeCount(nodes.length);
        setEdgeCount(filteredEdges.length);
        setNodeList(nodes.map(n => ({ id: n.id, name: n.name, type: n.type })));
        setLoading(false);

        startAnimation();
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load graph');
        setLoading(false);
      });

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours, minMentions, nodeLimit, typeFilter, refreshKey]);

  // ── Canvas resize ───────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const dpr = window.devicePixelRatio || 1;

    const resize = () => {
      const rect = container.getBoundingClientRect();
      const w = rect.width;
      const h = rect.height;
      sizeRef.current = { width: w, height: h };
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  // ── Mouse interaction ───────────────────────────────────
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    let found: GraphNode | null = null;
    for (const node of nodesRef.current) {
      const r = nodeRadius(node.mentions);
      const dx = node.x - mx;
      const dy = node.y - my;
      if (dx * dx + dy * dy <= (r + 4) * (r + 4)) {
        found = node;
        break;
      }
    }

    hoveredIdRef.current = found?.id ?? null;

    if (found) {
      canvas.style.cursor = 'pointer';
      setTooltip({ x: e.clientX, y: e.clientY, node: found });
    } else {
      canvas.style.cursor = 'default';
      setTooltip(null);
    }
  }, []);

  const handleMouseLeave = useCallback(() => {
    hoveredIdRef.current = null;
    setTooltip(null);
  }, []);

  const handleClick = useCallback(() => {
    const hovered = hoveredIdRef.current;
    if (hovered) {
      navigate(`/entities/${hovered}`);
    }
  }, [navigate]);

  // ── Path finding ────────────────────────────────────────
  const findPath = useCallback(async () => {
    if (!pathSource || !pathTarget || pathSource === pathTarget) return;
    setPathLoading(true);
    setPathResult(null);
    pathStateRef.current = null;
    try {
      const res = await api.get('/entities/path', {
        params: { source_id: pathSource, target_id: pathTarget, max_depth: 3 },
      });
      const result = res.data as PathResult;
      setPathResult(result);
      if (result.found) {
        const nodeIds = new Set(result.path.map(s => s.entity.id));
        const edgePairs = new Set<string>();
        for (let i = 0; i < result.path.length - 1; i++) {
          edgePairs.add(`${result.path[i].entity.id}|${result.path[i + 1].entity.id}`);
          edgePairs.add(`${result.path[i + 1].entity.id}|${result.path[i].entity.id}`);
        }
        pathStateRef.current = { nodeIds, edgePairs };
      }
    } catch {
      setPathResult(null);
    } finally {
      setPathLoading(false);
    }
  }, [pathSource, pathTarget]);

  const clearPath = useCallback(() => {
    setPathResult(null);
    setPathSource('');
    setPathTarget('');
    pathStateRef.current = null;
  }, []);

  // ── Type filter toggle ──────────────────────────────────
  const toggleType = useCallback((t: string) => {
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(t)) {
        if (next.size > 1) next.delete(t); // keep at least one
      } else {
        next.add(t);
      }
      return next;
    });
  }, []);

  // ── Render ──────────────────────────────────────────────
  return (
    <div className="entity-graph-root">
      {/* Controls bar */}
      <div className="entity-graph-controls">
        {/* Time range */}
        <div className="entity-graph-control-group">
          <label className="entity-graph-label">Range</label>
          <select
            className="select select--sm"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            <option value={6}>6h</option>
            <option value={24}>24h</option>
            <option value={48}>48h</option>
            <option value={168}>7d</option>
            <option value={720}>30d</option>
          </select>
        </div>

        {/* Min mentions */}
        <div className="entity-graph-control-group">
          <label className="entity-graph-label">Min Mentions</label>
          <select
            className="select select--sm"
            value={minMentions}
            onChange={(e) => setMinMentions(Number(e.target.value))}
          >
            {[1, 2, 3, 5, 10].map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </div>

        {/* Node limit */}
        <div className="entity-graph-control-group">
          <label className="entity-graph-label">Nodes</label>
          <select
            className="select select--sm"
            value={nodeLimit}
            onChange={(e) => setNodeLimit(Number(e.target.value))}
          >
            {[25, 50, 100].map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </div>

        {/* Type filter */}
        <div className="entity-graph-control-group entity-graph-types">
          <label className="entity-graph-label">Types</label>
          <div className="entity-graph-type-pills">
            {ENTITY_TYPES.map((t) => (
              <button
                key={t}
                className={`entity-graph-type-pill entity-graph-type-pill--${t.toLowerCase()}${typeFilter.has(t) ? ' active' : ''}`}
                onClick={() => toggleType(t)}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Stats */}
        {!loading && !error && (
          <div className="entity-graph-stats">
            <span>{nodeCount} nodes</span>
            <span className="entity-graph-stats-sep">·</span>
            <span>{edgeCount} edges</span>
            {!simDone && <span className="entity-graph-settling">settling…</span>}
          </div>
        )}

        {/* Path finder controls */}
        <div className="entity-graph-control-group entity-graph-path-group">
          <label className="entity-graph-label">Path:</label>
          <select
            className="select select--sm"
            value={pathSource}
            onChange={e => { setPathSource(e.target.value); setPathResult(null); pathStateRef.current = null; }}
            style={{ maxWidth: 130 }}
          >
            <option value="">From…</option>
            {nodeList.map(n => (
              <option key={n.id} value={n.id}>{n.name.slice(0, 20)}</option>
            ))}
          </select>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>→</span>
          <select
            className="select select--sm"
            value={pathTarget}
            onChange={e => { setPathTarget(e.target.value); setPathResult(null); pathStateRef.current = null; }}
            style={{ maxWidth: 130 }}
          >
            <option value="">To…</option>
            {nodeList.filter(n => n.id !== pathSource).map(n => (
              <option key={n.id} value={n.id}>{n.name.slice(0, 20)}</option>
            ))}
          </select>
          <button
            className="btn btn-secondary btn-sm"
            onClick={findPath}
            disabled={!pathSource || !pathTarget || pathLoading || loading}
          >
            {pathLoading ? '…' : '🔗 Find'}
          </button>
          {pathResult && (
            <button className="btn btn-secondary btn-sm" onClick={clearPath}>✕ Clear</button>
          )}
        </div>

        <div className="entity-graph-spacer" />

      {/* Refresh */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setRefreshKey((k) => k + 1)}
          disabled={loading}
        >
          ↺ Refresh
        </button>
      </div>

      {/* Canvas area */}
      <div ref={containerRef} className="entity-graph-canvas-wrap">
        {loading && (
          <div className="entity-graph-overlay">
            <span className="spinner" />
            <span>Building graph…</span>
          </div>
        )}
        {error && (
          <div className="entity-graph-overlay entity-graph-overlay--error">
            ⚠ {error}
          </div>
        )}
        {!loading && !error && nodeCount === 0 && (
          <div className="entity-graph-overlay">
            <span style={{ fontSize: 28, opacity: 0.4 }}>🕸️</span>
            <span>No entities found for these filters.</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Try increasing the time range or lowering the min mentions threshold.
            </span>
          </div>
        )}
        <canvas
          ref={canvasRef}
          className="entity-graph-canvas"
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          onClick={handleClick}
          style={{ display: loading || error ? 'none' : 'block' }}
        />
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="entity-graph-tooltip"
          style={{ left: tooltip.x + 14, top: tooltip.y - 10 }}
        >
          <div className="entity-graph-tooltip__name">{tooltip.node.name}</div>
          <div className="entity-graph-tooltip__meta">
            <span
              className="entity-graph-tooltip__type"
              style={{ color: TYPE_COLORS[tooltip.node.type] ?? '#6b7280' }}
            >
              {tooltip.node.type}
            </span>
            <span className="entity-graph-tooltip__mentions">
              {tooltip.node.mentions} mention{tooltip.node.mentions !== 1 ? 's' : ''}
            </span>
          </div>
          <div className="entity-graph-tooltip__hint">Click to view detail</div>
        </div>
      )}

      {/* Legend */}
      <div className="entity-graph-legend">
        {ENTITY_TYPES.filter((t) => typeFilter.has(t)).map((t) => (
          <div key={t} className="entity-graph-legend__item">
            <span
              className="entity-graph-legend__dot"
              style={{ background: TYPE_COLORS[t] }}
            />
            <span>{t}</span>
          </div>
        ))}
      </div>

      {/* Path result summary */}
      {pathResult && (
        <div className={`entity-graph-path-summary entity-graph-path-summary--${pathResult.found ? 'found' : 'notfound'}`}>
          {pathResult.found ? (
            <>
              <span className="entity-graph-path-summary__label">
                🔗 Path ({pathResult.depth} hop{pathResult.depth !== 1 ? 's' : ''}):
              </span>
              <span className="entity-graph-path-summary__chain">
                {pathResult.path.map((step, i) => (
                  <span key={step.entity.id}>
                    <span className="entity-graph-path-summary__node">{step.entity.name}</span>
                    {i < pathResult.path.length - 1 && (
                      <span className="entity-graph-path-summary__edge">
                        {' '}({pathResult.path[i + 1].connecting_posts} posts)→{' '}
                      </span>
                    )}
                  </span>
                ))}
              </span>
            </>
          ) : (
            <span className="entity-graph-path-summary__notfound">
              ✗ No path found between {pathResult.source.name} and {pathResult.target.name} within 3 hops
            </span>
          )}
        </div>
      )}
    </div>
  );
}

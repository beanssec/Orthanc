import { WidgetConfig } from './WidgetCard';

// ── Types ──────────────────────────────────────────────────

interface WidgetTemplate {
  id: string;
  name: string;
  description: string;
  category: 'military' | 'markets' | 'diplomacy' | 'data' | 'custom';
  icon: string;
  config: Partial<WidgetConfig>;
}

export interface WidgetTemplatePickerProps {
  tabId: string;
  widgets: WidgetConfig[];
  onAdd: (widget: WidgetConfig) => void;
  onClose: () => void;
}

// ── Templates ──────────────────────────────────────────────

const TEMPLATES: WidgetTemplate[] = [
  // Military
  {
    id: 'strike-chart',
    name: 'Daily Strike Activity',
    description: 'Line chart of US/Israel/Iran/Hezbollah strikes over time',
    category: 'military',
    icon: '💥',
    config: { type: 'builtin', component: 'StrikeChart', grid: { x: 0, y: 0, w: 12, h: 5 } },
  },
  {
    id: 'vip-flights',
    name: 'VIP Flight Sightings',
    description: 'Government aircraft detected in the last 48 hours',
    category: 'military',
    icon: '✈️',
    config: {
      type: 'api',
      title: 'VIP Flight Sightings',
      data_source: { endpoint: '/layers/flights/vip', params: { hours: 48 } },
      viz: 'table',
      grid: { x: 0, y: 0, w: 6, h: 4 },
    },
  },
  {
    id: 'mil-narratives',
    name: 'Military Narratives (High Divergence)',
    description: 'Active military narratives with significant source disagreement',
    category: 'military',
    icon: '⚔️',
    config: {
      type: 'api',
      title: 'Military Narratives (High Divergence)',
      data_source: { endpoint: '/narratives/', params: { status: 'active', min_divergence: 0.3, limit: 10 } },
      viz: 'table',
      grid: { x: 0, y: 0, w: 6, h: 4 },
    },
  },
  // Markets
  {
    id: 'oil-prices',
    name: 'Oil & Energy Prices',
    description: 'Current oil, gas, and energy commodity prices',
    category: 'markets',
    icon: '🛢️',
    config: {
      type: 'api',
      title: 'Oil & Energy Prices',
      data_source: { endpoint: '/finance/quotes', params: { tickers: 'CL,BZ,NG' } },
      viz: 'stat_cards',
      grid: { x: 0, y: 0, w: 6, h: 3 },
    },
  },
  {
    id: 'market-alerts',
    name: 'Economic Alerts',
    description: 'Recent alerts related to markets and sanctions',
    category: 'markets',
    icon: '📈',
    config: {
      type: 'api',
      title: 'Economic Alerts',
      data_source: { endpoint: '/alerts/events/', params: { limit: 10 } },
      viz: 'table',
      grid: { x: 0, y: 0, w: 12, h: 4 },
    },
  },
  // Diplomacy
  {
    id: 'divergence-leaders',
    name: 'Most Contested Narratives',
    description: 'Narratives with highest source group divergence',
    category: 'diplomacy',
    icon: '🗣️',
    config: {
      type: 'api',
      title: 'Most Contested Narratives',
      data_source: { endpoint: '/narratives/', params: { status: 'active', min_divergence: 0.3, limit: 10 } },
      viz: 'table',
      grid: { x: 0, y: 0, w: 12, h: 5 },
    },
  },
  {
    id: 'ceasefire-signals',
    name: 'Ceasefire / Diplomatic Signals',
    description: 'Recent alerts matching diplomatic keywords',
    category: 'diplomacy',
    icon: '🕊️',
    config: {
      type: 'api',
      title: 'Ceasefire Signals',
      data_source: { endpoint: '/alerts/events/', params: { limit: 10 } },
      viz: 'feed',
      grid: { x: 0, y: 0, w: 6, h: 5 },
    },
  },
  // Data / General
  {
    id: 'post-velocity',
    name: 'Post Velocity',
    description: 'Posts per hour across all sources',
    category: 'data',
    icon: '📡',
    config: {
      type: 'api',
      title: 'Post Velocity',
      data_source: { endpoint: '/dashboard/velocity', params: { hours: 24 } },
      viz: 'line_chart',
      grid: { x: 0, y: 0, w: 12, h: 4 },
    },
  },
  {
    id: 'recent-posts',
    name: 'Recent Posts Feed',
    description: 'Latest posts from all sources',
    category: 'data',
    icon: '📰',
    config: {
      type: 'api',
      title: 'Recent Posts',
      data_source: { endpoint: '/feed/', params: { page_size: 10 } },
      viz: 'feed',
      grid: { x: 0, y: 0, w: 12, h: 5 },
    },
  },
  {
    id: 'trending-entities',
    name: 'Trending Entities',
    description: 'Most mentioned entities in the last 24 hours',
    category: 'data',
    icon: '🔥',
    config: {
      type: 'api',
      title: 'Trending Entities',
      data_source: { endpoint: '/dashboard/trending-entities', params: { hours: 24 } },
      viz: 'table',
      grid: { x: 0, y: 0, w: 6, h: 4 },
    },
  },
  {
    id: 'source-health',
    name: 'Source Health',
    description: 'Status of all configured data sources',
    category: 'data',
    icon: '🔌',
    config: {
      type: 'api',
      title: 'Source Health',
      data_source: { endpoint: '/sources/health' },
      viz: 'table',
      grid: { x: 0, y: 0, w: 12, h: 4 },
    },
  },
  // Custom
  {
    id: 'custom-api',
    name: 'Custom API Widget',
    description: 'Create a widget from any API endpoint',
    category: 'custom',
    icon: '🔧',
    config: {
      type: 'api',
      title: 'Custom Widget',
      data_source: { endpoint: '/', params: {} },
      viz: 'table',
      grid: { x: 0, y: 0, w: 6, h: 4 },
    },
  },
  {
    id: 'custom-oql',
    name: 'Custom OQL Query',
    description: 'Create a widget powered by an OQL query',
    category: 'custom',
    icon: '🔍',
    config: {
      type: 'api',
      title: 'OQL Widget',
      data_source: { endpoint: '/query', params: { q: '' } },
      viz: 'table',
      grid: { x: 0, y: 0, w: 12, h: 4 },
    },
  },
];

// ── Category config ────────────────────────────────────────

const CATEGORIES: { id: WidgetTemplate['category']; label: string; icon: string }[] = [
  { id: 'military', label: 'Military', icon: '🎖️' },
  { id: 'markets', label: 'Markets', icon: '💹' },
  { id: 'diplomacy', label: 'Diplomacy', icon: '🌐' },
  { id: 'data', label: 'Data & Intel', icon: '📊' },
  { id: 'custom', label: 'Custom', icon: '⚙️' },
];

// ── Utility ────────────────────────────────────────────────

function generateWidgetId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

function getMaxY(widgets: WidgetConfig[]): number {
  if (widgets.length === 0) return 0;
  return Math.max(...widgets.map((w) => w.grid.y + w.grid.h));
}

// ── Component ──────────────────────────────────────────────

export function WidgetTemplatePicker({ widgets, onAdd, onClose }: WidgetTemplatePickerProps) {
  const handleSelectTemplate = (template: WidgetTemplate) => {
    const maxY = getMaxY(widgets);
    const baseGrid = template.config.grid ?? { x: 0, y: 0, w: 6, h: 4 };

    const newWidget: WidgetConfig = {
      id: generateWidgetId(),
      type: template.config.type ?? 'api',
      title: template.config.title,
      icon: template.icon,
      component: template.config.component,
      data_source: template.config.data_source,
      viz: template.config.viz,
      grid: {
        x: baseGrid.x,
        y: maxY,
        w: baseGrid.w,
        h: baseGrid.h,
      },
    };

    onAdd(newWidget);
  };

  return (
    <div className="wtp-overlay" onClick={onClose}>
      <div className="wtp-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="wtp-header">
          <div className="wtp-title">Add Widget</div>
          <button className="wtp-close" onClick={onClose} title="Close">✕</button>
        </div>

        {/* Content */}
        <div className="wtp-body">
          {CATEGORIES.map((cat) => {
            const templates = TEMPLATES.filter((t) => t.category === cat.id);
            if (templates.length === 0) return null;
            return (
              <div key={cat.id} className="wtp-category">
                <div className="wtp-category__header">
                  <span className="wtp-category__icon">{cat.icon}</span>
                  <span className="wtp-category__label">{cat.label}</span>
                </div>
                <div className="wtp-grid">
                  {templates.map((template) => (
                    <button
                      key={template.id}
                      className="wtp-card"
                      onClick={() => handleSelectTemplate(template)}
                      title={template.description}
                    >
                      <div className="wtp-card__icon">{template.icon}</div>
                      <div className="wtp-card__name">{template.name}</div>
                      <div className="wtp-card__desc">{template.description}</div>
                      <div className="wtp-card__add">+ Add</div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

# Dashboard Builder — Feature Specification

## Overview
Replace the static dashboard with a configurable, tab-based dashboard builder. Users can create custom tabs, add widgets with different visualisation types, connect them to data sources or OQL queries, and arrange them via drag-and-drop with resize.

## Phase 1: Tab System + Preset Layouts
**Goal:** Replace single dashboard with tabbed interface. 4 default tabs with curated widget sets.

### Default Tabs
1. **Overview** — current dashboard widgets (KPIs, velocity, source health, trending, alerts)
2. **Military / Strikes** — strike chart, VIP flights, frontline map, CENTCOM feed
3. **Markets / Economic** — oil price, portfolio, cashtag activity, sanctions alerts
4. **Diplomacy** — narrative divergence (high-divergence narratives), ceasefire signals, mediator activity

### Data Model
```sql
CREATE TABLE dashboard_tabs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    icon VARCHAR(10),              -- emoji icon
    position INTEGER NOT NULL DEFAULT 0,
    is_default BOOLEAN DEFAULT false,
    layout JSONB NOT NULL DEFAULT '[]',  -- array of widget configs
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, name)
);
```

### Widget Config Schema (stored in layout JSONB)
```json
{
    "id": "widget-uuid",
    "type": "line_chart | bar_chart | stat_card | table | donut | map | feed",
    "title": "Daily Strike Activity",
    "data_source": {
        "kind": "api",               // "api" | "oql"
        "endpoint": "/dashboard/strikes",
        "params": {"days": 14},
        // OR for OQL:
        "kind": "oql",
        "query": "posts where source_type = telegram group by day"
    },
    "config": {
        "colors": {"us": "#3b82f6"},
        "time_range": "14d",
        "refresh_interval": 300
    },
    "grid": {"x": 0, "y": 0, "w": 6, "h": 4}   // react-grid-layout position
}
```

### API Endpoints
- `GET /dashboard/tabs` — list user's tabs
- `POST /dashboard/tabs` — create tab
- `PUT /dashboard/tabs/{id}` — update tab (name, layout, position)
- `DELETE /dashboard/tabs/{id}` — delete tab
- `POST /dashboard/tabs/seed-defaults` — create the 4 default tabs

### Frontend Components
- `DashboardTabs.tsx` — tab bar with +/edit/delete
- `DashboardGrid.tsx` — react-grid-layout grid with widget cards
- `WidgetCard.tsx` — generic widget wrapper (title, refresh, edit, delete)
- `WidgetRenderer.tsx` — routes widget type to correct viz component

## Phase 2: Widget System
**Goal:** Drag-and-drop positioning, resize, edit modal.

### Widget Types
| Type | Component | Data Shape |
|------|-----------|-----------|
| line_chart | LineChart.tsx | `[{date, values: {key: number}}]` |
| bar_chart | BarChart.tsx | `[{label, value}]` |
| stat_card | StatCard.tsx | `{value, label, trend_pct}` |
| table | DataTable.tsx | `{columns, rows}` |
| donut | DonutChart.tsx | `[{label, value}]` |
| feed | FeedWidget.tsx | `[{title, content, timestamp}]` |

### Edit Modal
- Widget title (editable)
- Data source picker (dropdown of API endpoints OR OQL query editor)
- Visualisation type selector
- Time range
- Refresh interval
- Type-specific config (colors, limits, filters)

### Drag & Drop
- `react-grid-layout` (responsive, no jQuery dependency)
- Grid: 12 columns, row height 60px
- Min widget size: 2x2, max: 12x8
- Save layout to DB on drag end

## Phase 3: Query-Driven Widgets
**Goal:** Custom OQL queries powering widgets.

### OQL Integration
- Widget data_source.kind = "oql"
- Queries run server-side via existing `/query` endpoint
- Results mapped to widget type's expected data shape
- Auto-detect best visualisation from query result shape

### Template Library
Pre-built widget templates users can add with one click:
- "Posts per hour (last 24h)" → line_chart
- "Source type breakdown" → donut
- "Top entities today" → bar_chart
- "Narrative divergence leaders" → table
- "Oil price vs strike count" → dual-axis line_chart

## Dependencies
- `react-grid-layout` — npm install (lightweight, MIT licensed)
- Migration for dashboard_tabs table
- No backend model changes beyond the new table

## Implementation Order
1. Migration + model + CRUD API
2. Tab UI (tab bar, switching, add/delete)
3. Default tab seeding with existing widgets refactored into widget configs
4. react-grid-layout integration
5. Widget edit modal
6. OQL query integration
7. Template library

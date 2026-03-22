import { useCallback, useRef } from 'react';
import { ResponsiveGridLayout, useContainerWidth } from 'react-grid-layout';
import type { Layout } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import { WidgetCard, WidgetConfig } from './WidgetCard';
import api from '../../services/api';

interface DashboardGridProps {
  tabId: string;
  widgets: WidgetConfig[];
  onLayoutChange?: (widgets: WidgetConfig[]) => void;
}

function GridContainer({ tabId, widgets, onLayoutChange }: DashboardGridProps) {
  const { width, containerRef, mounted } = useContainerWidth();
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Convert widgets to react-grid-layout layout format
  const layout: Layout[] = widgets.map((w) => ({
    i: w.id,
    x: w.grid.x,
    y: w.grid.y,
    w: w.grid.w,
    h: w.grid.h,
    minW: 2,
    minH: 2,
  }));

  const layouts = { lg: layout, md: layout, sm: layout, xs: layout };

  const handleLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      // Merge updated positions back into widgets
      const updatedWidgets = widgets.map((widget) => {
        const item = newLayout.find((l) => l.i === widget.id);
        if (!item) return widget;
        return {
          ...widget,
          grid: {
            x: item.x,
            y: item.y,
            w: item.w,
            h: item.h,
          },
        };
      });

      onLayoutChange?.(updatedWidgets);

      // Debounced save to backend
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
      saveTimerRef.current = setTimeout(async () => {
        try {
          await api.put(`/dashboard-tabs/${tabId}`, {
            layout: updatedWidgets,
          });
        } catch {
          // Non-critical — layout save failure is silent
        }
      }, 500);
    },
    [tabId, widgets, onLayoutChange]
  );

  const handleDeleteWidget = useCallback(
    async (widgetId: string) => {
      const updatedWidgets = widgets.filter((w) => w.id !== widgetId);
      onLayoutChange?.(updatedWidgets);
      try {
        await api.put(`/dashboard-tabs/${tabId}`, {
          layout: updatedWidgets,
        });
      } catch {
        // Non-critical
      }
    },
    [tabId, widgets, onLayoutChange]
  );

  if (widgets.length === 0) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          height: '200px',
          color: 'var(--text-muted)',
          gap: '8px',
          fontSize: '13px',
        }}
      >
        <span style={{ fontSize: '24px' }}>📋</span>
        <span>No widgets on this tab yet</span>
        <span style={{ fontSize: '11px' }}>Widget configuration coming in Phase 2</span>
      </div>
    );
  }

  return (
    <div ref={containerRef as React.RefObject<HTMLDivElement>} style={{ width: '100%' }}>
      {mounted && (
        <ResponsiveGridLayout
          width={width}
          layouts={layouts}
          breakpoints={{ lg: 1200, md: 996, sm: 768, xs: 480 }}
          cols={{ lg: 12, md: 8, sm: 4, xs: 2 }}
          rowHeight={60}
          dragConfig={{ handle: '.widget-card__header' }}
          onLayoutChange={handleLayoutChange}
          margin={[8, 8]}
          containerPadding={[0, 0]}
        >
          {widgets.map((widget) => (
            <div key={widget.id}>
              <WidgetCard
                widget={widget}
                onDelete={handleDeleteWidget}
              />
            </div>
          ))}
        </ResponsiveGridLayout>
      )}
    </div>
  );
}

export function DashboardGrid(props: DashboardGridProps) {
  return (
    <div className="dashboard-grid">
      <GridContainer {...props} />
    </div>
  );
}

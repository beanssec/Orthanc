import { useEffect } from 'react';
import { useAlertStore } from '../../stores/alertStore';
import type { AlertEvent } from '../../stores/alertStore';
import '../../styles/alerts.css';

const SEVERITY_EMOJI: Record<string, string> = {
  flash: '🔴',
  urgent: '🟠',
  routine: '🔵',
};

// Track shown alert IDs to avoid re-showing on re-render
const _shownIds = new Set<string>();

function Toast({ event, onDismiss }: { event: AlertEvent; onDismiss: () => void }) {
  useEffect(() => {
    // Auto-dismiss after 8 seconds
    const t = setTimeout(onDismiss, 8000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div className={`alert-toast severity-${event.severity}`} onClick={onDismiss}>
      <div className="alert-toast-title">
        {SEVERITY_EMOJI[event.severity] ?? '🔔'} {event.title}
      </div>
      {event.summary && (
        <div className="alert-toast-summary">{event.summary.slice(0, 120)}</div>
      )}
    </div>
  );
}

/**
 * Mounts globally in AppShell.
 * Listens to alert store for incoming alerts and renders toasts.
 */
export function AlertToastContainer() {
  const events = useAlertStore((s) => s.events);
  // We only show the most recent unacknowledged events as toasts
  const toastEvents = events
    .filter((e) => !e.acknowledged && !_shownIds.has(e.id))
    .slice(0, 3);

  // Mark as shown
  toastEvents.forEach((e) => _shownIds.add(e.id));

  // We keep a local ref to visible toasts for dismiss tracking
  const { acknowledgeEvent } = useAlertStore();

  if (toastEvents.length === 0) return null;

  return (
    <div className="alert-toast-container">
      {toastEvents.map((ev) => (
        <Toast
          key={ev.id}
          event={ev}
          onDismiss={() => acknowledgeEvent(ev.id)}
        />
      ))}
    </div>
  );
}

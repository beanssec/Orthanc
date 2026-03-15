/**
 * ScheduledBriefsView — Sprint 31 Checkpoint 4
 *
 * UI for managing multiple scheduled briefs.  Wires against the
 * /scheduled-briefs/ CRUD API added in Sprint 31 Checkpoint 1.
 *
 * Features:
 *  - list all schedules with inline enable/disable toggle
 *  - create / edit via slide-out form
 *  - delete with confirm guard
 *  - last-run / last-status / last-error visibility
 *  - run history (last 10) expandable per schedule
 */

import { useCallback, useEffect, useState } from 'react';
import api from '../../services/api';
import '../../styles/scheduled-briefs.css';

// ── Types ──────────────────────────────────────────────────────────────────

interface ScheduledBrief {
  id: string;
  name: string;
  enabled: boolean;
  schedule_hour_utc: number | null;
  cron_expr: string | null;
  model_id: string;
  time_window_hours: number;
  topic_filter: string | null;
  source_filters: string[] | null;
  delivery_method: string;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

interface ScheduledBriefRun {
  id: string;
  schedule_id: string;
  status: string;
  error_message: string | null;
  brief_id: string | null;
  started_at: string;
  completed_at: string | null;
}

interface Model {
  id: string;
  name: string;
  available: boolean;
  requires?: string;
}

// blank form state
interface FormState {
  name: string;
  enabled: boolean;
  schedule_hour_utc: number;
  model_id: string;
  time_window_hours: number;
  topic_filter: string;
  source_filters: string[];
  delivery_method: string;
}

const BLANK_FORM: FormState = {
  name: 'Daily Brief',
  enabled: true,
  schedule_hour_utc: 8,
  model_id: 'grok-3-mini',
  time_window_hours: 24,
  topic_filter: '',
  source_filters: [],
  delivery_method: 'internal',
};

const TIME_OPTIONS = [
  { label: '6h', hours: 6 },
  { label: '12h', hours: 12 },
  { label: '24h', hours: 24 },
  { label: '48h', hours: 48 },
  { label: '7d', hours: 168 },
];

const SOURCE_TYPES = ['rss', 'x', 'telegram', 'reddit', 'discord', 'shodan', 'acled', 'webhook', 'document'];

const DELIVERY_METHODS = [
  { value: 'internal', label: 'Internal (save to briefs history)' },
  { value: 'telegram', label: 'Telegram DM' },
  { value: 'webhook', label: 'Webhook POST' },
];

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => i);

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(ts: string | null): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtDuration(startTs: string, endTs: string | null): string {
  if (!endTs) return '…';
  const ms = new Date(endTs).getTime() - new Date(startTs).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms / 60000)}m`;
}

function statusDotClass(status: string | null): string {
  if (status === 'success') return 'sb-dot sb-dot--ok';
  if (status === 'error') return 'sb-dot sb-dot--err';
  if (status === 'running') return 'sb-dot sb-dot--run';
  return 'sb-dot';
}

function nextRunLabel(s: ScheduledBrief): string {
  if (!s.enabled) return 'Disabled';
  if (s.next_run_at) return fmt(s.next_run_at);
  if (s.schedule_hour_utc !== null) {
    const h = String(s.schedule_hour_utc).padStart(2, '0');
    return `Daily at ${h}:00 UTC`;
  }
  return '—';
}

// ── Main component ─────────────────────────────────────────────────────────

export function ScheduledBriefsView() {
  const [schedules, setSchedules] = useState<ScheduledBrief[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // expanded run-history per schedule id
  const [expandedRuns, setExpandedRuns] = useState<Record<string, ScheduledBriefRun[]>>({});
  const [loadingRuns, setLoadingRuns] = useState<Record<string, boolean>>({});

  // models (for selectors)
  const [models, setModels] = useState<Model[]>([]);

  // form state
  const [formOpen, setFormOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null); // null = create
  const [form, setForm] = useState<FormState>(BLANK_FORM);
  const [formSaving, setFormSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // delete confirm
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  // ── Data loading ──────────────────────────────────────────────────────

  const fetchSchedules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/scheduled-briefs/');
      setSchedules(res.data);
    } catch (e: unknown) {
      setError((e as { message?: string })?.message ?? 'Failed to load schedules');
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchModels = useCallback(async () => {
    try {
      const res = await api.get('/briefs/models');
      setModels(res.data);
    } catch {
      // non-fatal
    }
  }, []);

  useEffect(() => {
    fetchSchedules();
    fetchModels();
  }, [fetchSchedules, fetchModels]);

  // ── Run history ───────────────────────────────────────────────────────

  async function toggleRuns(s: ScheduledBrief) {
    const id = s.id;
    if (expandedRuns[id] !== undefined) {
      // collapse
      setExpandedRuns((prev) => {
        const copy = { ...prev };
        delete copy[id];
        return copy;
      });
      return;
    }
    setLoadingRuns((prev) => ({ ...prev, [id]: true }));
    try {
      const res = await api.get(`/scheduled-briefs/${id}/runs?limit=10`);
      setExpandedRuns((prev) => ({ ...prev, [id]: res.data }));
    } catch {
      setExpandedRuns((prev) => ({ ...prev, [id]: [] }));
    } finally {
      setLoadingRuns((prev) => ({ ...prev, [id]: false }));
    }
  }

  // ── Enable / disable toggle ───────────────────────────────────────────

  async function handleToggle(s: ScheduledBrief) {
    setTogglingId(s.id);
    try {
      const res = await api.patch(`/scheduled-briefs/${s.id}`, { enabled: !s.enabled });
      setSchedules((prev) => prev.map((x) => (x.id === s.id ? res.data : x)));
    } catch {
      // ignore
    } finally {
      setTogglingId(null);
    }
  }

  // ── Delete ────────────────────────────────────────────────────────────

  async function handleDelete(id: string) {
    try {
      await api.delete(`/scheduled-briefs/${id}`);
      setSchedules((prev) => prev.filter((s) => s.id !== id));
      setExpandedRuns((prev) => {
        const copy = { ...prev };
        delete copy[id];
        return copy;
      });
    } catch {
      // ignore
    } finally {
      setDeletingId(null);
    }
  }

  // ── Form helpers ──────────────────────────────────────────────────────

  function openCreate() {
    const firstAvail = models.find((m) => m.available);
    setForm({ ...BLANK_FORM, model_id: firstAvail?.id ?? 'grok-3-mini' });
    setEditingId(null);
    setFormError(null);
    setFormOpen(true);
  }

  function openEdit(s: ScheduledBrief) {
    setForm({
      name: s.name,
      enabled: s.enabled,
      schedule_hour_utc: s.schedule_hour_utc ?? 8,
      model_id: s.model_id,
      time_window_hours: s.time_window_hours,
      topic_filter: s.topic_filter ?? '',
      source_filters: s.source_filters ?? [],
      delivery_method: s.delivery_method,
    });
    setEditingId(s.id);
    setFormError(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditingId(null);
  }

  async function handleFormSave() {
    setFormSaving(true);
    setFormError(null);
    const payload = {
      name: form.name.trim() || 'Daily Brief',
      enabled: form.enabled,
      schedule_hour_utc: form.schedule_hour_utc,
      model_id: form.model_id,
      time_window_hours: form.time_window_hours,
      topic_filter: form.topic_filter.trim() || null,
      source_filters: form.source_filters.length > 0 ? form.source_filters : null,
      delivery_method: form.delivery_method,
    };
    try {
      if (editingId) {
        const res = await api.patch(`/scheduled-briefs/${editingId}`, payload);
        setSchedules((prev) => prev.map((s) => (s.id === editingId ? res.data : s)));
      } else {
        const res = await api.post('/scheduled-briefs/', payload);
        setSchedules((prev) => [res.data, ...prev]);
      }
      closeForm();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFormError(detail ?? (e as Error)?.message ?? 'Save failed');
    } finally {
      setFormSaving(false);
    }
  }

  function toggleSource(src: string) {
    setForm((f) => ({
      ...f,
      source_filters: f.source_filters.includes(src)
        ? f.source_filters.filter((s) => s !== src)
        : [...f.source_filters, src],
    }));
  }

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="sb-view">
      {/* ── Header ── */}
      <div className="sb-header">
        <div>
          <span className="sb-title">Scheduled Briefs</span>
          <span className="sb-subtitle">Automated intelligence briefs on a recurring schedule</span>
        </div>
        <button className="btn btn-primary sb-create-btn" onClick={openCreate}>
          + New Schedule
        </button>
      </div>

      {/* ── Main list ── */}
      {loading ? (
        <div className="sb-loading"><span className="spinner" /> Loading schedules…</div>
      ) : error ? (
        <div className="sb-error">⚠ {error}</div>
      ) : schedules.length === 0 ? (
        <div className="sb-empty">
          <div className="sb-empty__icon">🕐</div>
          <div className="sb-empty__title">No scheduled briefs</div>
          <div className="sb-empty__body">
            Create a schedule to receive automated intelligence briefs at regular intervals.
          </div>
          <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={openCreate}>
            + New Schedule
          </button>
        </div>
      ) : (
        <div className="sb-list">
          {schedules.map((s) => {
            const runs = expandedRuns[s.id];
            const runsOpen = runs !== undefined;
            const runsLoading = loadingRuns[s.id] ?? false;
            const isDeletingThis = deletingId === s.id;
            const isToggling = togglingId === s.id;

            return (
              <div key={s.id} className={`sb-card${s.enabled ? '' : ' sb-card--disabled'}`}>
                {/* ── Card header ── */}
                <div className="sb-card__header">
                  <div className="sb-card__title-row">
                    {/* Enable toggle */}
                    <button
                      className={`sb-toggle${s.enabled ? ' sb-toggle--on' : ''}`}
                      onClick={() => handleToggle(s)}
                      disabled={isToggling}
                      title={s.enabled ? 'Disable' : 'Enable'}
                    >
                      <span className="sb-toggle__knob" />
                    </button>

                    <span className="sb-card__name">{s.name}</span>

                    {/* Status badge */}
                    {s.last_status && (
                      <span className={`sb-status-badge sb-status-badge--${s.last_status}`}>
                        {s.last_status}
                      </span>
                    )}
                  </div>

                  <div className="sb-card__actions">
                    <button className="btn btn-ghost btn-sm" onClick={() => openEdit(s)} title="Edit">
                      ✏
                    </button>
                    {isDeletingThis ? (
                      <>
                        <span className="sb-delete-confirm-text">Delete?</span>
                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(s.id)}>
                          Confirm
                        </button>
                        <button className="btn btn-secondary btn-sm" onClick={() => setDeletingId(null)}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setDeletingId(s.id)}
                        title="Delete"
                      >
                        🗑
                      </button>
                    )}
                  </div>
                </div>

                {/* ── Card meta row ── */}
                <div className="sb-card__meta">
                  <span className="sb-meta-item">
                    <span className="sb-meta-label">Model</span>
                    <span className="sb-meta-value">{s.model_id}</span>
                  </span>
                  <span className="sb-meta-item">
                    <span className="sb-meta-label">Window</span>
                    <span className="sb-meta-value">
                      {s.time_window_hours >= 168 ? '7d' : `${s.time_window_hours}h`}
                    </span>
                  </span>
                  <span className="sb-meta-item">
                    <span className="sb-meta-label">Schedule</span>
                    <span className="sb-meta-value">
                      {s.schedule_hour_utc !== null
                        ? `Daily ${String(s.schedule_hour_utc).padStart(2, '0')}:00 UTC`
                        : s.cron_expr ?? '—'}
                    </span>
                  </span>
                  <span className="sb-meta-item">
                    <span className="sb-meta-label">Delivery</span>
                    <span className="sb-meta-value">{s.delivery_method}</span>
                  </span>
                  {s.topic_filter && (
                    <span className="sb-meta-item">
                      <span className="sb-meta-label">Topic</span>
                      <span className="sb-meta-value">{s.topic_filter}</span>
                    </span>
                  )}
                </div>

                {/* ── Run status row ── */}
                <div className="sb-card__run-row">
                  <div className="sb-run-info">
                    <span className="sb-meta-label">Last run</span>
                    <span className={statusDotClass(s.last_status)} />
                    <span className="sb-run-ts">{fmt(s.last_run_at)}</span>
                    {s.last_error && (
                      <span className="sb-run-error" title={s.last_error}>
                        ⚠ {s.last_error.length > 60 ? s.last_error.slice(0, 60) + '…' : s.last_error}
                      </span>
                    )}
                  </div>
                  <div className="sb-run-info">
                    <span className="sb-meta-label">Next run</span>
                    <span className="sb-run-ts">{nextRunLabel(s)}</span>
                  </div>
                  <button
                    className="btn btn-ghost btn-sm sb-history-btn"
                    onClick={() => toggleRuns(s)}
                    disabled={runsLoading}
                  >
                    {runsLoading ? <span className="spinner spinner-sm" /> : (runsOpen ? '▲ History' : '▼ History')}
                  </button>
                </div>

                {/* ── Run history table ── */}
                {runsOpen && (
                  <div className="sb-runs">
                    {runs.length === 0 ? (
                      <div className="sb-runs__empty">No runs recorded yet.</div>
                    ) : (
                      <table className="sb-runs__table">
                        <thead>
                          <tr>
                            <th>Started</th>
                            <th>Status</th>
                            <th>Duration</th>
                            <th>Brief</th>
                            <th>Error</th>
                          </tr>
                        </thead>
                        <tbody>
                          {runs.map((r) => (
                            <tr key={r.id} className={`sb-run-row sb-run-row--${r.status}`}>
                              <td className="sb-run__ts">{fmt(r.started_at)}</td>
                              <td>
                                <span className={`sb-status-badge sb-status-badge--${r.status}`}>
                                  {r.status}
                                </span>
                              </td>
                              <td className="sb-run__dur">{fmtDuration(r.started_at, r.completed_at)}</td>
                              <td>
                                {r.brief_id ? (
                                  <a
                                    href="/briefs"
                                    className="sb-run__brief-link"
                                    title={`Brief ${r.brief_id}`}
                                  >
                                    View
                                  </a>
                                ) : (
                                  <span className="sb-run__no-brief">—</span>
                                )}
                              </td>
                              <td className="sb-run__err">
                                {r.error_message ? (
                                  <span title={r.error_message}>
                                    {r.error_message.length > 50
                                      ? r.error_message.slice(0, 50) + '…'
                                      : r.error_message}
                                  </span>
                                ) : (
                                  '—'
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Create / Edit form drawer ── */}
      {formOpen && (
        <div className="sb-drawer-overlay" onClick={closeForm}>
          <div className="sb-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="sb-drawer__header">
              <span className="sb-drawer__title">
                {editingId ? 'Edit Schedule' : 'New Schedule'}
              </span>
              <button className="btn btn-ghost sb-drawer__close" onClick={closeForm}>✕</button>
            </div>

            <div className="sb-drawer__body">
              {/* Name */}
              <div className="sb-field">
                <label className="sb-field__label">Name</label>
                <input
                  className="input sb-field__input"
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Daily Brief"
                  maxLength={255}
                />
              </div>

              {/* Enabled */}
              <div className="sb-field sb-field--row">
                <label className="sb-field__label">Enabled</label>
                <button
                  className={`sb-toggle${form.enabled ? ' sb-toggle--on' : ''}`}
                  onClick={() => setForm((f) => ({ ...f, enabled: !f.enabled }))}
                >
                  <span className="sb-toggle__knob" />
                </button>
                <span className="sb-field__hint">{form.enabled ? 'Active' : 'Paused'}</span>
              </div>

              {/* Model */}
              <div className="sb-field">
                <label className="sb-field__label">Model</label>
                <select
                  className="sb-field__select"
                  value={form.model_id}
                  onChange={(e) => setForm((f) => ({ ...f, model_id: e.target.value }))}
                >
                  {models.length === 0 ? (
                    <option value="grok-3-mini">grok-3-mini</option>
                  ) : (
                    models.map((m) => (
                      <option key={m.id} value={m.id} disabled={!m.available}>
                        {m.name}{!m.available ? ` (needs ${m.requires ?? 'key'})` : ''}
                      </option>
                    ))
                  )}
                </select>
              </div>

              {/* Time window */}
              <div className="sb-field">
                <label className="sb-field__label">Time Window</label>
                <div className="sb-field__timerange">
                  {TIME_OPTIONS.map((opt) => (
                    <button
                      key={opt.hours}
                      className={`sb-timerange-btn${form.time_window_hours === opt.hours ? ' sb-timerange-btn--active' : ''}`}
                      onClick={() => setForm((f) => ({ ...f, time_window_hours: opt.hours }))}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Schedule hour */}
              <div className="sb-field">
                <label className="sb-field__label">Run at (UTC)</label>
                <select
                  className="sb-field__select sb-field__select--narrow"
                  value={form.schedule_hour_utc}
                  onChange={(e) => setForm((f) => ({ ...f, schedule_hour_utc: Number(e.target.value) }))}
                >
                  {HOUR_OPTIONS.map((h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, '0')}:00 UTC
                    </option>
                  ))}
                </select>
              </div>

              {/* Topic filter */}
              <div className="sb-field">
                <label className="sb-field__label">
                  Topic Filter <span className="sb-field__optional">(optional)</span>
                </label>
                <input
                  className="input sb-field__input"
                  type="text"
                  value={form.topic_filter}
                  onChange={(e) => setForm((f) => ({ ...f, topic_filter: e.target.value }))}
                  placeholder="Ukraine, cyber, Iran… (blank = all)"
                />
              </div>

              {/* Source filters */}
              <div className="sb-field">
                <label className="sb-field__label">
                  Source Filter <span className="sb-field__optional">(optional — blank = all)</span>
                </label>
                <div className="sb-field__sources">
                  {SOURCE_TYPES.map((src) => (
                    <label key={src} className="sb-source-chip">
                      <input
                        type="checkbox"
                        checked={form.source_filters.includes(src)}
                        onChange={() => toggleSource(src)}
                      />
                      <span>{src}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Delivery method */}
              <div className="sb-field">
                <label className="sb-field__label">Delivery Method</label>
                <select
                  className="sb-field__select"
                  value={form.delivery_method}
                  onChange={(e) => setForm((f) => ({ ...f, delivery_method: e.target.value }))}
                >
                  {DELIVERY_METHODS.map((d) => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </div>

              {formError && <div className="sb-form-error">⚠ {formError}</div>}
            </div>

            <div className="sb-drawer__footer">
              <button className="btn btn-secondary" onClick={closeForm} disabled={formSaving}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleFormSave} disabled={formSaving}>
                {formSaving ? <><span className="spinner spinner-sm" /> Saving…</> : '✓ Save Schedule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

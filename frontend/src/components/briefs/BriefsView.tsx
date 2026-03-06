import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import '../../styles/briefs.css';

// ── Types ──────────────────────────────────────────────────
interface Model {
  id: string;
  provider: string;
  name: string;
  description: string;
  strengths: string;
  context_window: number;
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  cost_estimate_per_brief: string;
  available: boolean;
  requires?: string;
}

interface SavedBrief {
  id: string;
  summary: string;
  post_count: number;
  time_range_hours: number;
  hours: number;
  model: string;
  model_name: string;
  cost_estimate: string;
  generated_at: string;
}

interface BriefSchedule {
  enabled: boolean;
  model_id: string;
  time_range_hours: number;
  schedule_hour_utc: number;
  last_generated: string | null;
}

type TabId = 'generate' | 'history' | 'schedule';

const TIME_OPTIONS = [
  { label: '6h', hours: 6 },
  { label: '12h', hours: 12 },
  { label: '24h', hours: 24 },
  { label: '48h', hours: 48 },
  { label: '7d', hours: 168 },
];

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => i);

// ── Helpers ────────────────────────────────────────────────
function formatCtx(ctx: number): string {
  if (ctx >= 1000000) return `${(ctx / 1000000).toFixed(0)}M ctx`;
  if (ctx >= 1000) return `${(ctx / 1000).toFixed(0)}K ctx`;
  return `${ctx} ctx`;
}

function formatDateTime(ts: string): string {
  return new Date(ts).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function briefHours(b: SavedBrief): number {
  return b.time_range_hours ?? b.hours ?? 24;
}

function getPreview(content: string): string {
  // Skip numbered section headers (e.g. "1. Executive Summary") and get first real content line
  const lines = content.split('\n').filter(
    (l) => l.trim() && !l.match(/^#+\s/) && !l.match(/^\d+\.\s/)
  );
  return lines[0]?.substring(0, 150) || 'No preview available';
}

function extractBriefTitle(brief: SavedBrief): string {
  if ((brief as unknown as { title?: string }).title) {
    return (brief as unknown as { title: string }).title;
  }
  if (brief.summary) {
    const lines = brief.summary.split('\n');
    for (const line of lines) {
      const stripped = line.trim();
      if (stripped.startsWith('# ') || stripped.startsWith('## ') || stripped.startsWith('### ')) {
        const heading = stripped.replace(/^#+\s+/, '').trim();
        if (heading.length > 3) return heading;
      }
    }
    for (const line of lines) {
      const stripped = line.trim();
      if (
        stripped.length > 10 &&
        !stripped.toLowerCase().startsWith('below is') &&
        !stripped.toLowerCase().startsWith('this is') &&
        !stripped.toLowerCase().startsWith('the following')
      ) {
        return stripped.length > 80 ? stripped.slice(0, 80) + '…' : stripped;
      }
    }
  }
  const model = brief.model_name ?? brief.model ?? 'AI';
  const date = new Date(brief.generated_at).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
  return `Intelligence Brief — ${model} — ${date}`;
}

function nextScheduledTime(hourUtc: number): string {
  const now = new Date();
  const nowUtcHour = now.getUTCHours();
  const target = new Date(now);
  target.setUTCHours(hourUtc, 0, 0, 0);
  if (nowUtcHour >= hourUtc) {
    target.setUTCDate(target.getUTCDate() + 1);
  }
  return `${String(hourUtc).padStart(2, '0')}:00 UTC — ${target.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short' })}`;
}

// ── Markdown-like renderer ────────────────────────────────
function renderBriefContent(text: string, navigate: (path: string) => void): React.ReactNode {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];
  let key = 0;

  function flushList() {
    if (listItems.length > 0) {
      elements.push(
        <ul key={`ul-${key++}`}>
          {listItems.map((item, i) => (
            <li key={i} dangerouslySetInnerHTML={{ __html: renderInline(item) }} />
          ))}
        </ul>
      );
      listItems = [];
    }
  }

  function renderInline(line: string): string {
    return line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  }

  for (const raw of lines) {
    const line = raw.trim();
    if (line.startsWith('### ')) {
      flushList();
      elements.push(<h3 key={key++}>{line.slice(4)}</h3>);
    } else if (line.startsWith('## ')) {
      flushList();
      elements.push(<h3 key={key++}>{line.slice(3)}</h3>);
    } else if (line.startsWith('# ')) {
      flushList();
      elements.push(<h3 key={key++}>{line.slice(2)}</h3>);
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      listItems.push(line.slice(2));
    } else if (line === '') {
      flushList();
    } else {
      flushList();
      elements.push(
        <p key={key++} dangerouslySetInnerHTML={{ __html: renderInline(line) }} />
      );
    }
  }
  flushList();
  void navigate;
  return <>{elements}</>;
}

// ── Component ──────────────────────────────────────────────
export function BriefsView() {
  const navigate = useNavigate();

  // Active tab
  const [activeTab, setActiveTab] = useState<TabId>('history');

  // ── Model selector state ──
  const [models, setModels] = useState<Model[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [hours, setHours] = useState(24);

  // ── Generation state ──
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  // ── Saved briefs ──
  const [briefs, setBriefs] = useState<SavedBrief[]>([]);
  const [briefsLoading, setBriefsLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [exportingPdfId, setExportingPdfId] = useState<string | null>(null);

  // ── Schedule state ──
  const [schedule, setSchedule] = useState<BriefSchedule | null>(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const [scheduleSuccess, setScheduleSuccess] = useState(false);
  // Schedule form fields
  const [schedEnabled, setSchedEnabled] = useState(true);
  const [schedModel, setSchedModel] = useState('grok-3-mini');
  const [schedHours, setSchedHours] = useState(24);
  const [schedHour, setSchedHour] = useState(8);

  const briefListRef = useRef<HTMLDivElement>(null);

  // ── Load models ──
  const fetchModels = useCallback(async () => {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const res = await api.get('/briefs/models');
      const list: Model[] = res.data;
      setModels(list);
      const first = list.find((m) => m.available);
      if (first) {
        setSelectedModel(first.id);
        setSchedModel(first.id);
      }
    } catch (err: unknown) {
      setModelsError(err instanceof Error ? err.message : 'Failed to load models');
    } finally {
      setModelsLoading(false);
    }
  }, []);

  // ── Load saved briefs ──
  const fetchBriefs = useCallback(async () => {
    setBriefsLoading(true);
    try {
      const res = await api.get('/briefs/');
      setBriefs(res.data);
    } catch {
      // silently fail
    } finally {
      setBriefsLoading(false);
    }
  }, []);

  // ── Load schedule ──
  const fetchSchedule = useCallback(async () => {
    setScheduleLoading(true);
    try {
      const res = await api.get('/briefs/schedule');
      const s: BriefSchedule | null = res.data.schedule;
      setSchedule(s);
      if (s) {
        setSchedEnabled(s.enabled);
        setSchedModel(s.model_id);
        setSchedHours(s.time_range_hours);
        setSchedHour(s.schedule_hour_utc);
      }
    } catch {
      // silently fail
    } finally {
      setScheduleLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchModels();
    fetchBriefs();
  }, [fetchModels, fetchBriefs]);

  // Load schedule when tab opens
  useEffect(() => {
    if (activeTab === 'schedule') {
      fetchSchedule();
    }
  }, [activeTab, fetchSchedule]);

  // Auto-switch to generate tab when no briefs yet
  useEffect(() => {
    if (!briefsLoading && briefs.length === 0) {
      setActiveTab('generate');
    }
  }, [briefsLoading, briefs.length]);

  async function handleGenerate() {
    if (!selectedModel) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      const res = await api.post('/briefs/generate', { hours, model: selectedModel });
      if (res.data.error) {
        setGenerateError(res.data.error);
      } else {
        const newBrief: SavedBrief = res.data;
        setBriefs((prev) => [newBrief, ...prev]);
        setExpandedId(newBrief.id);
        setActiveTab('history');
        setTimeout(() => {
          briefListRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to generate brief');
      setGenerateError(msg);
    } finally {
      setGenerating(false);
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.delete(`/briefs/${id}`);
      setBriefs((prev) => prev.filter((b) => b.id !== id));
      if (expandedId === id) setExpandedId(null);
    } catch {
      // ignore
    } finally {
      setDeleteConfirmId(null);
    }
  }

  async function handleExportPDF(brief: SavedBrief) {
    setExportingPdfId(brief.id);
    try {
      const response = await api.get(`/briefs/${brief.id}/pdf`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
      const link = document.createElement('a');
      link.href = url;
      const date = new Date(brief.generated_at).toISOString().slice(0, 10).replace(/-/g, '');
      link.setAttribute('download', `orthanc_brief_${date}_${brief.id.slice(0, 8)}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('PDF export failed:', err);
    } finally {
      setExportingPdfId(null);
    }
  }

  async function handleCopy(brief: SavedBrief) {
    try {
      await navigator.clipboard.writeText(brief.summary);
      setCopiedId(brief.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch { /* ignore */ }
  }

  async function handleSaveSchedule() {
    setScheduleSaving(true);
    setScheduleError(null);
    setScheduleSuccess(false);
    try {
      const res = await api.post('/briefs/schedule', {
        enabled: schedEnabled,
        model_id: schedModel,
        time_range_hours: schedHours,
        schedule_hour_utc: schedHour,
      });
      setSchedule(res.data.schedule);
      setScheduleSuccess(true);
      setTimeout(() => setScheduleSuccess(false), 3000);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to save schedule');
      setScheduleError(msg);
    } finally {
      setScheduleSaving(false);
    }
  }

  async function handleDeleteSchedule() {
    try {
      await api.delete('/briefs/schedule');
      setSchedule(null);
      setSchedEnabled(false);
    } catch {
      // ignore
    }
  }

  const selectedModelInfo = models.find((m) => m.id === selectedModel);

  return (
    <div className="briefs-view">
      {/* ── Header ── */}
      <div className="briefs-header">
        <span className="briefs-title">Intelligence Briefs</span>
        <div className="briefs-tabs">
          {(['generate', 'history', 'schedule'] as TabId[]).map((tab) => (
            <button
              key={tab}
              className={`briefs-tab${activeTab === tab ? ' briefs-tab--active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab === 'generate' ? '+ Generate' : tab === 'history' ? '📋 History' : '🕐 Schedule'}
            </button>
          ))}
        </div>
      </div>

      {/* ── GENERATE TAB ── */}
      {activeTab === 'generate' && (
        <div className="briefs-selector-panel">
          <div className="model-section__title">Select Model</div>

          {modelsLoading ? (
            <div className="briefs-loading">
              <span className="spinner" /> Loading models…
            </div>
          ) : modelsError ? (
            <div className="briefs-error">⚠ {modelsError}</div>
          ) : models.length === 0 ? (
            <div className="briefs-error">No models configured</div>
          ) : (
            <div className="model-grid">
              {models.map((model) => (
                <div
                  key={model.id}
                  className={[
                    'model-card',
                    !model.available && 'model-card--disabled',
                    model.available && selectedModel === model.id && 'model-card--selected',
                  ].filter(Boolean).join(' ')}
                  onClick={() => { if (model.available) setSelectedModel(model.id); }}
                >
                  <div>
                    <div className="model-card__name">{model.name}</div>
                    <div className="model-card__provider">{model.provider}</div>
                  </div>
                  {model.description && <div className="model-card__desc">{model.description}</div>}
                  {model.strengths && <div className="model-card__strengths">✦ {model.strengths}</div>}
                  <div className="model-card__meta">
                    <span className="model-card__cost">{model.cost_estimate_per_brief}/brief</span>
                    {model.context_window > 0 && (
                      <span className="model-card__context">{formatCtx(model.context_window)}</span>
                    )}
                  </div>
                  {!model.available && model.requires && (
                    <div className="model-card__requires">
                      Requires {model.requires} API key ·{' '}
                      <a href="/settings/credentials" onClick={(e) => { e.stopPropagation(); navigate('/settings/credentials'); }}>
                        Configure
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Controls */}
          <div className="briefs-controls">
            <span className="briefs-controls__label">Time Range</span>
            <div className="briefs-timerange">
              {TIME_OPTIONS.map((opt) => (
                <button
                  key={opt.hours}
                  className={`briefs-timerange__btn${hours === opt.hours ? ' briefs-timerange__btn--active' : ''}`}
                  onClick={() => setHours(opt.hours)}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            {!selectedModel && !modelsLoading && (
              <span className="briefs-no-model">⚠ Select a model above</span>
            )}

            <button
              className="btn btn-primary briefs-controls__generate"
              disabled={!selectedModel || generating || modelsLoading}
              onClick={handleGenerate}
            >
              {generating ? (
                <><span className="spinner spinner-sm" /> Analyzing {hours}h of posts…</>
              ) : (
                '▶ Generate Brief'
              )}
            </button>
          </div>

          {generating && (
            <div className="briefs-generating">
              <span className="spinner" />
              <div>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Analyzing posts…</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                  Using {selectedModelInfo?.name ?? selectedModel} · Last {hours}h
                </div>
              </div>
            </div>
          )}

          {generateError && <div className="briefs-error">⚠ {generateError}</div>}
        </div>
      )}

      {/* ── HISTORY TAB ── */}
      {activeTab === 'history' && (
        <div className="briefs-history" ref={briefListRef}>
          {briefsLoading ? (
            <div className="briefs-loading">
              <span className="spinner" /> Loading briefs…
            </div>
          ) : briefs.length === 0 ? (
            <div className="briefs-empty">
              <div className="briefs-empty__icon">📋</div>
              <div style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>No briefs generated yet</div>
              <div style={{ fontSize: 12, maxWidth: 360 }}>
                Generate your first intelligence brief above — AI will synthesize patterns across your collected feed data.
              </div>
              <button
                className="btn btn-primary"
                style={{ marginTop: 8 }}
                onClick={() => setActiveTab('generate')}
              >
                ▶ Generate Brief
              </button>
            </div>
          ) : (
            briefs.map((brief) => {
              const isExpanded = expandedId === brief.id;
              const isDeleteConfirm = deleteConfirmId === brief.id;
              const hrs = briefHours(brief);

              return (
                <div
                  key={brief.id}
                  className={`brief-card${isExpanded ? ' brief-card--expanded' : ''}`}
                >
                  <div
                    className="brief-card__header"
                    onClick={() => setExpandedId(isExpanded ? null : brief.id)}
                  >
                    <div className="brief-card__header-left">
                      <span className="brief-card__date">{formatDateTime(brief.generated_at)}</span>
                      <span className="brief-card__model">{brief.model_name ?? brief.model}</span>
                      {brief.cost_estimate && (
                        <span className="brief-card__cost">{brief.cost_estimate}</span>
                      )}
                    </div>
                    <div className="brief-card__header-right">
                      <span className="brief-card__stats">
                        {brief.post_count ?? 0} posts · {hrs}h
                      </span>
                      <span className="brief-card__chevron">{isExpanded ? '▲' : '▼'}</span>
                    </div>
                  </div>

                  {!isExpanded && (
                    <div className="brief-card__preview" onClick={() => setExpandedId(brief.id)}>
                      <span className="brief-card__headline">{extractBriefTitle(brief)}</span>
                      {brief.summary && (
                        <span className="brief-card__preview-text">
                          {getPreview(brief.summary)}
                        </span>
                      )}
                    </div>
                  )}

                  {isExpanded && (
                    <div className="brief-card__body">
                      <div className="brief-meta">
                        <div className="brief-meta__item">
                          <span className="brief-meta__label">Model</span>
                          <span className="brief-meta__value">{brief.model_name ?? brief.model}</span>
                        </div>
                        <div className="brief-meta__item">
                          <span className="brief-meta__label">Posts</span>
                          <span className="brief-meta__value">{brief.post_count ?? 0}</span>
                        </div>
                        <div className="brief-meta__item">
                          <span className="brief-meta__label">Range</span>
                          <span className="brief-meta__value">{hrs}h</span>
                        </div>
                        {brief.cost_estimate && (
                          <div className="brief-meta__item">
                            <span className="brief-meta__label">Cost</span>
                            <span className="brief-meta__value">{brief.cost_estimate}</span>
                          </div>
                        )}
                        <div className="brief-meta__actions">
                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleCopy(brief)}
                          >
                            {copiedId === brief.id ? '✓ Copied' : '⎘ Copy'}
                          </button>

                          <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleExportPDF(brief)}
                            disabled={exportingPdfId === brief.id}
                            title="Export as PDF intelligence report"
                          >
                            {exportingPdfId === brief.id ? (
                              <><span className="spinner spinner-sm" /> Exporting…</>
                            ) : (
                              '📄 PDF'
                            )}
                          </button>

                          {isDeleteConfirm ? (
                            <>
                              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Delete?</span>
                              <button className="btn btn-danger btn-sm" onClick={() => handleDelete(brief.id)}>
                                Confirm
                              </button>
                              <button className="btn btn-secondary btn-sm" onClick={() => setDeleteConfirmId(null)}>
                                Cancel
                              </button>
                            </>
                          ) : (
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => setDeleteConfirmId(brief.id)}
                            >
                              🗑 Delete
                            </button>
                          )}
                        </div>
                      </div>

                      <div className="brief-output">
                        {renderBriefContent(brief.summary || 'No content.', navigate)}
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}

      {/* ── SCHEDULE TAB ── */}
      {activeTab === 'schedule' && (
        <div className="briefs-schedule-panel">
          {scheduleLoading ? (
            <div className="briefs-loading"><span className="spinner" /> Loading schedule…</div>
          ) : (
            <>
              {/* Current status */}
              {schedule && schedule.enabled && (
                <div className="briefs-schedule-status">
                  <span className="briefs-schedule-status__dot briefs-schedule-status__dot--active" />
                  <span>
                    Next brief at: <strong>{nextScheduledTime(schedule.schedule_hour_utc)}</strong>
                  </span>
                  {schedule.last_generated && (
                    <span className="briefs-schedule-status__last">
                      · Last generated {formatDateTime(schedule.last_generated)}
                    </span>
                  )}
                </div>
              )}
              {schedule && !schedule.enabled && (
                <div className="briefs-schedule-status briefs-schedule-status--disabled">
                  <span className="briefs-schedule-status__dot" />
                  <span>Scheduled briefs are disabled</span>
                </div>
              )}
              {!schedule && (
                <div className="briefs-schedule-status briefs-schedule-status--none">
                  <span className="briefs-schedule-status__dot" />
                  <span>No schedule configured</span>
                </div>
              )}

              {/* Schedule form */}
              <div className="briefs-schedule-form">
                <div className="briefs-schedule-form__title">Configure Daily Brief</div>

                {/* Enable toggle */}
                <div className="briefs-schedule-row">
                  <label className="briefs-schedule-label">Enable</label>
                  <label className="briefs-toggle">
                    <input
                      type="checkbox"
                      checked={schedEnabled}
                      onChange={(e) => setSchedEnabled(e.target.checked)}
                    />
                    <span className="briefs-toggle__track" />
                  </label>
                </div>

                {/* Model selector */}
                <div className="briefs-schedule-row">
                  <label className="briefs-schedule-label">Model</label>
                  <select
                    className="briefs-schedule-select"
                    value={schedModel}
                    onChange={(e) => setSchedModel(e.target.value)}
                    disabled={!schedEnabled}
                  >
                    {modelsLoading ? (
                      <option>Loading…</option>
                    ) : (
                      models.map((m) => (
                        <option key={m.id} value={m.id} disabled={!m.available}>
                          {m.name}{!m.available ? ' (no key)' : ''}
                        </option>
                      ))
                    )}
                  </select>
                </div>

                {/* Time range */}
                <div className="briefs-schedule-row">
                  <label className="briefs-schedule-label">Time Range</label>
                  <div className="briefs-timerange">
                    {TIME_OPTIONS.map((opt) => (
                      <button
                        key={opt.hours}
                        className={`briefs-timerange__btn${schedHours === opt.hours ? ' briefs-timerange__btn--active' : ''}`}
                        onClick={() => setSchedHours(opt.hours)}
                        disabled={!schedEnabled}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Hour of day */}
                <div className="briefs-schedule-row">
                  <label className="briefs-schedule-label">Run at (UTC)</label>
                  <select
                    className="briefs-schedule-select briefs-schedule-select--narrow"
                    value={schedHour}
                    onChange={(e) => setSchedHour(Number(e.target.value))}
                    disabled={!schedEnabled}
                  >
                    {HOUR_OPTIONS.map((h) => (
                      <option key={h} value={h}>
                        {String(h).padStart(2, '0')}:00 UTC
                      </option>
                    ))}
                  </select>
                </div>

                {/* Save / Delete */}
                <div className="briefs-schedule-actions">
                  <button
                    className="btn btn-primary"
                    onClick={handleSaveSchedule}
                    disabled={scheduleSaving}
                  >
                    {scheduleSaving ? <><span className="spinner spinner-sm" /> Saving…</> : '✓ Save Schedule'}
                  </button>
                  {schedule && (
                    <button className="btn btn-secondary" onClick={handleDeleteSchedule}>
                      🗑 Remove Schedule
                    </button>
                  )}
                </div>

                {scheduleError && <div className="briefs-error">⚠ {scheduleError}</div>}
                {scheduleSuccess && (
                  <div className="briefs-success">✓ Schedule saved. Briefs will generate automatically.</div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

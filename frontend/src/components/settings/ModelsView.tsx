import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../../services/api';

/* ── Types ──────────────────────────────────────────────── */

interface Provider {
  name: string;
  status: 'connected' | 'disconnected' | 'not_configured';
  model_count: number;
}

type ProviderApiRow = Partial<Provider> & {
  name?: string;
  type?: string;
  base_url?: string | null;
};

type ProvidersApiResponse = ProviderApiRow[] | {
  providers?: ProviderApiRow[];
  count?: number;
};

interface ModelInfo {
  id: string;
  name?: string;
  provider?: string;
}

type TaskAssignments = Record<string, string>;

type TaskAssignmentsApiResponse = TaskAssignments | {
  tasks?: Record<string, { task?: string; model?: string; overridden?: boolean }>;
};

type ModelsApiResponse = ModelInfo[] | {
  models?: ModelInfo[];
  count?: number;
};

interface UsageData {
  total_calls: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number | null;
  by_task: Record<string, number>;
  by_model: Record<string, number>;
}

/* ── Constants ──────────────────────────────────────────── */

const TASK_LABELS: Record<string, string> = {
  brief: 'Intelligence Briefs',
  stance_classification: 'Stance Classification',
  translation: 'Translation',
  embedding: 'Embeddings',
  summarisation: 'Summarisation',
  entity_enrichment: 'Entity Enrichment',
  image_analysis: 'Image Analysis',
  narrative_title: 'Narrative Titles',
};

const PROVIDER_LABELS: Record<string, string> = {
  openrouter: 'OpenRouter',
  xai: 'xAI',
  ollama: 'Ollama',
  local: 'Local (OpenAI)',
  builtin: 'Built-in',
};

/* ── Helpers ────────────────────────────────────────────── */

function fmt(n: number): string {
  return n.toLocaleString('en-US');
}

function fmtCost(n: number | null | undefined): string {
  if (typeof n !== 'number' || Number.isNaN(n)) return '—';
  return `$${n.toFixed(2)}`;
}

function guessProvider(modelId: string): string {
  if (!modelId) return '—';
  if (modelId.includes('grok')) return 'xAI';
  if (modelId.includes('gpt') || modelId.includes('openai')) return 'OpenRouter';
  if (modelId.includes('claude')) return 'OpenRouter';
  if (modelId.includes('hash') || modelId.includes('local')) return 'Built-in';
  return '—';
}

function normalizeProviders(data: ProvidersApiResponse): Provider[] {
  const rows = Array.isArray(data) ? data : Array.isArray(data?.providers) ? data.providers : [];
  return rows
    .filter((row): row is ProviderApiRow & { name: string } => typeof row?.name === 'string' && row.name.length > 0)
    .map((row) => ({
      name: row.name,
      status: row.status === 'connected' || row.status === 'disconnected' || row.status === 'not_configured'
        ? row.status
        : 'connected',
      model_count: typeof row.model_count === 'number' ? row.model_count : 0,
    }));
}

function normalizeModels(data: ModelsApiResponse): ModelInfo[] {
  return Array.isArray(data) ? data : Array.isArray(data?.models) ? data.models : [];
}

function normalizeTasks(data: TaskAssignmentsApiResponse): TaskAssignments {
  if (!data || Array.isArray(data)) return {};
  if ('tasks' in data && data.tasks && typeof data.tasks === 'object') {
    const out: TaskAssignments = {};
    Object.entries(data.tasks).forEach(([taskKey, taskInfo]) => {
      out[taskKey] = taskInfo?.model ?? '';
    });
    return out;
  }
  return Object.fromEntries(
    Object.entries(data).map(([k, v]) => [k, typeof v === 'string' ? v : '']),
  );
}

/* ── Section 1: Providers ───────────────────────────────── */

function ProvidersSection() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [testResults, setTestResults] = useState<Record<string, 'testing' | 'ok' | 'fail'>>({});

  const fetchProviders = useCallback(async () => {
    try {
      setError('');
      const { data } = await api.get<ProvidersApiResponse>('/models/providers');
      setProviders(normalizeProviders(data));
    } catch {
      setError('Failed to load provider status.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchProviders(); }, [fetchProviders]);

  const handleTest = async (name: string) => {
    setTestResults((r) => ({ ...r, [name]: 'testing' }));
    try {
      await api.post(`/models/providers/${name}/test`);
      setTestResults((r) => ({ ...r, [name]: 'ok' }));
    } catch {
      setTestResults((r) => ({ ...r, [name]: 'fail' }));
    }
    // Auto-clear after 4s
    setTimeout(() => {
      setTestResults((r) => {
        const copy = { ...r };
        delete copy[name];
        return copy;
      });
    }, 4000);
  };

  return (
    <div className="models-section">
      <div className="models-section-title">Configured Providers</div>
      <div className="models-card">
        {error && <div className="models-error" style={{ margin: '12px' }}>{error}</div>}
        {loading ? (
          <div className="models-loading">Loading providers…</div>
        ) : providers.length === 0 ? (
          <div className="models-empty">
            No providers configured.{' '}
            <Link to="/settings/credentials">Set up credentials →</Link>
          </div>
        ) : (
          <table className="models-table">
            <thead>
              <tr>
                <th>Provider</th>
                <th>Status</th>
                <th>Models</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {providers.map((p) => {
                const testResult = testResults[p.name];
                const configured = p.status !== 'not_configured';
                return (
                  <tr key={p.name}>
                    <td>
                      <span className="models-provider-name">
                        <span
                          className={`models-status-dot models-status-dot--${p.status}`}
                        />
                        {PROVIDER_LABELS[p.name] ?? p.name}
                      </span>
                    </td>
                    <td>
                      <span className={`models-status-label models-status-label--${p.status}`}>
                        {p.status === 'connected'
                          ? 'Connected'
                          : p.status === 'disconnected'
                          ? 'Disconnected'
                          : 'Not configured'}
                      </span>
                    </td>
                    <td>
                      <span className="models-count">
                        {p.model_count > 0 ? fmt(p.model_count) : '—'}
                      </span>
                    </td>
                    <td>
                      {configured ? (
                        testResult === 'testing' ? (
                          <button className="models-btn" disabled>Testing…</button>
                        ) : testResult === 'ok' ? (
                          <button className="models-btn models-btn--success">✅ OK</button>
                        ) : testResult === 'fail' ? (
                          <button className="models-btn models-btn--error">❌ Failed</button>
                        ) : (
                          <button
                            className="models-btn models-btn--primary"
                            onClick={() => handleTest(p.name)}
                          >
                            Test
                          </button>
                        )
                      ) : (
                        <Link to="/settings/credentials" className="models-btn">
                          Setup →
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/* ── Section 2: Task Assignments ────────────────────────── */

function TasksSection() {
  const [tasks, setTasks] = useState<TaskAssignments>({});
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saveStates, setSaveStates] = useState<Record<string, 'saving' | 'saved' | 'error'>>({});

  const fetchData = useCallback(async () => {
    try {
      setError('');
      const [tasksRes, modelsRes] = await Promise.all([
        api.get<TaskAssignmentsApiResponse>('/models/tasks'),
        api.get<ModelsApiResponse>('/models/'),
      ]);
      setTasks(normalizeTasks(tasksRes.data));
      setModels(normalizeModels(modelsRes.data));
    } catch {
      setError('Failed to load task assignments.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleChange = async (taskKey: string, modelId: string) => {
    setTasks((t) => ({ ...t, [taskKey]: modelId }));
    setSaveStates((s) => ({ ...s, [taskKey]: 'saving' }));
    try {
      await api.post(`/models/tasks/${taskKey}`, { model_id: modelId });
      setSaveStates((s) => ({ ...s, [taskKey]: 'saved' }));
      setTimeout(() => {
        setSaveStates((s) => {
          const copy = { ...s };
          delete copy[taskKey];
          return copy;
        });
      }, 2000);
    } catch {
      setSaveStates((s) => ({ ...s, [taskKey]: 'error' }));
    }
  };

  const taskKeys = Object.keys(TASK_LABELS);

  return (
    <div className="models-section">
      <div className="models-section-title">Task Assignments</div>
      <div className="models-card">
        {error && <div className="models-error" style={{ margin: '12px' }}>{error}</div>}
        {loading ? (
          <div className="models-loading">Loading assignments…</div>
        ) : (
          <table className="models-table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Model</th>
                <th>Provider</th>
              </tr>
            </thead>
            <tbody>
              {taskKeys.map((key) => {
                const currentModel = tasks[key] ?? '';
                const saveState = saveStates[key];
                const providerGuess = guessProvider(currentModel);

                return (
                  <tr key={key}>
                    <td style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                      {TASK_LABELS[key]}
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <select
                          className="models-select"
                          value={currentModel}
                          onChange={(e) => handleChange(key, e.target.value)}
                          disabled={models.length === 0}
                        >
                          {currentModel && !models.find((m) => m.id === currentModel) && (
                            <option value={currentModel}>{currentModel}</option>
                          )}
                          {models.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name ?? m.id}
                            </option>
                          ))}
                          {models.length === 0 && (
                            <option value="">No models available</option>
                          )}
                        </select>
                        {saveState === 'saving' && (
                          <span className="models-save-indicator models-save-indicator--saving">saving…</span>
                        )}
                        {saveState === 'saved' && (
                          <span className="models-save-indicator models-save-indicator--saved">✓</span>
                        )}
                        {saveState === 'error' && (
                          <span className="models-save-indicator models-save-indicator--error">✕ failed</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className="models-provider-badge">{providerGuess}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

/* ── Section 3: Usage ───────────────────────────────────── */

function UsageSection() {
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchUsage = useCallback(async () => {
    try {
      setError('');
      const { data } = await api.get<UsageData>('/models/usage', { params: { hours: 24 } });
      setUsage(data);
    } catch {
      setError('Failed to load usage statistics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsage(); }, [fetchUsage]);

  const byTaskEntries = usage
    ? Object.entries(usage.by_task ?? {}).sort(([, a], [, b]) => b - a)
    : [];

  const maxCalls = byTaskEntries.length > 0 ? byTaskEntries[0][1] : 1;

  return (
    <div className="models-section">
      <div className="models-section-title">Usage (Last 24h)</div>
      <div className="models-card">
        {error && <div className="models-error" style={{ margin: '12px' }}>{error}</div>}
        {loading ? (
          <div className="models-loading">Loading usage…</div>
        ) : !usage ? (
          <div className="models-empty">No usage data available.</div>
        ) : (
          <>
            <div className="models-usage-summary">
              <div className="models-usage-stat">
                <span className="models-usage-stat-label">Total Calls</span>
                <span className="models-usage-stat-value">{fmt(usage.total_calls)}</span>
              </div>
              <div className="models-usage-stat">
                <span className="models-usage-stat-label">Tokens In</span>
                <span className="models-usage-stat-value">{fmt(usage.total_tokens_in)}</span>
              </div>
              <div className="models-usage-stat">
                <span className="models-usage-stat-label">Tokens Out</span>
                <span className="models-usage-stat-value">{fmt(usage.total_tokens_out)}</span>
              </div>
              <div className="models-usage-stat">
                <span className="models-usage-stat-label">Est. Cost</span>
                <span className="models-usage-stat-value models-usage-stat-value--cost">
                  {fmtCost(usage.total_cost_usd)}
                </span>
              </div>
            </div>

            {byTaskEntries.length > 0 && (
              <div className="models-usage-bars">
                <div className="models-usage-bars-title">By Task</div>
                {byTaskEntries.map(([taskKey, calls]) => {
                  const pct = maxCalls > 0 ? (calls / maxCalls) * 100 : 0;
                  const label = TASK_LABELS[taskKey] ?? taskKey;
                  return (
                    <div key={taskKey} className="models-bar-row">
                      <span className="models-bar-label" title={label}>{label}</span>
                      <div className="models-bar-track">
                        <div
                          className="models-bar-fill"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="models-bar-count">{fmt(calls)} calls</span>
                    </div>
                  );
                })}
              </div>
            )}

            {byTaskEntries.length === 0 && (
              <div className="models-empty">No task usage in the last 24 hours.</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ── Main view ──────────────────────────────────────────── */

export function ModelsView() {
  return (
    <div className="models-page">
      <ProvidersSection />
      <TasksSection />
      <UsageSection />
    </div>
  );
}

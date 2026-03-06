import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { LoadingSpinner } from '../common/LoadingSpinner';
import '../../styles/setup.css';

// ── Types ────────────────────────────────────────────────

interface AddedSource {
  id: string | number;
  display_name: string;
  url: string;
}

interface CredForm {
  provider: string;
  values: Record<string, string>;
  password: string;
}

// ── Constants ────────────────────────────────────────────

const RSS_SUGGESTIONS = [
  { name: 'BBC World News', url: 'http://feeds.bbci.co.uk/news/world/rss.xml' },
  { name: 'Al Jazeera', url: 'https://www.aljazeera.com/xml/rss/all.xml' },
  { name: 'USGS Earthquakes', url: 'https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.atom' },
  { name: 'Reuters', url: 'https://www.reutersagency.com/feed/' },
];

const WIZARD_PROVIDERS = [
  {
    id: 'x',
    label: 'X / Twitter',
    icon: '✕',
    description: 'Monitor Twitter accounts and hashtags via xAI API',
    fields: [{ key: 'api_key', label: 'xAI API Key', placeholder: 'xai-...', type: 'password' as const }],
  },
  {
    id: 'telegram',
    label: 'Telegram',
    icon: '✈',
    description: 'Monitor Telegram channels and groups',
    fields: [
      { key: 'api_id', label: 'API ID', placeholder: '12345678', type: 'text' as const },
      { key: 'api_hash', label: 'API Hash', placeholder: 'abc123def456...', type: 'password' as const },
    ],
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    icon: '🤖',
    description: 'AI-powered intelligence briefs (Claude, GPT-4, Gemini)',
    fields: [{ key: 'api_key', label: 'API Key', placeholder: 'sk-or-...', type: 'password' as const }],
  },
  {
    id: 'shodan',
    label: 'Shodan',
    icon: '🔍',
    description: 'Scan for exposed devices and infrastructure',
    fields: [{ key: 'api_key', label: 'API Key', placeholder: 'aBcD1234...', type: 'password' as const }],
  },
];

// ── Step Indicator ────────────────────────────────────────

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="setup-steps">
      {Array.from({ length: total }, (_, i) => {
        const stepNum = i + 1;
        const isDone = stepNum < current;
        const isActive = stepNum === current;
        return (
          <div key={stepNum} className="setup-step-item">
            <div
              className={`setup-step-circle${isDone ? ' done' : isActive ? ' active' : ''}`}
              title={`Step ${stepNum}`}
            >
              {isDone ? '✓' : stepNum}
            </div>
            {i < total - 1 && (
              <div className={`setup-step-line${isDone ? ' done' : ''}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Step 1: Welcome ───────────────────────────────────────

function StepWelcome({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  return (
    <div className="setup-content">
      <div>
        <div style={{ textAlign: 'center', fontSize: '48px', marginBottom: '16px' }}>▣</div>
        <h1 className="setup-title">Welcome to Orthanc</h1>
        <p className="setup-subtitle" style={{ marginTop: '10px' }}>
          Let's get your intelligence feeds running.<br />
          This takes about 60 seconds.
        </p>
      </div>

      <div className="setup-footer">
        <div className="setup-footer-buttons">
          <button className="btn btn-primary" onClick={onNext} style={{ minWidth: '160px' }}>
            Get Started →
          </button>
        </div>
        <button className="setup-skip-link" onClick={onSkip}>
          Skip setup, take me to the dashboard
        </button>
      </div>
    </div>
  );
}

// ── Step 2: Sources ───────────────────────────────────────

function StepSources({
  addedSources,
  onSourceAdded,
  onNext,
  onBack,
}: {
  addedSources: AddedSource[];
  onSourceAdded: (source: AddedSource) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const [customUrl, setCustomUrl] = useState('');
  const [customName, setCustomName] = useState('');
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState('');

  const isAdded = (url: string) => addedSources.some((s) => s.url === url);

  const addSource = async (url: string, name: string) => {
    if (isAdded(url)) return;
    setAdding(url);
    setError('');
    try {
      const res = await api.post('/sources/', {
        type: 'rss',
        handle: url,
        display_name: name,
        config_json: {},
      });
      onSourceAdded({ id: res.data.id, display_name: name, url });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to add source. Check the URL and try again.');
    } finally {
      setAdding(null);
    }
  };

  const handleCustomAdd = async () => {
    const url = customUrl.trim();
    const name = customName.trim() || 'Custom RSS Feed';
    if (!url) { setError('Please enter a URL.'); return; }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      setError('URL must start with http:// or https://');
      return;
    }
    await addSource(url, name);
    if (!error) {
      setCustomUrl('');
      setCustomName('');
    }
  };

  return (
    <div className="setup-content">
      <div>
        <h2 className="setup-title">Add Your First Source</h2>
        <p className="setup-subtitle" style={{ marginTop: '8px' }}>
          Start with an RSS feed — no API credentials needed.
        </p>
      </div>

      {error && <div className="setup-error">{error}</div>}

      <div className="setup-suggestions">
        <div className="setup-suggestions-label">Quick-add popular feeds</div>
        {RSS_SUGGESTIONS.map((s) => {
          const added = isAdded(s.url);
          const loading = adding === s.url;
          return (
            <div
              key={s.url}
              className={`setup-suggestion-card${added ? ' added' : ''}`}
              onClick={() => !added && !loading && addSource(s.url, s.name)}
            >
              <div className="setup-suggestion-info">
                <span className="setup-suggestion-name">{s.name}</span>
                <span className="setup-suggestion-url">{s.url}</span>
              </div>
              <button
                className={`setup-suggestion-action${added ? ' added' : ''}`}
                disabled={added || !!loading}
                onClick={(e) => { e.stopPropagation(); if (!added && !loading) addSource(s.url, s.name); }}
              >
                {loading ? '…' : added ? '✓ Added' : '+ Add'}
              </button>
            </div>
          );
        })}
      </div>

      <div className="setup-custom-url">
        <div className="setup-custom-url-label">Or add a custom RSS/Atom URL</div>
        <div className="setup-custom-url-row">
          <input
            className="input"
            type="text"
            placeholder="https://example.com/feed.xml"
            value={customUrl}
            onChange={(e) => setCustomUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCustomAdd()}
          />
        </div>
        <div className="setup-custom-url-row">
          <input
            className="input"
            type="text"
            placeholder="Display name (optional)"
            value={customName}
            onChange={(e) => setCustomName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleCustomAdd()}
          />
          <button
            className="btn btn-secondary"
            onClick={handleCustomAdd}
            disabled={!!adding}
            style={{ flexShrink: 0 }}
          >
            {adding && adding !== RSS_SUGGESTIONS.find(s => s.url === adding)?.url ? <LoadingSpinner size="sm" /> : 'Add'}
          </button>
        </div>
      </div>

      {addedSources.length > 0 && (
        <div className="setup-added-list">
          {addedSources.map((s) => (
            <div key={s.url} className="setup-added-item">
              <span className="setup-added-icon">✓</span>
              <span className="setup-added-name">{s.display_name}</span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                rss
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="setup-footer">
        <div className="setup-footer-buttons">
          <button className="btn btn-secondary" onClick={onBack}>← Back</button>
          <button
            className="btn btn-primary"
            onClick={onNext}
            disabled={addedSources.length === 0}
            style={{ minWidth: '120px' }}
          >
            Continue →
          </button>
        </div>
        {addedSources.length === 0 && (
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            Add at least one source to continue
          </span>
        )}
      </div>
    </div>
  );
}

// ── Step 3: Credentials ───────────────────────────────────

function ProviderCard({
  provider,
  configured,
  onConfigured,
}: {
  provider: typeof WIZARD_PROVIDERS[0];
  configured: boolean;
  onConfigured: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSave = async () => {
    if (!password.trim()) { setError('Password required.'); return; }
    for (const f of provider.fields) {
      if (!values[f.key]?.trim()) { setError(`${f.label} is required.`); return; }
    }
    setError('');
    setSaving(true);
    try {
      await api.post('/credentials/', {
        provider: provider.id,
        api_keys: { _password: password, ...values },
      });
      setOpen(false);
      onConfigured();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to save credentials.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={`setup-provider-card${configured ? ' configured' : ''}`}>
      <div className="setup-provider-header">
        <span className="setup-provider-icon">{provider.icon}</span>
        <span className="setup-provider-name">{provider.label}</span>
      </div>
      <p className="setup-provider-desc">{provider.description}</p>

      {configured ? (
        <div className="setup-provider-status">✓ Configured</div>
      ) : (
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? 'Cancel' : 'Configure'}
        </button>
      )}

      {open && !configured && (
        <div className="setup-cred-form">
          {error && <div className="setup-error">{error}</div>}
          {provider.fields.map((f) => (
            <input
              key={f.key}
              className="input"
              type={f.type}
              placeholder={f.label + ' — ' + f.placeholder}
              value={values[f.key] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
            />
          ))}
          <input
            className="input"
            type="password"
            placeholder="Your login password (for encryption)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
            {saving ? <><LoadingSpinner size="sm" /> Saving...</> : 'Save'}
          </button>
        </div>
      )}
    </div>
  );
}

function StepCredentials({
  configuredProviders,
  onProviderConfigured,
  onNext,
  onSkip,
  onBack,
}: {
  configuredProviders: Set<string>;
  onProviderConfigured: (id: string) => void;
  onNext: () => void;
  onSkip: () => void;
  onBack: () => void;
}) {
  return (
    <div className="setup-content">
      <div>
        <h2 className="setup-title">Unlock More Data Sources</h2>
        <p className="setup-subtitle" style={{ marginTop: '8px' }}>
          Optional — configure API credentials to enable additional collectors.<br />
          <span style={{ fontSize: '12px' }}>You can always add these later in Settings → Credentials.</span>
        </p>
      </div>

      <div className="setup-providers-grid">
        {WIZARD_PROVIDERS.map((p) => (
          <ProviderCard
            key={p.id}
            provider={p}
            configured={configuredProviders.has(p.id)}
            onConfigured={() => onProviderConfigured(p.id)}
          />
        ))}
      </div>

      <div className="setup-footer">
        <div className="setup-footer-buttons">
          <button className="btn btn-secondary" onClick={onBack}>← Back</button>
          <button className="btn btn-primary" onClick={onNext} style={{ minWidth: '120px' }}>
            {configuredProviders.size > 0 ? 'Continue →' : 'Skip →'}
          </button>
        </div>
        <button className="setup-skip-link" onClick={onSkip}>
          Skip this step
        </button>
      </div>
    </div>
  );
}

// ── Step 4: Done ──────────────────────────────────────────

function StepDone({
  addedSources,
  configuredProviders,
}: {
  addedSources: AddedSource[];
  configuredProviders: Set<string>;
}) {
  const navigate = useNavigate();

  return (
    <div className="setup-content">
      <div>
        <div className="setup-done-checkmark">🎯</div>
        <h2 className="setup-title">You're all set!</h2>
        <p className="setup-subtitle" style={{ marginTop: '8px' }}>
          Your collectors are now running.
        </p>
      </div>

      <div className="setup-done-items">
        {addedSources.length > 0 && (
          <div className="setup-done-item">
            <span className="setup-done-check">✓</span>
            <span>{addedSources.length} RSS feed{addedSources.length !== 1 ? 's' : ''} active</span>
          </div>
        )}
        {configuredProviders.size > 0 && (
          <>
            {Array.from(configuredProviders).map((id) => {
              const p = WIZARD_PROVIDERS.find((x) => x.id === id);
              return p ? (
                <div key={id} className="setup-done-item">
                  <span className="setup-done-check">✓</span>
                  <span>{p.icon} {p.label} configured</span>
                </div>
              ) : null;
            })}
          </>
        )}
      </div>

      <div className="setup-tip">
        💡 Data will start appearing in your feed within a few minutes as sources are polled.
        Check the Feed view or Dashboard for incoming intelligence.
      </div>

      <div className="setup-footer">
        <div className="setup-footer-buttons">
          <button
            className="btn btn-primary"
            onClick={() => navigate('/dashboard')}
            style={{ minWidth: '160px' }}
          >
            Go to Dashboard →
          </button>
        </div>
        <button
          className="setup-alt-link"
          onClick={() => navigate('/map')}
        >
          Explore the Map instead
        </button>
      </div>
    </div>
  );
}

// ── Main Wizard ───────────────────────────────────────────

export function SetupWizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [addedSources, setAddedSources] = useState<AddedSource[]>([]);
  const [configuredProviders, setConfiguredProviders] = useState<Set<string>>(new Set());

  const TOTAL_STEPS = 4;

  const handleSkip = () => {
    localStorage.setItem('wizardDismissed', 'true');
    navigate('/dashboard');
  };

  const handleSourceAdded = (source: AddedSource) => {
    setAddedSources((prev) => {
      if (prev.some((s) => s.url === source.url)) return prev;
      return [...prev, source];
    });
  };

  const handleProviderConfigured = (id: string) => {
    setConfiguredProviders((prev) => new Set([...prev, id]));
  };

  return (
    <div className="setup-page">
      <div className="setup-card">
        <div className="setup-header">
          <div className="setup-logo">▣ Orthanc</div>
        </div>

        <StepIndicator current={step} total={TOTAL_STEPS} />

        {step === 1 && (
          <StepWelcome onNext={() => setStep(2)} onSkip={handleSkip} />
        )}
        {step === 2 && (
          <StepSources
            addedSources={addedSources}
            onSourceAdded={handleSourceAdded}
            onNext={() => setStep(3)}
            onBack={() => setStep(1)}
          />
        )}
        {step === 3 && (
          <StepCredentials
            configuredProviders={configuredProviders}
            onProviderConfigured={handleProviderConfigured}
            onNext={() => { localStorage.setItem('wizardDismissed', 'true'); setStep(4); }}
            onSkip={() => { localStorage.setItem('wizardDismissed', 'true'); setStep(4); }}
            onBack={() => setStep(2)}
          />
        )}
        {step === 4 && (
          <StepDone
            addedSources={addedSources}
            configuredProviders={configuredProviders}
          />
        )}
      </div>
    </div>
  );
}

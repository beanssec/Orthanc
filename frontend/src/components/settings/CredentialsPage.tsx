import { useState, useEffect } from 'react';
import api from '../../services/api';
import { StatusDot } from '../common/StatusDot';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { Modal } from '../common/Modal';
import { ConfirmDialog } from '../common/ConfirmDialog';

interface CredentialStatus {
  provider: string;
  configured: boolean;
  collector_active: boolean;
}

const PROVIDERS = [
  {
    id: 'telegram',
    label: 'Telegram',
    icon: '✈',
    description: 'Monitor Telegram channels and groups for OSINT data.',
    fields: [
      { key: 'api_id', label: 'API ID', placeholder: '12345678', type: 'text' as const },
      { key: 'api_hash', label: 'API Hash', placeholder: 'abc123def456...', type: 'password' as const },
    ],
    guide: {
      title: 'How to get Telegram API credentials',
      steps: [
        'Go to https://my.telegram.org and log in with your phone number',
        'Click "API development tools"',
        'Fill in the form: App title (e.g. "Orthanc"), Short name (e.g. "orthanc"), Platform: Other',
        'Click "Create application"',
        'Copy your API ID (number) and API Hash (hex string)',
        'Enter them here, then go to Settings → Telegram to link your account',
      ],
      note: 'After saving credentials, you still need to authenticate your Telegram account via Settings → Telegram Setup. This sends a code to your Telegram app.',
    },
  },
  {
    id: 'x',
    label: 'X / Twitter (xAI)',
    icon: '✕',
    description: 'Monitor X posts and cashtag ($TICKER) mentions via xAI Grok API.',
    fields: [
      { key: 'api_key', label: 'xAI API Key', placeholder: 'xai-...', type: 'password' as const },
    ],
    guide: {
      title: 'How to get an xAI API key',
      steps: [
        'Go to https://console.x.ai and create an account',
        'Navigate to API Keys section',
        'Create a new API key',
        'Copy the key (starts with xai-...)',
      ],
      note: 'This key is also used for AI intelligence briefs (Grok models) and cashtag monitoring for your portfolio.',
    },
  },
  {
    id: 'openrouter',
    label: 'OpenRouter',
    icon: '🤖',
    description: 'Access multiple AI models (Claude, GPT-4, Gemini, Llama) for intelligence briefs.',
    fields: [
      { key: 'api_key', label: 'API Key', placeholder: 'sk-or-...', type: 'password' as const },
    ],
    guide: {
      title: 'How to get an OpenRouter API key',
      steps: [
        'Go to https://openrouter.ai and create an account',
        'Navigate to Keys → Create Key',
        'Copy your API key (starts with sk-or-...)',
        'Add credits to your account ($5 minimum)',
      ],
      note: 'One key gives access to 7+ AI models for briefs: Claude Sonnet, GPT-4o, Gemini Flash, Llama, Mistral, and more.',
    },
  },
  {
    id: 'shodan',
    label: 'Shodan',
    icon: '🔍',
    description: 'Scan for exposed devices, services, and infrastructure vulnerabilities.',
    fields: [
      { key: 'api_key', label: 'API Key', placeholder: 'aBcD1234...', type: 'password' as const },
    ],
    guide: {
      title: 'How to get a Shodan API key',
      steps: [
        'Go to https://account.shodan.io and create an account',
        'Your API key is shown on the Account page after login',
        'Free tier allows limited queries; paid membership unlocks more',
      ],
      note: 'Shodan monitors internet-facing devices. Add search queries in Settings → Sources after configuring.',
    },
  },
  {
    id: 'discord',
    label: 'Discord',
    icon: '💬',
    description: 'Monitor Discord servers and channels via a bot.',
    fields: [
      { key: 'bot_token', label: 'Bot Token', placeholder: 'MTIz...', type: 'password' as const },
    ],
    guide: {
      title: 'How to create a Discord bot',
      steps: [
        'Go to https://discord.com/developers/applications',
        'Click "New Application", give it a name',
        'Go to Bot → "Add Bot" → confirm',
        'Under Token, click "Copy" to get your bot token',
        'Enable MESSAGE CONTENT INTENT under Privileged Gateway Intents',
        'Go to OAuth2 → URL Generator, select "bot" scope + "Read Messages" permission',
        'Open the generated URL to invite the bot to your server',
      ],
      note: 'The bot must be invited to any server you want to monitor. It only reads messages — it never sends.',
    },
  },
  {
    id: 'ais',
    label: 'AIS (Ship Tracking)',
    icon: '🚢',
    description: 'Real-time vessel tracking via AISStream.io WebSocket feed.',
    fields: [
      { key: 'api_key', label: 'API Key', placeholder: 'your-ais-key...', type: 'password' as const },
    ],
    guide: {
      title: 'How to get an AISStream API key',
      steps: [
        'Go to https://aisstream.io and create a free account',
        'Navigate to your dashboard',
        'Copy your API key',
      ],
      note: 'Free tier provides real-time AIS data for vessel positions. The collector monitors key maritime zones.',
    },
  },
  {
    id: 'mapbox',
    label: 'Mapbox (optional)',
    icon: '🗺',
    description: 'Not required — Orthanc uses free CartoDB tiles by default.',
    fields: [
      { key: 'access_token', label: 'Access Token', placeholder: 'pk.eyJ1...', type: 'password' as const },
    ],
    guide: {
      title: 'Mapbox is optional',
      steps: [
        'Orthanc uses free CartoDB dark-matter tiles — no Mapbox key needed',
        'If you prefer Mapbox styling, go to https://mapbox.com and create an account',
        'Copy your public access token from the account page',
      ],
      note: 'Only needed if you want Mapbox-specific map styles. The default dark map works without any key.',
    },
  },
];

function CredentialModal({
  provider,
  onClose,
  onSave,
}: {
  provider: (typeof PROVIDERS)[0];
  onClose: () => void;
  onSave: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password.trim()) { setError('Password is required for encryption.'); return; }
    for (const f of provider.fields) {
      if (!values[f.key]?.trim()) { setError(`${f.label} is required.`); return; }
    }
    setError('');
    setLoading(true);
    try {
      const api_keys: Record<string, string> = { _password: password, ...values };
      await api.post('/credentials/', { provider: provider.id, api_keys });
      onSave();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to save credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={`Configure ${provider.label}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit as unknown as React.MouseEventHandler} disabled={loading}>
            {loading ? <LoadingSpinner size="sm" /> : null}
            Save
          </button>
        </>
      }
    >
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {error && <div className="error-message">{error}</div>}

        {provider.fields.map((f) => (
          <div className="form-group" key={f.key}>
            <label className="form-label">{f.label}</label>
            <input
              className="input"
              type={f.type}
              placeholder={f.placeholder}
              value={values[f.key] ?? ''}
              onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
            />
          </div>
        ))}

        <div className="form-group">
          <label className="form-label">Your Password (for encryption)</label>
          <input
            className="input"
            type="password"
            placeholder="Your login password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>
      </form>
    </Modal>
  );
}

export function CredentialsPage() {
  const [statuses, setStatuses] = useState<Record<string, CredentialStatus>>({});
  const [loading, setLoading] = useState(true);
  const [configuring, setConfiguring] = useState<(typeof PROVIDERS)[0] | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [showingGuide, setShowingGuide] = useState<string | null>(null);

  const fetchStatuses = async () => {
    try {
      const res = await api.get<CredentialStatus[]>('/credentials/status');
      const map: Record<string, CredentialStatus> = {};
      res.data.forEach((s) => { map[s.provider] = s; });
      setStatuses(map);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStatuses(); }, []);

  const handleDelete = async () => {
    if (!deleting) return;
    try {
      await api.delete(`/credentials/${deleting}`);
      await fetchStatuses();
    } catch {
      // ignore
    } finally {
      setDeleting(null);
    }
  };

  if (loading) return <div style={{ padding: '40px', display: 'flex', justifyContent: 'center' }}><LoadingSpinner size="lg" /></div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div className="banner banner-info">
        🔒 Your API keys are encrypted with your password and stored securely. They are decrypted only while you're logged in.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '12px' }}>
        {PROVIDERS.map((provider) => {
          const status = statuses[provider.id];
          const configured = status?.configured ?? false;
          const active = status?.collector_active ?? false;

          return (
            <div className="card" key={provider.id} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ fontSize: '18px' }}>{provider.icon}</span>
                  <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)' }}>{provider.label}</span>
                </div>
              </div>

              {'description' in provider && (
                <p style={{ fontSize: '11px', color: 'var(--text-muted)', margin: 0, lineHeight: '1.4' }}>
                  {provider.description}
                </p>
              )}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
                  <StatusDot status={configured ? 'active' : 'muted'} />
                  <span style={{ color: configured ? 'var(--success)' : 'var(--text-muted)' }}>
                    {configured ? 'Configured ✓' : 'Not configured'}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px' }}>
                  <StatusDot status={active ? 'active' : 'muted'} />
                  <span style={{ color: active ? 'var(--success)' : 'var(--text-muted)' }}>
                    Collector: {active ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button className="btn btn-primary btn-sm" onClick={() => setConfiguring(provider)}>
                  {configured ? 'Update' : 'Configure'}
                </button>
                {'guide' in provider && (
                  <button className="btn btn-secondary btn-sm" onClick={() => setShowingGuide(showingGuide === provider.id ? null : provider.id)}>
                    {showingGuide === provider.id ? 'Hide Guide' : 'Setup Guide'}
                  </button>
                )}
                {configured && (
                  <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => setDeleting(provider.id)}>
                    Remove
                  </button>
                )}
              </div>

              {showingGuide === provider.id && 'guide' in provider && (
                <div style={{ background: 'var(--color-bg, #0a0e1a)', borderRadius: '6px', padding: '12px', marginTop: '4px', border: '1px solid var(--border, #1f2937)' }}>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '10px' }}>
                    {provider.guide.title}
                  </div>
                  <ol style={{ margin: 0, paddingLeft: '18px', fontSize: '11px', color: 'var(--text-secondary, #d1d5db)', lineHeight: '1.8' }}>
                    {provider.guide.steps.map((step, i) => (
                      <li key={i} style={{ marginBottom: '2px' }}>{step}</li>
                    ))}
                  </ol>
                  {provider.guide.note && (
                    <div style={{ marginTop: '10px', padding: '8px', background: 'rgba(59, 130, 246, 0.1)', borderRadius: '4px', borderLeft: '3px solid var(--accent, #3b82f6)', fontSize: '11px', color: 'var(--text-muted, #9ca3af)', lineHeight: '1.5' }}>
                      💡 {provider.guide.note}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {configuring && (
        <CredentialModal
          provider={configuring}
          onClose={() => setConfiguring(null)}
          onSave={() => { setConfiguring(null); fetchStatuses(); }}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title="Remove Credentials"
          message={`Remove ${PROVIDERS.find(p => p.id === deleting)?.label ?? deleting} credentials? The collector will stop immediately.`}
          confirmLabel="Remove"
          onConfirm={handleDelete}
          onCancel={() => setDeleting(null)}
          danger
        />
      )}
    </div>
  );
}

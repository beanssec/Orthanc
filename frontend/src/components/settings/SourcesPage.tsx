import { useState, useEffect } from 'react';
import api from '../../services/api';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { EmptyState } from '../common/EmptyState';
import { Modal } from '../common/Modal';
import { ConfirmDialog } from '../common/ConfirmDialog';
import { formatDateTime } from '../../utils/dateFormat';

interface Source {
  id: string;
  type: 'telegram' | 'x' | 'rss' | 'reddit' | 'discord' | 'shodan' | 'webhook';
  handle: string;
  display_name: string;
  enabled: boolean;
  last_polled: string | null;
  config_json: Record<string, unknown>;
  download_images: boolean;
  download_videos: boolean;
  max_image_size_mb: number;
  max_video_size_mb: number;
}

const TYPE_COLORS: Record<string, string> = {
  telegram: 'var(--telegram-color)',
  x: 'var(--x-color)',
  rss: 'var(--rss-color)',
  reddit: '#ff4500',
  discord: '#5865f2',
  shodan: '#e11d48',
  webhook: '#8b5cf6',
};

const TYPE_PLACEHOLDERS: Record<string, string> = {
  telegram: '@channelname',
  x: '@username',
  rss: 'https://feeds.example.com/rss',
  reddit: 'r/worldnews',
  discord: 'channel_id (numeric Discord channel ID)',
  shodan: 'webcam country:US',
  webhook: 'my-webhook-source',
};

function SourceModal({
  onClose,
  onSave,
  initial,
}: {
  onClose: () => void;
  onSave: () => void;
  initial?: Source | null;
}) {
  const [type, setType] = useState<string>(initial?.type ?? 'telegram');
  const [handle, setHandle] = useState(initial?.handle ?? '');
  const [displayName, setDisplayName] = useState(initial?.display_name ?? '');
  const [downloadImages, setDownloadImages] = useState(initial?.download_images ?? false);
  const [downloadVideos, setDownloadVideos] = useState(initial?.download_videos ?? false);
  const [maxImageSizeMb, setMaxImageSizeMb] = useState(initial?.max_image_size_mb ?? 10);
  const [maxVideoSizeMb, setMaxVideoSizeMb] = useState(initial?.max_video_size_mb ?? 100);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!handle.trim() || !displayName.trim()) { setError('All fields are required.'); return; }
    setError('');
    setLoading(true);
    try {
      const mediaPayload = (type === 'telegram' || initial?.type === 'telegram') ? {
        download_images: downloadImages,
        download_videos: downloadVideos,
        max_image_size_mb: maxImageSizeMb,
        max_video_size_mb: maxVideoSizeMb,
      } : {};
      if (initial) {
        await api.put(`/sources/${initial.id}`, { display_name: displayName.trim(), ...mediaPayload });
      } else {
        await api.post('/sources/', { type, handle: handle.trim(), display_name: displayName.trim(), config_json: {}, ...mediaPayload });
      }
      onSave();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to save source.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={initial ? 'Edit Source' : 'Add Source'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSubmit as unknown as React.MouseEventHandler} disabled={loading}>
            {loading ? <LoadingSpinner size="sm" /> : null}
            {initial ? 'Update' : 'Add Source'}
          </button>
        </>
      }
    >
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {error && <div className="error-message">{error}</div>}

        {!initial && (
          <div className="form-group">
            <label className="form-label">Type</label>
            <select className="select" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="telegram">Telegram</option>
              <option value="x">X (Twitter)</option>
              <option value="rss">RSS</option>
              <option value="reddit">Reddit</option>
              <option value="discord">Discord</option>
              <option value="shodan">Shodan</option>
              <option value="webhook">Webhook</option>
            </select>
          </div>
        )}

        <div className="form-group">
          <label className="form-label">Handle / URL</label>
          <input
            className="input"
            type="text"
            placeholder={TYPE_PLACEHOLDERS[type] ?? '@channelname'}
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            disabled={!!initial}
          />
        </div>

        <div className="form-group">
          <label className="form-label">Display Name</label>
          <input
            className="input"
            type="text"
            placeholder="e.g. Reuters Breaking News"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
          />
        </div>

        {/* Media download toggles — Telegram only */}
        {(type === 'telegram' || initial?.type === 'telegram') && (
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
              Media Downloads
            </div>

            <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <label className="form-label" style={{ marginBottom: 0 }}>
                📷 Auto-download images
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={downloadImages}
                  onChange={(e) => setDownloadImages(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            {downloadImages && (
              <div className="form-group" style={{ marginBottom: 10 }}>
                <label className="form-label">Max image size (MB)</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={maxImageSizeMb}
                  onChange={(e) => setMaxImageSizeMb(Number(e.target.value))}
                />
              </div>
            )}

            <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <label className="form-label" style={{ marginBottom: 0 }}>
                🎥 Auto-download videos
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={downloadVideos}
                  onChange={(e) => setDownloadVideos(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            </div>

            {downloadVideos && (
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">Max video size (MB)</label>
                <input
                  className="input"
                  type="number"
                  min={10}
                  max={1000}
                  step={10}
                  value={maxVideoSizeMb}
                  onChange={(e) => setMaxVideoSizeMb(Number(e.target.value))}
                />
              </div>
            )}

            <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.4 }}>
              Downloads are opt-in and off by default. Images will be analyzed for AI-generation.
            </p>
          </div>
        )}
      </form>
    </Modal>
  );
}

export function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [editSource, setEditSource] = useState<Source | null>(null);
  const [deleteSource, setDeleteSource] = useState<Source | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const fetchSources = async () => {
    try {
      const res = await api.get('/sources/');
      setSources(res.data);
    } catch {
      setError('Failed to load sources.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchSources(); }, []);

  const handleToggle = async (source: Source) => {
    setTogglingId(source.id);
    try {
      await api.put(`/sources/${source.id}`, { enabled: !source.enabled });
      setSources((prev) => prev.map((s) => s.id === source.id ? { ...s, enabled: !s.enabled } : s));
    } catch {
      // ignore
    } finally {
      setTogglingId(null);
    }
  };

  const handleDelete = async () => {
    if (!deleteSource) return;
    try {
      await api.delete(`/sources/${deleteSource.id}`);
      setSources((prev) => prev.filter((s) => s.id !== deleteSource.id));
    } catch {
      // ignore
    } finally {
      setDeleteSource(null);
    }
  };

  if (loading) return <div style={{ padding: '40px', display: 'flex', justifyContent: 'center' }}><LoadingSpinner size="lg" /></div>;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
        <h2 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Sources ({sources.length})
        </h2>
        <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(true)}>+ Add Source</button>
      </div>

      {error && <div className="error-message" style={{ marginBottom: '12px' }}>{error}</div>}

      {sources.length === 0 ? (
        <EmptyState icon="📡" message="No sources configured" description="Add a Telegram channel, X account, or RSS feed to start collecting data." />
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Handle</th>
                <th>Display Name</th>
                <th>Status</th>
                <th>Last Polled</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.id}>
                  <td>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className="status-dot" style={{ backgroundColor: TYPE_COLORS[source.type] ?? 'var(--text-muted)' }} />
                      <span style={{ textTransform: 'capitalize' }}>{source.type}</span>
                    </span>
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: '12px', color: 'var(--text-primary)' }}>{source.handle}</span>
                  </td>
                  <td style={{ color: 'var(--text-primary)' }}>{source.display_name}</td>
                  <td>
                    <label className="toggle" title={source.enabled ? 'Disable' : 'Enable'}>
                      <input
                        type="checkbox"
                        checked={source.enabled}
                        onChange={() => handleToggle(source)}
                        disabled={togglingId === source.id}
                      />
                      <span className="toggle-slider" />
                    </label>
                  </td>
                  <td>
                    <span className="mono" style={{ fontSize: '11px', color: source.last_polled ? 'var(--text-muted)' : '#f59e0b' }}>
                      {source.last_polled ? formatDateTime(source.last_polled) : 'Never polled'}
                    </span>
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setEditSource(source)} title="Edit">✎</button>
                      <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => setDeleteSource(source)} title="Delete">✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(showAdd || editSource) && (
        <SourceModal
          onClose={() => { setShowAdd(false); setEditSource(null); }}
          onSave={() => { setShowAdd(false); setEditSource(null); fetchSources(); }}
          initial={editSource}
        />
      )}

      {deleteSource && (
        <ConfirmDialog
          title="Delete Source"
          message={`Delete "${deleteSource.display_name}"? This will stop collecting data from this source.`}
          confirmLabel="Delete"
          onConfirm={handleDelete}
          onCancel={() => setDeleteSource(null)}
          danger
        />
      )}
    </div>
  );
}

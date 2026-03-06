import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import '../../styles/collaboration.css';

interface Bookmark {
  id: string;
  user_id: string;
  target_type: string;
  target_id: string;
  label: string | null;
  created_at: string;
}

const TYPE_ICONS: Record<string, string> = {
  entity: '🔗',
  post: '📰',
  event: '📍',
  brief: '📋',
};

const TYPE_LABELS: Record<string, string> = {
  entity: 'Entities',
  post: 'Posts',
  event: 'Events',
  brief: 'Briefs',
};

export function BookmarksView() {
  const navigate = useNavigate();
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string | null>(null);

  useEffect(() => {
    api.get('/bookmarks/')
      .then(res => setBookmarks(res.data as Bookmark[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const removeBookmark = async (bm: Bookmark) => {
    try {
      await api.delete(`/bookmarks/${bm.target_type}/${bm.target_id}`);
      setBookmarks(prev => prev.filter(b => b.id !== bm.id));
    } catch { /* ignore */ }
  };

  const handleNavigate = (bm: Bookmark) => {
    switch (bm.target_type) {
      case 'entity':
        navigate(`/entities/${bm.target_id}`);
        break;
      case 'post':
        navigate(`/feed?post=${bm.target_id}`);
        break;
      case 'brief':
        navigate(`/briefs`);
        break;
      default:
        break;
    }
  };

  const filtered = filter ? bookmarks.filter(b => b.target_type === filter) : bookmarks;

  // Group by type
  const groups: Record<string, Bookmark[]> = {};
  for (const bm of filtered) {
    if (!groups[bm.target_type]) groups[bm.target_type] = [];
    groups[bm.target_type].push(bm);
  }

  const types = Array.from(new Set(bookmarks.map(b => b.target_type)));
  const formatDate = (ts: string) =>
    new Date(ts).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });

  return (
    <div className="bookmarks-page">
      <div className="bookmarks-page__title">
        <span>★</span>
        <span>Bookmarks</span>
        {bookmarks.length > 0 && (
          <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--text-muted)' }}>
            ({bookmarks.length} total)
          </span>
        )}
      </div>

      {/* Filter pills */}
      {types.length > 1 && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
          <button
            className={`entity-timeline__range-pill${!filter ? ' entity-timeline__range-pill--active' : ''}`}
            onClick={() => setFilter(null)}
          >
            All
          </button>
          {types.map(t => (
            <button
              key={t}
              className={`entity-timeline__range-pill${filter === t ? ' entity-timeline__range-pill--active' : ''}`}
              onClick={() => setFilter(t)}
            >
              {TYPE_ICONS[t] ?? '📌'} {TYPE_LABELS[t] ?? t}
            </button>
          ))}
        </div>
      )}

      {loading ? (
        <div className="entities-loading"><span className="spinner" /> Loading bookmarks…</div>
      ) : bookmarks.length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 14, marginTop: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>☆</div>
          <div>No bookmarks yet</div>
          <div style={{ fontSize: 12, marginTop: 8, color: 'var(--text-muted)' }}>
            Bookmark entities, posts, and briefs using the ★ button
          </div>
        </div>
      ) : (
        Object.entries(groups).map(([type, items]) => (
          <div key={type} className="bookmarks-group">
            <div className="bookmarks-group__header">
              <span>{TYPE_ICONS[type] ?? '📌'}</span>
              <span className="bookmarks-group__label">{TYPE_LABELS[type] ?? type}</span>
              <span className="bookmarks-group__count">{items.length}</span>
            </div>
            {items.map(bm => (
              <div key={bm.id} className="bookmark-item" onClick={() => handleNavigate(bm)}>
                <div style={{ fontSize: 14 }}>{TYPE_ICONS[bm.target_type] ?? '📌'}</div>
                <div style={{ flex: 1 }}>
                  <div className="bookmark-item__label">
                    {bm.label ?? <span style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: 11 }}>{bm.target_id}</span>}
                  </div>
                  <div className="bookmark-item__sub">
                    Saved {formatDate(bm.created_at)}
                  </div>
                </div>
                <button
                  className="bookmark-item__remove-btn"
                  onClick={e => { e.stopPropagation(); removeBookmark(bm); }}
                  title="Remove bookmark"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  );
}

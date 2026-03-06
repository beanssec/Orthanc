import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import '../../styles/collaboration.css';

// ── Types ──────────────────────────────────────────────────
interface EntityDetailData {
  id: string;
  name: string;
  type: string;
  canonical_name?: string;
  mention_count: number;
  first_seen: string;
  last_seen: string;
  mentions?: unknown[];
}

interface Connection {
  entity: { id: string; name: string; type: string };
  co_occurrences: number;
}

interface TimelineItem {
  post_id: string;
  content: string | null;
  source_type: string;
  author: string | null;
  timestamp: string | null;
  context_snippet: string | null;
  event: { lat: number; lng: number; place_name: string | null } | null;
}

interface TimelineResponse {
  total: number;
  page: number;
  page_size: number;
  items: TimelineItem[];
  entity: { id: string; name: string; type: string; first_seen: string; last_seen: string };
}

interface PathStep {
  entity: { id: string; name: string; type: string };
  connecting_posts: number;
}

interface PathResult {
  source: { id: string; name: string; type: string };
  target: { id: string; name: string; type: string };
  path: PathStep[];
  depth: number;
  found: boolean;
}

interface EntityListItem {
  id: string;
  name: string;
  type: string;
  mention_count: number;
}

interface RelationshipType {
  id: string;
  label: string;
  directed: boolean;
}

interface Relationship {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  confidence: number;
  notes: string | null;
  evidence_post_ids: string[];
  created_by: string | null;
  created_at: string;
  source_entity: { id: string; name: string; type: string } | null;
  target_entity: { id: string; name: string; type: string } | null;
}

interface Note {
  id: string;
  user_id: string;
  content: string;
  created_at: string;
  updated_at: string;
}

interface Tag {
  id: string;
  tag: string;
  target_type: string;
  target_id: string;
}

interface Props {
  entityId: string | number;
}

type DetailTab = 'overview' | 'timeline' | 'relationships' | 'notes';
type TimeRange = 24 | 48 | 168 | 720 | 99999;

// ── Helpers ────────────────────────────────────────────────
function entityTypeClass(type: string): string {
  const map: Record<string, string> = {
    PERSON: 'person', ORG: 'org', GPE: 'gpe', EVENT: 'event', NORP: 'norp',
  };
  return map[type?.toUpperCase()] ?? 'norp';
}

function formatDate(ts: string | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatDateTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  return new Date(ts).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

const SOURCE_COLORS: Record<string, string> = {
  telegram: '#3b82f6', twitter: '#1da1f2', rss: '#f97316',
  reddit: '#ef4444', mastodon: '#6366f1',
};
function sourceBadgeStyle(source: string) {
  const color = SOURCE_COLORS[source?.toLowerCase()] ?? '#6b7280';
  return { background: color + '22', border: `1px solid ${color}44`, color };
}

function confidenceColor(conf: number): string {
  if (conf >= 0.7) return '#10b981';
  if (conf >= 0.4) return '#f59e0b';
  return '#ef4444';
}

// ── Path Modal ─────────────────────────────────────────────
interface PathModalProps {
  sourceEntityId: string;
  sourceEntityName: string;
  onClose: () => void;
}

function PathModal({ sourceEntityId, sourceEntityName, onClose }: PathModalProps) {
  const [allEntities, setAllEntities] = useState<EntityListItem[]>([]);
  const [search, setSearch] = useState('');
  const [selectedTarget, setSelectedTarget] = useState<EntityListItem | null>(null);
  const [pathResult, setPathResult] = useState<PathResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [entitiesLoading, setEntitiesLoading] = useState(true);
  const [maxDepth, setMaxDepth] = useState(3);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    api.get('/entities/', { params: { limit: 500, sort_by: 'mention_count' } })
      .then(res => setAllEntities((res.data as EntityListItem[]).filter(e => String(e.id) !== String(sourceEntityId))))
      .catch(() => {})
      .finally(() => setEntitiesLoading(false));
  }, [sourceEntityId]);

  const filteredEntities = search.trim()
    ? allEntities.filter(e => e.name.toLowerCase().includes(search.toLowerCase())).slice(0, 10)
    : [];

  const findPath = useCallback(async () => {
    if (!selectedTarget) return;
    setLoading(true);
    setPathResult(null);
    try {
      const res = await api.get('/entities/path', {
        params: { source_id: sourceEntityId, target_id: selectedTarget.id, max_depth: maxDepth },
      });
      setPathResult(res.data as PathResult);
    } catch {
      setPathResult(null);
    } finally {
      setLoading(false);
    }
  }, [selectedTarget, sourceEntityId, maxDepth]);

  return (
    <div className="path-modal-backdrop" onClick={onClose}>
      <div className="path-modal" onClick={e => e.stopPropagation()}>
        <div className="path-modal__header">
          <span className="path-modal__title">Find Connection Path</span>
          <button className="path-modal__close" onClick={onClose}>✕</button>
        </div>
        <div className="path-modal__body">
          <div className="path-modal__source">
            <span className="path-modal__label">From:</span>
            <span className="path-modal__entity-name">{sourceEntityName}</span>
          </div>
          <div className="path-modal__target-section">
            <span className="path-modal__label">To:</span>
            {selectedTarget ? (
              <div className="path-modal__selected-target">
                <span className={`badge badge--${entityTypeClass(selectedTarget.type)}`}>{selectedTarget.type}</span>
                <span className="path-modal__entity-name">{selectedTarget.name}</span>
                <button className="path-modal__clear-target" onClick={() => { setSelectedTarget(null); setPathResult(null); }}>✕</button>
              </div>
            ) : (
              <div className="path-modal__search-wrap">
                <input
                  ref={inputRef}
                  className="input"
                  placeholder={entitiesLoading ? 'Loading entities…' : 'Search target entity…'}
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  disabled={entitiesLoading}
                />
                {filteredEntities.length > 0 && (
                  <div className="path-modal__dropdown">
                    {filteredEntities.map(e => (
                      <div key={e.id} className="path-modal__dropdown-item"
                        onClick={() => { setSelectedTarget(e); setSearch(''); }}>
                        <span className={`badge badge--${entityTypeClass(e.type)}`}>{e.type}</span>
                        <span>{e.name}</span>
                        <span className="path-modal__dropdown-count">{e.mention_count}×</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="path-modal__options">
            <label className="path-modal__label">Max Depth:</label>
            <select className="select select--sm" value={maxDepth} onChange={e => setMaxDepth(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <button className="btn btn-primary" onClick={findPath} disabled={!selectedTarget || loading}>
            {loading ? 'Searching…' : '🔗 Find Path'}
          </button>
          {pathResult && (
            <div className="path-result">
              {pathResult.found ? (
                <>
                  <div className="path-result__found">✓ Path found — {pathResult.depth} hop{pathResult.depth !== 1 ? 's' : ''}</div>
                  <div className="path-result__chain">
                    {pathResult.path.map((step, i) => (
                      <div key={step.entity.id} className="path-result__step">
                        <div className="path-result__step-entity">
                          <span className={`badge badge--${entityTypeClass(step.entity.type)}`}>{step.entity.type}</span>
                          <span className="path-result__step-name">{step.entity.name}</span>
                        </div>
                        {i > 0 && <div className="path-result__step-meta">{step.connecting_posts} shared post{step.connecting_posts !== 1 ? 's' : ''}</div>}
                        {i < pathResult.path.length - 1 && <div className="path-result__arrow">↓</div>}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="path-result__not-found">✗ No path found within {maxDepth} hops</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Add Relationship Modal ─────────────────────────────────
interface AddRelModalProps {
  entityId: string;
  relTypes: RelationshipType[];
  onClose: () => void;
  onCreated: (rel: Relationship) => void;
}

function AddRelationshipModal({ entityId, relTypes, onClose, onCreated }: AddRelModalProps) {
  const [allEntities, setAllEntities] = useState<EntityListItem[]>([]);
  const [search, setSearch] = useState('');
  const [selectedTarget, setSelectedTarget] = useState<EntityListItem | null>(null);
  const [relType, setRelType] = useState(relTypes[0]?.id ?? '');
  const [confidence, setConfidence] = useState(50);
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.get('/entities/', { params: { limit: 500, sort_by: 'mention_count' } })
      .then(res => setAllEntities((res.data as EntityListItem[]).filter(e => e.id !== entityId)))
      .catch(() => {});
    inputRef.current?.focus();
  }, [entityId]);

  const filtered = search.trim()
    ? allEntities.filter(e => e.name.toLowerCase().includes(search.toLowerCase())).slice(0, 8)
    : [];

  const handleSubmit = async () => {
    if (!selectedTarget || !relType) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.post(`/entities/${entityId}/relationships`, {
        target_entity_id: selectedTarget.id,
        relationship_type: relType,
        confidence: confidence / 100,
        notes: notes.trim() || null,
      });
      onCreated(res.data as Relationship);
      onClose();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create relationship';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rel-modal-backdrop" onClick={onClose}>
      <div className="rel-modal" onClick={e => e.stopPropagation()}>
        <div className="rel-modal__header">
          <span className="rel-modal__title">Add Relationship</span>
          <button className="rel-modal__close" onClick={onClose}>✕</button>
        </div>
        <div className="rel-modal__body">
          {/* Target entity */}
          <div className="rel-modal__field">
            <label className="rel-modal__label">Target Entity</label>
            {selectedTarget ? (
              <div className="rel-modal__selected-entity">
                <span className={`badge badge--${entityTypeClass(selectedTarget.type)}`}>{selectedTarget.type}</span>
                <span style={{ fontSize: 12 }}>{selectedTarget.name}</span>
                <button className="rel-modal__clear-btn" onClick={() => setSelectedTarget(null)}>✕</button>
              </div>
            ) : (
              <div className="rel-modal__entity-search">
                <input
                  ref={inputRef}
                  className="input"
                  placeholder="Search entity…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                />
                {filtered.length > 0 && (
                  <div className="rel-modal__dropdown">
                    {filtered.map(e => (
                      <div key={e.id} className="rel-modal__dropdown-item"
                        onClick={() => { setSelectedTarget(e); setSearch(''); }}>
                        <span className={`badge badge--${entityTypeClass(e.type)}`}>{e.type}</span>
                        <span>{e.name}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Relationship type */}
          <div className="rel-modal__field">
            <label className="rel-modal__label">Relationship Type</label>
            <select className="select" value={relType} onChange={e => setRelType(e.target.value)}>
              {relTypes.map(rt => (
                <option key={rt.id} value={rt.id}>{rt.label}{rt.directed ? ' →' : ' ↔'}</option>
              ))}
            </select>
          </div>

          {/* Confidence */}
          <div className="rel-modal__field">
            <label className="rel-modal__label">Confidence</label>
            <div className="rel-modal__confidence-row">
              <input
                type="range" min={0} max={100} value={confidence}
                onChange={e => setConfidence(Number(e.target.value))}
              />
              <span className="rel-modal__confidence-value" style={{ color: confidenceColor(confidence / 100) }}>
                {confidence}%
              </span>
            </div>
          </div>

          {/* Notes */}
          <div className="rel-modal__field">
            <label className="rel-modal__label">Notes (optional)</label>
            <textarea
              className="input"
              placeholder="Supporting context or evidence…"
              value={notes}
              onChange={e => setNotes(e.target.value)}
              style={{ minHeight: 72, resize: 'vertical', fontFamily: 'inherit', fontSize: 12 }}
            />
          </div>

          {error && (
            <div style={{ fontSize: 12, color: 'var(--danger)', padding: '6px 10px', background: '#ef444415', borderRadius: 4 }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" onClick={handleSubmit} disabled={!selectedTarget || !relType || loading}>
              {loading ? 'Saving…' : '+ Add Relationship'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Notes Section ──────────────────────────────────────────
interface NotesSectionProps {
  targetType: string;
  targetId: string;
}

function NotesSection({ targetType, targetId }: NotesSectionProps) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [newNote, setNewNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');

  useEffect(() => {
    api.get(`/notes/${targetType}/${targetId}`)
      .then(res => setNotes(res.data as Note[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [targetType, targetId]);

  const submitNote = async () => {
    if (!newNote.trim()) return;
    setSubmitting(true);
    try {
      const res = await api.post(`/notes/${targetType}/${targetId}`, { content: newNote.trim() });
      setNotes(prev => [res.data as Note, ...prev]);
      setNewNote('');
    } catch {/* ignore */} finally {
      setSubmitting(false);
    }
  };

  const saveEdit = async (noteId: string) => {
    if (!editContent.trim()) return;
    try {
      const res = await api.put(`/notes/${noteId}`, { content: editContent.trim() });
      setNotes(prev => prev.map(n => n.id === noteId ? res.data as Note : n));
      setEditingId(null);
    } catch {/* ignore */}
  };

  const deleteNote = async (noteId: string) => {
    try {
      await api.delete(`/notes/${noteId}`);
      setNotes(prev => prev.filter(n => n.id !== noteId));
    } catch {/* ignore */}
  };

  return (
    <div className="collab-notes">
      {loading ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>Loading notes…</div>
      ) : (
        notes.map(note => (
          <div key={note.id} className="note-card">
            <div className="note-card__header">
              <span className="note-card__timestamp">{formatDateTime(note.created_at)}</span>
              {note.updated_at !== note.created_at && (
                <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 4 }}>(edited)</span>
              )}
              <div className="note-card__actions">
                <button className="note-card__action-btn" onClick={() => { setEditingId(note.id); setEditContent(note.content); }}>Edit</button>
                <button className="note-card__action-btn note-card__action-btn--danger" onClick={() => deleteNote(note.id)}>Delete</button>
              </div>
            </div>
            {editingId === note.id ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <textarea
                  className="note-card__edit-area"
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                />
                <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                  <button className="btn btn-secondary btn-sm" style={{ fontSize: 11 }} onClick={() => setEditingId(null)}>Cancel</button>
                  <button className="btn btn-primary btn-sm" style={{ fontSize: 11 }} onClick={() => saveEdit(note.id)}>Save</button>
                </div>
              </div>
            ) : (
              <div className="note-card__content">{note.content}</div>
            )}
          </div>
        ))
      )}

      <div className="note-add-form">
        <textarea
          placeholder="Add a note…"
          value={newNote}
          onChange={e => setNewNote(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && e.ctrlKey) submitNote(); }}
        />
        <div className="note-add-form__actions">
          <button className="btn btn-primary btn-sm" disabled={!newNote.trim() || submitting} onClick={submitNote}>
            {submitting ? 'Adding…' : '+ Add Note'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Tags Section ───────────────────────────────────────────
interface TagsSectionProps {
  targetType: string;
  targetId: string;
}

function TagsSection({ targetType, targetId }: TagsSectionProps) {
  const navigate = useNavigate();
  const [tags, setTags] = useState<Tag[]>([]);
  const [newTag, setNewTag] = useState('');

  useEffect(() => {
    api.get(`/tags/${targetType}/${targetId}`)
      .then(res => setTags(res.data as Tag[]))
      .catch(() => {});
  }, [targetType, targetId]);

  const addTag = async (tag: string) => {
    const trimmed = tag.trim().toLowerCase();
    if (!trimmed) return;
    try {
      const res = await api.post(`/tags/${targetType}/${targetId}`, { tag: trimmed });
      setTags(prev => [...prev, res.data as Tag]);
      setNewTag('');
    } catch {/* ignore */}
  };

  const removeTag = async (tagValue: string) => {
    try {
      await api.delete(`/tags/${targetType}/${targetId}/${encodeURIComponent(tagValue)}`);
      setTags(prev => prev.filter(t => t.tag !== tagValue));
    } catch {/* ignore */}
  };

  return (
    <div className="tag-pills">
      {tags.map(t => (
        <span key={t.id} className="tag-pill" onClick={() => navigate(`/search?q=${encodeURIComponent(t.tag)}&tag=true`)}>
          {t.tag}
          <button className="tag-pill__remove" onClick={e => { e.stopPropagation(); removeTag(t.tag); }}>×</button>
        </span>
      ))}
      <input
        className="tag-add-input"
        placeholder="+ tag"
        value={newTag}
        onChange={e => setNewTag(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') addTag(newTag); }}
      />
    </div>
  );
}

// ── Bookmark Button ────────────────────────────────────────
interface BookmarkBtnProps {
  targetType: string;
  targetId: string;
  label?: string;
}

function BookmarkButton({ targetType, targetId, label }: BookmarkBtnProps) {
  const [bookmarked, setBookmarked] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/bookmarks/check/${targetType}/${targetId}`)
      .then(res => setBookmarked((res.data as { bookmarked: boolean }).bookmarked))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [targetType, targetId]);

  const toggle = async () => {
    const prev = bookmarked;
    setBookmarked(!prev); // optimistic
    try {
      if (prev) {
        await api.delete(`/bookmarks/${targetType}/${targetId}`);
      } else {
        await api.post(`/bookmarks/${targetType}/${targetId}`, { label: label ?? null });
      }
    } catch {
      setBookmarked(prev); // revert
    }
  };

  if (loading) return null;

  return (
    <button
      className={`bookmark-btn${bookmarked ? ' bookmark-btn--active' : ''}`}
      onClick={toggle}
      title={bookmarked ? 'Remove bookmark' : 'Bookmark this entity'}
    >
      <span className="bookmark-star">{bookmarked ? '★' : '☆'}</span>
      {bookmarked ? 'Bookmarked' : 'Bookmark'}
    </button>
  );
}

// ── Relationships Section ──────────────────────────────────
interface RelationshipsSectionProps {
  entityId: string;
  relTypes: RelationshipType[];
}

function RelationshipsSection({ entityId, relTypes }: RelationshipsSectionProps) {
  const navigate = useNavigate();
  const [rels, setRels] = useState<Relationship[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  useEffect(() => {
    api.get(`/entities/${entityId}/relationships`)
      .then(res => setRels(res.data as Relationship[]))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [entityId]);

  const handleDelete = async (relId: string) => {
    try {
      await api.delete(`/entities/relationships/${relId}`);
      setRels(prev => prev.filter(r => r.id !== relId));
    } catch {/* ignore */}
    setConfirmDelete(null);
  };

  const getRelTypeInfo = (typeId: string) => relTypes.find(r => r.id === typeId);

  return (
    <>
      <div className="entity-section__title-row">
        <span className="entity-section__title">Relationships ({rels.length})</span>
        <button className="btn btn-secondary btn-sm" style={{ fontSize: 10, padding: '2px 8px' }}
          onClick={() => setShowAddModal(true)}>
          + Add
        </button>
      </div>

      <div className="entity-relationships">
        {loading ? (
          <div style={{ padding: '12px 14px', fontSize: 12, color: 'var(--text-muted)' }}>Loading…</div>
        ) : rels.length === 0 ? (
          <div style={{ padding: '12px 14px', fontSize: 12, color: 'var(--text-muted)' }}>
            No relationships defined yet
          </div>
        ) : (
          rels.map(rel => {
            const isSource = rel.source_entity_id === entityId;
            const other = isSource ? rel.target_entity : rel.source_entity;
            const typeInfo = getRelTypeInfo(rel.relationship_type);
            return (
              <div key={rel.id} className="entity-relationship__item">
                <div className="entity-relationship__badge-col">
                  <span className={`rel-badge rel-badge--${rel.relationship_type}`}>
                    {typeInfo?.label ?? rel.relationship_type}
                  </span>
                  {typeInfo?.directed && !isSource && (
                    <span style={{ fontSize: 9, color: 'var(--text-muted)', display: 'block', marginTop: 2 }}>← received</span>
                  )}
                </div>
                <div className="entity-relationship__target">
                  <div className="entity-relationship__target-name"
                    onClick={() => other && navigate(`/entities/${other.id}`)}>
                    {other && <span className={`badge badge--${entityTypeClass(other.type)}`}>{other.type}</span>}
                    <span>{other?.name ?? '—'}</span>
                  </div>
                  {/* Confidence bar */}
                  <div className="confidence-bar" style={{ marginTop: 5 }}>
                    <div className="confidence-bar__track">
                      <div className="confidence-bar__fill" style={{
                        width: `${Math.round(rel.confidence * 100)}%`,
                        background: confidenceColor(rel.confidence),
                      }} />
                    </div>
                    <div className="confidence-bar__label">
                      <span>Confidence</span>
                      <span>{Math.round(rel.confidence * 100)}%</span>
                    </div>
                  </div>
                  {rel.notes && <div className="entity-relationship__notes">{rel.notes}</div>}
                </div>
                <div className="entity-relationship__actions">
                  {confirmDelete === rel.id ? (
                    <div style={{ display: 'flex', gap: 4 }}>
                      <button className="btn btn-sm" style={{ fontSize: 10, background: 'var(--danger)', color: '#fff', border: 'none', padding: '2px 6px', borderRadius: 3 }}
                        onClick={() => handleDelete(rel.id)}>Yes</button>
                      <button className="btn btn-secondary btn-sm" style={{ fontSize: 10 }}
                        onClick={() => setConfirmDelete(null)}>No</button>
                    </div>
                  ) : (
                    <button className="entity-relationship__delete-btn" onClick={() => setConfirmDelete(rel.id)}>✕ remove</button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {showAddModal && (
        <AddRelationshipModal
          entityId={entityId}
          relTypes={relTypes}
          onClose={() => setShowAddModal(false)}
          onCreated={rel => setRels(prev => [rel, ...prev])}
        />
      )}
    </>
  );
}

// ── Main Component ──────────────────────────────────────────
export function EntityDetail({ entityId }: Props) {
  const navigate = useNavigate();
  const [entity, setEntity] = useState<EntityDetailData | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>('overview');
  const [relTypes, setRelTypes] = useState<RelationshipType[]>([]);

  // Timeline state
  const [timelineItems, setTimelineItems] = useState<TimelineItem[]>([]);
  const [timelineTotal, setTimelineTotal] = useState(0);
  const [timelinePage, setTimelinePage] = useState(1);
  const [timelineRange, setTimelineRange] = useState<TimeRange>(168);
  const [timelineLoading, setTimelineLoading] = useState(false);

  // Path modal
  const [showPathModal, setShowPathModal] = useState(false);

  // Load entity + connections + rel types
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setEntity(null);
    setConnections([]);
    setActiveTab('overview');

    Promise.all([
      api.get(`/entities/${entityId}`),
      api.get(`/entities/${entityId}/connections`),
      api.get('/entities/relationship-types'),
    ])
      .then(([entityRes, connRes, rtRes]) => {
        if (!cancelled) {
          setEntity(entityRes.data as EntityDetailData);
          const conns = (connRes.data as Connection[]).sort((a, b) => b.co_occurrences - a.co_occurrences);
          setConnections(conns);
          setRelTypes(rtRes.data as RelationshipType[]);
        }
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load entity');
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [entityId]);

  // Timeline loading
  useEffect(() => {
    if (activeTab !== 'timeline') return;
    let cancelled = false;
    setTimelineLoading(true);

    api.get(`/entities/${entityId}/timeline`, {
      params: { hours: timelineRange, page: timelinePage, page_size: 30 },
    })
      .then(res => {
        if (!cancelled) {
          const data = res.data as TimelineResponse;
          setTimelineItems(data.items);
          setTimelineTotal(data.total);
        }
      })
      .catch(() => { if (!cancelled) setTimelineItems([]); })
      .finally(() => { if (!cancelled) setTimelineLoading(false); });

    return () => { cancelled = true; };
  }, [entityId, activeTab, timelineRange, timelinePage]);

  const handleRangeChange = useCallback((range: TimeRange) => {
    setTimelineRange(range);
    setTimelinePage(1);
  }, []);

  if (loading) {
    return <div className="entities-loading"><span className="spinner" />Loading entity…</div>;
  }
  if (error || !entity) {
    return <div className="entities-error">⚠ {error ?? 'Entity not found'}</div>;
  }

  const totalPages = Math.ceil(timelineTotal / 30);

  return (
    <div className="entity-detail">
      {/* Header */}
      <div className="entity-detail__header">
        <div className="entity-detail__name">{entity.name}</div>
        <div className="entity-detail__meta" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className={`badge badge--${entityTypeClass(entity.type)}`}>{entity.type}</span>
          {entity.canonical_name && entity.canonical_name !== entity.name && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>aka {entity.canonical_name}</span>
          )}
          <BookmarkButton targetType="entity" targetId={String(entity.id)} label={entity.name} />
        </div>
      </div>

      {/* Tags */}
      <div style={{ padding: '6px 14px 10px', borderBottom: '1px solid var(--border)' }}>
        <TagsSection targetType="entity" targetId={String(entity.id)} />
      </div>

      {/* Tab bar */}
      <div className="entity-detail__tabs">
        {(['overview', 'timeline', 'relationships', 'notes'] as DetailTab[]).map(tab => (
          <button
            key={tab}
            className={`entity-detail__tab${activeTab === tab ? ' entity-detail__tab--active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab === 'overview' ? 'Overview'
              : tab === 'timeline' ? `Timeline${timelineTotal > 0 && activeTab === 'timeline' ? ` (${timelineTotal})` : ''}`
              : tab === 'relationships' ? 'Relationships'
              : 'Notes'}
          </button>
        ))}
      </div>

      {/* Body */}
      <div className="entity-detail__body">
        {/* ── Overview ── */}
        {activeTab === 'overview' && (
          <>
            <div className="entity-stats">
              <div className="entity-stats__item">
                <span className="entity-stats__value">{entity.mention_count}</span>
                <span className="entity-stats__label">Mentions</span>
              </div>
              <div className="entity-stats__item">
                <span className="entity-stats__value">{formatDate(entity.first_seen)}</span>
                <span className="entity-stats__label">First Seen</span>
              </div>
              <div className="entity-stats__item">
                <span className="entity-stats__value">{formatDate(entity.last_seen)}</span>
                <span className="entity-stats__label">Last Seen</span>
              </div>
            </div>

            <div className="entity-section">
              <div className="entity-section__title-row">
                <span className="entity-section__title">Connected Entities ({connections.length})</span>
                <button className="btn btn-secondary btn-sm" style={{ fontSize: 10, padding: '2px 8px' }}
                  onClick={() => setShowPathModal(true)}>
                  🔗 Find Path
                </button>
              </div>
              {connections.length > 0 && <div className="entity-section__hint">Co-occur in the same posts</div>}
              <div className="entity-connections">
                {connections.length === 0 ? (
                  <div style={{ padding: '12px 14px', color: 'var(--text-muted)', fontSize: 12 }}>No connections found</div>
                ) : (
                  connections.slice(0, 20).map((conn) => (
                    <div key={conn.entity.id} className="entity-connection__item">
                      <span className={`badge badge--${entityTypeClass(conn.entity.type)}`} style={{ cursor: 'pointer' }}
                        onClick={() => navigate(`/entities/${conn.entity.id}`)}>
                        {conn.entity.type}
                      </span>
                      <span className="entity-connection__name" onClick={() => navigate(`/entities/${conn.entity.id}`)} style={{ cursor: 'pointer' }}>
                        {conn.entity.name}
                      </span>
                      <span className="entity-connection__count">{conn.co_occurrences}×</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </>
        )}

        {/* ── Timeline ── */}
        {activeTab === 'timeline' && (
          <div className="entity-timeline">
            <div className="entity-timeline__controls">
              <span className="entity-timeline__total">{timelineTotal} mention{timelineTotal !== 1 ? 's' : ''}</span>
              <div className="entity-timeline__range-pills">
                {([24, 48, 168, 720, 99999] as TimeRange[]).map(r => (
                  <button key={r}
                    className={`entity-timeline__range-pill${timelineRange === r ? ' entity-timeline__range-pill--active' : ''}`}
                    onClick={() => handleRangeChange(r)}>
                    {r === 24 ? '24h' : r === 48 ? '48h' : r === 168 ? '7d' : r === 720 ? '30d' : 'All'}
                  </button>
                ))}
              </div>
            </div>
            {timelineLoading ? (
              <div className="entities-loading"><span className="spinner" /> Loading timeline…</div>
            ) : timelineItems.length === 0 ? (
              <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                No posts found in this time range
              </div>
            ) : (
              <div className="entity-timeline__list">
                {timelineItems.map((item, i) => (
                  <div key={item.post_id + i} className="entity-timeline__item"
                    onClick={() => navigate(`/feed?post=${item.post_id}`)}>
                    <div className="entity-timeline__spine">
                      <div className="entity-timeline__dot" />
                      {i < timelineItems.length - 1 && <div className="entity-timeline__line" />}
                    </div>
                    <div className="entity-timeline__card">
                      <div className="entity-timeline__card-header">
                        <span className="entity-timeline__ts">{formatDateTime(item.timestamp)}</span>
                        <span className="entity-timeline__source" style={sourceBadgeStyle(item.source_type)}>{item.source_type}</span>
                        {item.author && <span className="entity-timeline__author">@{item.author}</span>}
                        {item.event && (
                          <span className="entity-timeline__geo" title={item.event.place_name ?? ''}>
                            📍 {item.event.place_name ?? `${item.event.lat?.toFixed(2)},${item.event.lng?.toFixed(2)}`}
                          </span>
                        )}
                      </div>
                      {item.context_snippet && <div className="entity-timeline__snippet">{item.context_snippet}</div>}
                      <div className="entity-timeline__content">
                        {(item.content ?? '').slice(0, 200)}{(item.content ?? '').length > 200 ? '…' : ''}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {totalPages > 1 && (
              <div className="entities-pagination">
                <span>Page {timelinePage} of {totalPages} · {timelineTotal} total</span>
                <div className="entities-pagination__controls">
                  <button className="btn btn-secondary btn-sm" disabled={timelinePage <= 1}
                    onClick={() => setTimelinePage(p => p - 1)}>← Prev</button>
                  <button className="btn btn-secondary btn-sm" disabled={timelinePage >= totalPages}
                    onClick={() => setTimelinePage(p => p + 1)}>Next →</button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Relationships ── */}
        {activeTab === 'relationships' && (
          <div className="entity-section">
            <RelationshipsSection entityId={String(entity.id)} relTypes={relTypes} />
          </div>
        )}

        {/* ── Notes ── */}
        {activeTab === 'notes' && (
          <div className="entity-section">
            <div className="entity-section__title">Notes</div>
            <NotesSection targetType="entity" targetId={String(entity.id)} />
          </div>
        )}
      </div>

      {showPathModal && entity && (
        <PathModal
          sourceEntityId={String(entity.id)}
          sourceEntityName={entity.name}
          onClose={() => setShowPathModal(false)}
        />
      )}
    </div>
  );
}

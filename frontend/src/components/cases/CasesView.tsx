import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../../services/api'
import '../../styles/cases.css'

interface CaseSummary {
  id: string
  title: string
  description?: string
  classification: string
  status: string
  item_count: number
  created_at: string
  updated_at: string
}

interface CreateCaseForm {
  title: string
  description: string
  classification: string
}

const STATUS_DOT: Record<string, string> = {
  open: 'status-dot-open',
  active: 'status-dot-active',
  closed: 'status-dot-closed',
  archived: 'status-dot-archived',
}

const STATUS_BADGE: Record<string, string> = {
  open: 'case-card__meta-badge status-open',
  active: 'case-card__meta-badge status-active',
  closed: 'case-card__meta-badge status-closed',
  archived: 'case-card__meta-badge status-archived',
}

const CLASSIF_BADGE: Record<string, string> = {
  unclassified: 'case-card__meta-badge classif-unclassified',
  confidential: 'case-card__meta-badge classif-confidential',
  secret: 'case-card__meta-badge classif-secret',
  top_secret: 'case-card__meta-badge classif-top_secret',
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

export function CasesView() {
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('all')
  const [showCreate, setShowCreate] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<CreateCaseForm>({
    title: '',
    description: '',
    classification: 'unclassified',
  })

  const fetchCases = () => {
    setLoading(true)
    const url = statusFilter === 'all' ? '/cases/' : `/cases/?status=${statusFilter}`
    api.get(url)
      .then((r) => setCases(r.data as CaseSummary[]))
      .catch(() => setCases([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchCases()
  }, [statusFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleCreate = async () => {
    if (!form.title.trim()) return
    setCreating(true)
    try {
      await api.post('/cases/', {
        title: form.title.trim(),
        description: form.description.trim() || null,
        classification: form.classification,
      })
      setShowCreate(false)
      setForm({ title: '', description: '', classification: 'unclassified' })
      fetchCases()
    } catch (e) {
      console.error('Failed to create case', e)
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="cases-view">
      <div className="cases-header">
        <div className="cases-header__title">
          🕵️ Investigations
        </div>
        <div className="cases-header__actions">
          <select
            className="cases-filter-select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <option value="all">All</option>
            <option value="open">Open</option>
            <option value="active">Active</option>
            <option value="closed">Closed</option>
            <option value="archived">Archived</option>
          </select>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            + New Case
          </button>
        </div>
      </div>

      {/* Create modal */}
      {showCreate && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowCreate(false)}>
          <div className="modal-box">
            <div className="modal-box__title">New Investigation</div>
            <div className="modal-box__field">
              <label className="modal-box__label">Title</label>
              <input
                className="modal-box__input"
                placeholder="Operation name or description…"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                autoFocus
              />
            </div>
            <div className="modal-box__field">
              <label className="modal-box__label">Description</label>
              <textarea
                className="modal-box__textarea"
                placeholder="What is this investigation about?"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
            <div className="modal-box__field">
              <label className="modal-box__label">Classification</label>
              <select
                className="modal-box__select"
                value={form.classification}
                onChange={(e) => setForm((f) => ({ ...f, classification: e.target.value }))}
              >
                <option value="unclassified">Unclassified</option>
                <option value="confidential">Confidential</option>
                <option value="secret">Secret</option>
                <option value="top_secret">Top Secret</option>
              </select>
            </div>
            <div className="modal-box__actions">
              <button className="btn btn-ghost" onClick={() => setShowCreate(false)} disabled={creating}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={creating || !form.title.trim()}>
                {creating ? 'Creating…' : 'Create Case'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="cases-list">
        {loading ? (
          <div className="cases-empty">
            <div className="cases-empty__text">Loading…</div>
          </div>
        ) : cases.length === 0 ? (
          <div className="cases-empty">
            <div className="cases-empty__icon">🕵️</div>
            <div className="cases-empty__text">No investigations yet</div>
            <div className="cases-empty__sub">Create a case to start tracking evidence</div>
          </div>
        ) : (
          cases.map((c) => (
            <Link key={c.id} to={`/cases/${c.id}`} className="case-card">
              <div className="case-card__header">
                <span className={`case-card__status-dot ${STATUS_DOT[c.status] || 'status-dot-open'}`} />
                <span className="case-card__title">{c.title}</span>
              </div>
              {c.description && (
                <div className="case-card__desc">{c.description}</div>
              )}
              <div className="case-card__meta">
                <span>{c.item_count} item{c.item_count !== 1 ? 's' : ''}</span>
                <span className={STATUS_BADGE[c.status] || 'case-card__meta-badge status-open'}>
                  {c.status}
                </span>
                <span className={CLASSIF_BADGE[c.classification] || 'case-card__meta-badge classif-unclassified'}>
                  {c.classification.replace('_', ' ')}
                </span>
                <span>{timeAgo(c.updated_at)}</span>
              </div>
            </Link>
          ))
        )}
      </div>
    </div>
  )
}

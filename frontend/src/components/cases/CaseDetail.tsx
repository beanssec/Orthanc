import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import api from '../../services/api'
import '../../styles/cases.css'

interface CaseData {
  id: string
  title: string
  description?: string
  classification: string
  status: string
  item_count: number
  created_at: string
  updated_at: string
  items: CaseItemData[]
  timeline: CaseTimelineEntry[]
}

interface CaseItemData {
  id: string
  case_id: string
  item_type: string
  item_id?: string
  title?: string
  content?: string
  lat?: number
  lng?: number
  metadata?: Record<string, unknown>
  added_by?: string
  added_at: string
}

interface CaseTimelineEntry {
  id: string
  case_id: string
  timestamp: string
  event_type: string
  description?: string
  added_by?: string
}

const ITEM_ICONS: Record<string, string> = {
  post: '📰',
  entity: '🔗',
  event: '📍',
  fused_event: '⚡',
  note: '📝',
  map_marker: '📌',
}

const STATUS_OPTIONS = ['open', 'active', 'closed', 'archived']
const CLASSIF_OPTIONS = ['unclassified', 'confidential', 'secret', 'top_secret']

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

function fmtDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

// ── Evidence Board Tab ─────────────────────────────────────
function EvidenceBoard({ caseData, onRefresh }: { caseData: CaseData; onRefresh: () => void }) {
  const [showNote, setShowNote] = useState(false)
  const [showMarker, setShowMarker] = useState(false)
  const [noteTitle, setNoteTitle] = useState('')
  const [noteContent, setNoteContent] = useState('')
  const [markerTitle, setMarkerTitle] = useState('')
  const [markerLat, setMarkerLat] = useState('')
  const [markerLng, setMarkerLng] = useState('')
  const [saving, setSaving] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)

  const addNote = async () => {
    if (!noteContent.trim()) return
    setSaving(true)
    try {
      await api.post(`/cases/${caseData.id}/items`, {
        item_type: 'note',
        title: noteTitle.trim() || 'Note',
        content: noteContent.trim(),
      })
      setNoteTitle('')
      setNoteContent('')
      setShowNote(false)
      onRefresh()
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  const addMarker = async () => {
    const lat = parseFloat(markerLat)
    const lng = parseFloat(markerLng)
    if (isNaN(lat) || isNaN(lng)) return
    setSaving(true)
    try {
      await api.post(`/cases/${caseData.id}/items`, {
        item_type: 'map_marker',
        title: markerTitle.trim() || `${lat.toFixed(4)}, ${lng.toFixed(4)}`,
        lat,
        lng,
      })
      setMarkerTitle('')
      setMarkerLat('')
      setMarkerLng('')
      setShowMarker(false)
      onRefresh()
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  const removeItem = async (itemId: string) => {
    setRemoving(itemId)
    try {
      await api.delete(`/cases/${caseData.id}/items/${itemId}`)
      onRefresh()
    } catch (e) { console.error(e) }
    finally { setRemoving(null) }
  }

  return (
    <div>
      {/* Toolbar */}
      <div className="evidence-board__toolbar">
        <button className="btn btn-secondary" onClick={() => { setShowNote(!showNote); setShowMarker(false) }}>
          📝 Add Note
        </button>
        <button className="btn btn-secondary" onClick={() => { setShowMarker(!showMarker); setShowNote(false) }}>
          📌 Add Map Marker
        </button>
      </div>

      {/* Add Note form */}
      {showNote && (
        <div className="add-note-form">
          <input
            placeholder="Note title (optional)"
            value={noteTitle}
            onChange={(e) => setNoteTitle(e.target.value)}
          />
          <textarea
            rows={4}
            placeholder="Note content…"
            value={noteContent}
            onChange={(e) => setNoteContent(e.target.value)}
          />
          <div className="add-note-form__actions">
            <button className="btn btn-ghost" onClick={() => setShowNote(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={addNote} disabled={saving || !noteContent.trim()}>
              {saving ? 'Saving…' : 'Add Note'}
            </button>
          </div>
        </div>
      )}

      {/* Add Marker form */}
      {showMarker && (
        <div className="add-marker-form">
          <input
            placeholder="Location name (optional)"
            value={markerTitle}
            onChange={(e) => setMarkerTitle(e.target.value)}
          />
          <div className="add-marker-form__coords">
            <input
              placeholder="Latitude (e.g. 33.8938)"
              value={markerLat}
              onChange={(e) => setMarkerLat(e.target.value)}
              type="number"
              step="any"
            />
            <input
              placeholder="Longitude (e.g. 35.5018)"
              value={markerLng}
              onChange={(e) => setMarkerLng(e.target.value)}
              type="number"
              step="any"
            />
          </div>
          <div className="add-marker-form__actions">
            <button className="btn btn-ghost" onClick={() => setShowMarker(false)}>Cancel</button>
            <button className="btn btn-primary" onClick={addMarker} disabled={saving || !markerLat || !markerLng}>
              {saving ? 'Saving…' : 'Add Marker'}
            </button>
          </div>
        </div>
      )}

      {/* Item list */}
      <div className="evidence-items">
        {caseData.items.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 16px', color: 'var(--text-muted)' }}>
            No evidence yet. Add notes, posts, or entities.
          </div>
        ) : (
          caseData.items.map((item) => (
            <div key={item.id} className="evidence-item">
              <span className="evidence-item__icon">
                {ITEM_ICONS[item.item_type] || '📁'}
              </span>
              <div className="evidence-item__body">
                <div className="evidence-item__type">{item.item_type.replace('_', ' ')}</div>
                <div className="evidence-item__title">{item.title || item.item_id || 'Untitled'}</div>
                {item.content && (
                  <div className="evidence-item__content">{item.content}</div>
                )}
                {item.lat != null && item.lng != null && (
                  <div className="evidence-item__content">📍 {item.lat.toFixed(4)}, {item.lng.toFixed(4)}</div>
                )}
                <div className="evidence-item__timestamp">{timeAgo(item.added_at)}</div>
              </div>
              <button
                className="evidence-item__remove"
                onClick={() => removeItem(item.id)}
                disabled={removing === item.id}
                title="Remove from case"
              >
                {removing === item.id ? '…' : '✕'}
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── Timeline Tab ───────────────────────────────────────────
function TimelineTab({ entries }: { entries: CaseTimelineEntry[] }) {
  if (entries.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 16px', color: 'var(--text-muted)' }}>
        No timeline events yet.
      </div>
    )
  }

  return (
    <div className="case-timeline">
      {entries.map((entry) => (
        <div key={entry.id} className="case-timeline-entry">
          <span className={`case-timeline-entry__dot case-timeline-entry__dot--${entry.event_type}`} />
          <div className="case-timeline-entry__type">{entry.event_type.replace('_', ' ')}</div>
          <div className="case-timeline-entry__time">{fmtDate(entry.timestamp)}</div>
          <div className="case-timeline-entry__desc">{entry.description || entry.event_type}</div>
        </div>
      ))}
    </div>
  )
}

// ── Map Tab ────────────────────────────────────────────────
function MapTab({ items }: { items: CaseItemData[] }) {
  const mapRef = useRef<HTMLDivElement>(null)
  const mapInstance = useRef<unknown>(null)

  const geoItems = items.filter((i) => i.lat != null && i.lng != null)

  useEffect(() => {
    if (!mapRef.current || geoItems.length === 0) return

    // Dynamically load maplibre-gl if available
    import('maplibre-gl').then((maplibre) => {
      const ML = maplibre.default || maplibre

      if (mapInstance.current) {
        (mapInstance.current as { remove: () => void }).remove()
      }

      const center = geoItems.length > 0
        ? [geoItems[0].lng!, geoItems[0].lat!] as [number, number]
        : [35.0, 32.0] as [number, number]

      const map = new (ML as { Map: new (opts: unknown) => unknown }).Map({
        container: mapRef.current!,
        style: 'https://demotiles.maplibre.org/style.json',
        center,
        zoom: 5,
      })

      mapInstance.current = map

      ;(map as { on: (event: string, cb: () => void) => void }).on('load', () => {
        geoItems.forEach((item) => {
          new (ML as { Marker: new (opts?: unknown) => { setLngLat: (coords: [number, number]) => unknown; setPopup: (p: unknown) => unknown; addTo: (m: unknown) => void } }).Marker({
            color: item.item_type === 'map_marker' ? '#ef4444' : '#3b82f6',
          })
            .setLngLat([item.lng!, item.lat!])
            .setPopup(
              new (ML as { Popup: new (opts?: unknown) => { setHTML: (html: string) => unknown } }).Popup({ offset: 25 })
                .setHTML(`<strong>${item.title || item.item_type}</strong>`)
            )
            .addTo(map as object)
        })
      })
    }).catch(() => {
      // maplibre not available
    })

    return () => {
      if (mapInstance.current) {
        (mapInstance.current as { remove: () => void }).remove()
        mapInstance.current = null
      }
    }
  }, [items]) // eslint-disable-line react-hooks/exhaustive-deps

  if (geoItems.length === 0) {
    return (
      <div className="case-map-empty">
        <span style={{ fontSize: 32 }}>🗺️</span>
        <span>No geo-located items in this case</span>
        <span style={{ fontSize: 12 }}>Add map markers or posts with geo data</span>
      </div>
    )
  }

  return <div ref={mapRef} className="case-map-container" />
}

// ── Main Case Detail ───────────────────────────────────────
export function CaseDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [caseData, setCaseData] = useState<CaseData | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'evidence' | 'timeline' | 'map'>('evidence')
  const [editingTitle, setEditingTitle] = useState(false)
  const [title, setTitle] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const titleRef = useRef<HTMLInputElement>(null)

  const fetchCase = () => {
    if (!id) return
    api.get(`/cases/${id}`)
      .then((r) => {
        const data = r.data as CaseData
        setCaseData(data)
        setTitle(data.title)
      })
      .catch(() => navigate('/cases'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchCase()
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (editingTitle && titleRef.current) {
      titleRef.current.focus()
      titleRef.current.select()
    }
  }, [editingTitle])

  const handleTitleBlur = async () => {
    setEditingTitle(false)
    if (!caseData || title.trim() === caseData.title) return
    if (!title.trim()) { setTitle(caseData.title); return }
    await api.put(`/cases/${id}`, { title: title.trim() })
    fetchCase()
  }

  const handleStatusChange = async (newStatus: string) => {
    await api.put(`/cases/${id}`, { status: newStatus })
    fetchCase()
  }

  const handleClassifChange = async (newClassif: string) => {
    await api.put(`/cases/${id}`, { classification: newClassif })
    fetchCase()
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await api.delete(`/cases/${id}`)
      navigate('/cases')
    } catch (e) {
      console.error(e)
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  const handleExport = () => {
    window.open(`${api.defaults.baseURL}/cases/${id}/export/pdf`, '_blank')
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
        Loading…
      </div>
    )
  }

  if (!caseData) return null

  return (
    <div className="case-detail">
      {/* Header */}
      <div className="case-detail__header">
        <div className="case-detail__breadcrumb">
          <Link to="/cases">🕵️ Investigations</Link>
          <span>›</span>
          <span>{caseData.title}</span>
        </div>

        <div className="case-detail__title-row">
          <input
            ref={titleRef}
            className="case-detail__title-input"
            value={title}
            onClick={() => setEditingTitle(true)}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={handleTitleBlur}
            onKeyDown={(e) => e.key === 'Enter' && titleRef.current?.blur()}
          />

          <div className="case-detail__badges">
            <select
              className={`case-detail__status-select ${STATUS_BADGE[caseData.status] || ''}`}
              value={caseData.status}
              onChange={(e) => handleStatusChange(e.target.value)}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>

            <select
              className={`case-detail__status-select ${CLASSIF_BADGE[caseData.classification] || ''}`}
              value={caseData.classification}
              onChange={(e) => handleClassifChange(e.target.value)}
            >
              {CLASSIF_OPTIONS.map((c) => (
                <option key={c} value={c}>{c.replace('_', ' ')}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="case-detail__meta">
          <span>{caseData.item_count} item{caseData.item_count !== 1 ? 's' : ''}</span>
          <span>Created {timeAgo(caseData.created_at)}</span>
          <span>Updated {timeAgo(caseData.updated_at)}</span>
        </div>

        <div className="case-detail__actions">
          <button className="btn btn-secondary" onClick={handleExport} title="Export as PDF">
            📄 Export PDF
          </button>
          {!confirmDelete ? (
            <button
              className="btn btn-ghost"
              style={{ color: 'var(--danger)', borderColor: 'var(--danger)' }}
              onClick={() => setConfirmDelete(true)}
            >
              🗑 Delete
            </button>
          ) : (
            <>
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Confirm delete?</span>
              <button
                className="btn btn-ghost"
                style={{ color: 'var(--danger)' }}
                onClick={handleDelete}
                disabled={deleting}
              >
                {deleting ? 'Deleting…' : 'Yes, Delete'}
              </button>
              <button className="btn btn-ghost" onClick={() => setConfirmDelete(false)}>
                Cancel
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="case-tabs">
        <button
          className={`case-tab${tab === 'evidence' ? ' case-tab--active' : ''}`}
          onClick={() => setTab('evidence')}
        >
          🗂 Evidence Board ({caseData.items.length})
        </button>
        <button
          className={`case-tab${tab === 'timeline' ? ' case-tab--active' : ''}`}
          onClick={() => setTab('timeline')}
        >
          📅 Timeline ({caseData.timeline.length})
        </button>
        <button
          className={`case-tab${tab === 'map' ? ' case-tab--active' : ''}`}
          onClick={() => setTab('map')}
        >
          🗺 Map
        </button>
      </div>

      {/* Tab content */}
      <div className="case-tab-content">
        {tab === 'evidence' && (
          <EvidenceBoard caseData={caseData} onRefresh={fetchCase} />
        )}
        {tab === 'timeline' && (
          <TimelineTab entries={caseData.timeline} />
        )}
        {tab === 'map' && (
          <MapTab items={caseData.items} />
        )}
      </div>
    </div>
  )
}

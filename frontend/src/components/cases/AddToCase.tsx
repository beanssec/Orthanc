import { useEffect, useRef, useState } from 'react'
import api from '../../services/api'
import '../../styles/cases.css'

interface CaseSummary {
  id: string
  title: string
  status: string
  item_count: number
}

interface Props {
  itemType: string
  itemId?: string
  title?: string
  content?: string
  lat?: number
  lng?: number
}

const STATUS_DOT_CLASS: Record<string, string> = {
  open: 'status-dot-open',
  active: 'status-dot-active',
  closed: 'status-dot-closed',
  archived: 'status-dot-archived',
}

export function AddToCase({ itemType, itemId, title, content, lat, lng }: Props) {
  const [open, setOpen] = useState(false)
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [adding, setAdding] = useState<string | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) {
      setLoading(true)
      api.get('/cases/?status=open')
        .then((r) => {
          // Also fetch active
          return api.get('/cases/?status=active').then((r2) => {
            const combined = [...(r.data as CaseSummary[]), ...(r2.data as CaseSummary[])]
            // Deduplicate
            const seen = new Set<string>()
            setCases(combined.filter((c) => {
              if (seen.has(c.id)) return false
              seen.add(c.id)
              return true
            }))
          })
        })
        .catch(() => setCases([]))
        .finally(() => setLoading(false))
    }
  }, [open])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSuccess(null)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleAdd = async (caseId: string, caseTitle: string) => {
    setAdding(caseId)
    try {
      await api.post(`/cases/${caseId}/items`, {
        item_type: itemType,
        item_id: itemId || null,
        title: title || null,
        content: content || null,
        lat: lat || null,
        lng: lng || null,
      })
      setSuccess(caseTitle)
      setTimeout(() => {
        setOpen(false)
        setSuccess(null)
      }, 1500)
    } catch (e) {
      console.error('Failed to add to case', e)
    } finally {
      setAdding(null)
    }
  }

  if (success) {
    return (
      <div className="add-to-case-success">
        ✅ Added to "{success}"
      </div>
    )
  }

  return (
    <div className="add-to-case-wrapper" ref={wrapperRef}>
      <button
        className="add-to-case-btn"
        onClick={() => setOpen((v) => !v)}
        title="Add to investigation case"
      >
        🕵️ Add to Case
      </button>

      {open && (
        <div className="add-to-case-dropdown">
          <div className="add-to-case-dropdown__header">Add to Investigation</div>

          {loading ? (
            <div className="add-to-case-dropdown__empty">Loading…</div>
          ) : cases.length === 0 ? (
            <div className="add-to-case-dropdown__empty">No open cases</div>
          ) : (
            cases.map((c) => (
              <div
                key={c.id}
                className="add-to-case-dropdown__item"
                onClick={() => !adding && handleAdd(c.id, c.title)}
              >
                <span className={`add-to-case-dropdown__dot ${STATUS_DOT_CLASS[c.status] || 'status-dot-open'}`} />
                <span className="add-to-case-dropdown__name" title={c.title}>{c.title}</span>
                {adding === c.id && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>…</span>}
              </div>
            ))
          )}

          <div
            className="add-to-case-dropdown__create"
            onClick={() => {
              setOpen(false)
              window.location.href = '/cases'
            }}
          >
            + New Case
          </div>
        </div>
      )}
    </div>
  )
}

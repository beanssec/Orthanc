import React, { useState, useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../services/api'
import './documents.css'

interface DocumentItem {
  id: string
  filename: string
  title: string
  file_type: string
  file_size: number
  pages: number
  char_count: number
  author: string
  timestamp: string | null
  ingested_at: string | null
}

type UploadStep = 'idle' | 'uploading' | 'extracting' | 'ner' | 'done' | 'error'

const ACCEPTED = ['.pdf', '.docx', '.txt', '.md', '.csv']
const ACCEPTED_MIME = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'text/markdown',
  'text/csv',
  'application/octet-stream',
]

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZone: 'UTC', hour12: false,
  }) + ' UTC'
}

const STEP_LABELS: Record<UploadStep, string> = {
  idle: '',
  uploading: 'Uploading file…',
  extracting: 'Extracting text…',
  ner: 'Running entity recognition…',
  done: 'Complete',
  error: 'Upload failed',
}

const TYPE_ICONS: Record<string, string> = {
  pdf: '📄',
  docx: '📝',
  txt: '📃',
  md: '📃',
  csv: '📊',
}

export function DocumentsView() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [dragActive, setDragActive] = useState(false)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [uploadStep, setUploadStep] = useState<UploadStep>('idle')
  const [uploadResult, setUploadResult] = useState<{
    entities_found: number
    events_found: number
    text_length: number
    id: string
  } | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [totalDocs, setTotalDocs] = useState(0)
  const [loadingDocs, setLoadingDocs] = useState(false)

  const loadDocuments = useCallback(async () => {
    setLoadingDocs(true)
    try {
      const res = await api.get('/documents/?page=1&page_size=50')
      const data = res.data as { total: number; items: DocumentItem[] }
      setDocuments(data.items)
      setTotalDocs(data.total)
    } catch (err) {
      console.error('Failed to load documents:', err)
    } finally {
      setLoadingDocs(false)
    }
  }, [])

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
    const file = e.dataTransfer.files[0]
    if (file) {
      setSelectedFile(file)
      setUploadStep('idle')
      setUploadError(null)
      setUploadResult(null)
    }
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setUploadStep('idle')
      setUploadError(null)
      setUploadResult(null)
    }
  }, [])

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return
    setUploadError(null)
    setUploadResult(null)

    // Simulate progress steps — upload first
    setUploadStep('uploading')

    const formData = new FormData()
    formData.append('file', selectedFile)
    if (title.trim()) formData.append('title', title.trim())

    try {
      // Slight delay so "uploading" step is visible
      setUploadStep('extracting')
      const res = await api.post('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setUploadStep('ner')
      // Brief NER step display
      await new Promise((resolve) => setTimeout(resolve, 400))

      const data = res.data as {
        id: string
        entities_found: number
        events_found: number
        text_length: number
      }
      setUploadResult(data)
      setUploadStep('done')

      // Reload list
      await loadDocuments()

      // Reset form after 3s
      setTimeout(() => {
        setSelectedFile(null)
        setTitle('')
        setUploadStep('idle')
        setUploadResult(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
      }, 3000)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Upload failed. Please try again.'
      setUploadError(msg)
      setUploadStep('error')
    }
  }, [selectedFile, title, loadDocuments])

  const handleRowClick = useCallback(
    (doc: DocumentItem) => {
      // Navigate to feed filtered to show this post (by id in the URL hash for now)
      navigate(`/feed?post=${doc.id}`)
    },
    [navigate],
  )

  const isUploading = uploadStep === 'uploading' || uploadStep === 'extracting' || uploadStep === 'ner'

  return (
    <div className="documents-view">
      {/* Header */}
      <div className="documents-header">
        <div>
          <h1 className="documents-title">DOCUMENTS</h1>
          <p className="documents-subtitle">
            Upload intelligence documents for text extraction and entity recognition
          </p>
        </div>
        <div className="documents-count">
          <span className="documents-count__number">{totalDocs}</span>
          <span className="documents-count__label">documents</span>
        </div>
      </div>

      {/* Upload zone */}
      <div className="documents-upload-card">
        <div
          className={`upload-zone${dragActive ? ' upload-zone--active' : ''}${selectedFile ? ' upload-zone--has-file' : ''}`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => !selectedFile && fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click() }}
          aria-label="Upload document"
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED.join(',')}
            onChange={handleFileSelect}
            style={{ display: 'none' }}
          />

          {selectedFile ? (
            <div className="upload-zone__file-info">
              <span className="upload-zone__file-icon">
                {TYPE_ICONS[selectedFile.name.split('.').pop()?.toLowerCase() || ''] || '📄'}
              </span>
              <div className="upload-zone__file-details">
                <div className="upload-zone__file-name">{selectedFile.name}</div>
                <div className="upload-zone__file-meta">
                  {formatBytes(selectedFile.size)} · {selectedFile.name.split('.').pop()?.toUpperCase()}
                </div>
              </div>
              <button
                className="upload-zone__remove-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedFile(null)
                  setUploadStep('idle')
                  setUploadError(null)
                  setUploadResult(null)
                  if (fileInputRef.current) fileInputRef.current.value = ''
                }}
                title="Remove file"
              >
                ✕
              </button>
            </div>
          ) : (
            <div className="upload-zone__placeholder">
              <div className="upload-zone__icon">📂</div>
              <div className="upload-zone__text">
                <span className="upload-zone__text--primary">Drop a file here</span>
                <span className="upload-zone__text--secondary"> or </span>
                <span className="upload-zone__browse-link">browse</span>
              </div>
              <div className="upload-zone__accepted">
                {ACCEPTED.map((ext) => (
                  <span key={ext} className="upload-zone__type-badge">
                    {ext.toUpperCase().replace('.', '')}
                  </span>
                ))}
              </div>
              <div className="upload-zone__limit">Max 50 MB</div>
            </div>
          )}
        </div>

        {/* Title input */}
        {selectedFile && (
          <div className="upload-title-row">
            <label className="upload-title-label" htmlFor="doc-title">
              Title (optional)
            </label>
            <input
              id="doc-title"
              className="upload-title-input"
              type="text"
              placeholder={selectedFile.name}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              disabled={isUploading}
            />
          </div>
        )}

        {/* Progress steps */}
        {uploadStep !== 'idle' && (
          <div className="upload-progress">
            {(['uploading', 'extracting', 'ner', 'done'] as UploadStep[]).map((step, i) => {
              const steps: UploadStep[] = ['uploading', 'extracting', 'ner', 'done']
              const currentIdx = steps.indexOf(uploadStep)
              const isDone = i < currentIdx || uploadStep === 'done'
              const isActive = step === uploadStep && uploadStep !== 'done' && uploadStep !== 'error'

              if (uploadStep === 'error' && step !== 'done') {
                // Show error instead of done step
              }

              return (
                <div
                  key={step}
                  className={`upload-progress__step${isDone ? ' upload-progress__step--done' : ''}${isActive ? ' upload-progress__step--active' : ''}`}
                >
                  <div className="upload-progress__dot">
                    {isDone ? '✓' : isActive ? <span className="upload-progress__spinner" /> : '○'}
                  </div>
                  <span>{STEP_LABELS[step]}</span>
                </div>
              )
            })}

            {uploadStep === 'error' && (
              <div className="upload-progress__error">
                ✕ {uploadError}
              </div>
            )}

            {uploadStep === 'done' && uploadResult && (
              <div className="upload-progress__result">
                <span className="upload-progress__result-item">
                  ✓ {uploadResult.text_length.toLocaleString()} chars extracted
                </span>
                <span className="upload-progress__result-item">
                  🔗 {uploadResult.entities_found} entities
                </span>
                <span className="upload-progress__result-item">
                  📍 {uploadResult.events_found} geo events
                </span>
                <button
                  className="upload-progress__view-btn"
                  onClick={() => navigate(`/feed?post=${uploadResult.id}`)}
                >
                  View in Feed →
                </button>
              </div>
            )}
          </div>
        )}

        {/* Upload button */}
        {selectedFile && uploadStep === 'idle' && (
          <button
            className="btn btn-primary upload-submit-btn"
            onClick={handleUpload}
            disabled={isUploading}
          >
            Upload &amp; Process
          </button>
        )}

        {selectedFile && isUploading && (
          <button className="btn btn-primary upload-submit-btn" disabled>
            <span className="spinner spinner-sm" style={{ marginRight: 8 }} />
            Processing…
          </button>
        )}
      </div>

      {/* Document list */}
      <div className="document-list-section">
        <div className="document-list-header">
          <h2 className="document-list-title">Uploaded Documents</h2>
          <button
            className="btn btn-ghost"
            onClick={loadDocuments}
            disabled={loadingDocs}
            style={{ fontSize: '12px' }}
          >
            {loadingDocs ? 'Refreshing…' : '↻ Refresh'}
          </button>
        </div>

        {loadingDocs && documents.length === 0 ? (
          <div className="document-list__loading">Loading…</div>
        ) : documents.length === 0 ? (
          <div className="document-list__empty">
            <span style={{ fontSize: 32 }}>📂</span>
            <p>No documents uploaded yet. Upload your first document above.</p>
          </div>
        ) : (
          <div className="document-list">
            <table className="document-table">
              <thead>
                <tr>
                  <th>Title / Filename</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>Characters</th>
                  <th>Date Uploaded</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr
                    key={doc.id}
                    className="document-table__row"
                    onClick={() => handleRowClick(doc)}
                    title="Click to view in Feed"
                  >
                    <td className="document-table__title-cell">
                      <span className="document-table__type-icon">
                        {TYPE_ICONS[doc.file_type] || '📄'}
                      </span>
                      <div>
                        <div className="document-table__title">{doc.title}</div>
                        {doc.title !== doc.filename && (
                          <div className="document-table__filename">{doc.filename}</div>
                        )}
                      </div>
                    </td>
                    <td>
                      <span className="document-table__type-badge">
                        {doc.file_type.toUpperCase()}
                      </span>
                    </td>
                    <td className="document-table__size">{formatBytes(doc.file_size)}</td>
                    <td className="document-table__chars">
                      {doc.char_count.toLocaleString()}
                    </td>
                    <td className="document-table__date">
                      {formatDate(doc.timestamp)}
                    </td>
                    <td>
                      <button
                        className="btn btn-ghost document-table__action-btn"
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate(`/feed?post=${doc.id}`)
                        }}
                        title="View in Feed"
                      >
                        View →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default DocumentsView

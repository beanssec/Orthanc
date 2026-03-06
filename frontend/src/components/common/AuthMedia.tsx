/**
 * AuthMedia — renders an <img> or <video> with Bearer auth by fetching
 * the media via axios and creating a blob URL. Handles loading/error states.
 */
import React, { useEffect, useState, useRef } from 'react'
import api from '../../services/api'

interface AuthImageProps {
  postId: string
  thumb?: boolean
  className?: string
  style?: React.CSSProperties
  alt?: string
  onClick?: (e: React.MouseEvent) => void
}

export const AuthImage: React.FC<AuthImageProps> = ({
  postId,
  thumb = false,
  className,
  style,
  alt = 'Media',
  onClick,
}) => {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(false)
    setSrc(null)

    api
      .get(`/media/${postId}${thumb ? '?thumb=true' : ''}`, { responseType: 'blob' })
      .then((res) => {
        if (cancelled) return
        const blobUrl = URL.createObjectURL(res.data as Blob)
        urlRef.current = blobUrl
        setSrc(blobUrl)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })

    return () => {
      cancelled = true
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
  }, [postId, thumb])

  if (error) return <span style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>Media unavailable</span>
  if (!src) return <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>⏳</span>

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      style={style}
      onClick={onClick}
    />
  )
}

interface AuthVideoProps {
  postId: string
  mime?: string
  style?: React.CSSProperties
}

export const AuthVideo: React.FC<AuthVideoProps> = ({ postId, mime = 'video/mp4', style }) => {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const urlRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(false)
    setSrc(null)

    api
      .get(`/media/${postId}`, { responseType: 'blob' })
      .then((res) => {
        if (cancelled) return
        const blobUrl = URL.createObjectURL(res.data as Blob)
        urlRef.current = blobUrl
        setSrc(blobUrl)
      })
      .catch(() => {
        if (!cancelled) setError(true)
      })

    return () => {
      cancelled = true
      if (urlRef.current) {
        URL.revokeObjectURL(urlRef.current)
        urlRef.current = null
      }
    }
  }, [postId])

  if (error) return <span style={{ fontSize: 11, color: 'var(--text-muted)', fontStyle: 'italic' }}>Video unavailable</span>
  if (!src) return <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>⏳ Loading video…</span>

  return (
    <video controls style={{ width: '100%', maxHeight: 300, borderRadius: 6, background: '#000', ...style }}>
      <source src={src} type={mime} />
      Your browser does not support video playback.
    </video>
  )
}

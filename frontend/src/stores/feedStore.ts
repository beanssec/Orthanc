// Stub — real implementation created by main agent
import { create } from 'zustand'

export interface Post {
  id: string
  source_type: 'telegram' | 'x' | 'rss' | 'reddit' | 'discord' | 'shodan' | 'webhook' | 'firms' | 'flight' | 'ais' | 'cashtag'
  source_id: string
  author: string | null
  content: string | null
  timestamp: string
  ingested_at: string
  event: {
    id: string
    lat: number
    lng: number
    place_name: string | null
    confidence: number
  } | null
  // Media fields (migration 009)
  media_type: 'image' | 'video' | 'document' | null
  media_path: string | null
  media_size_bytes: number | null
  media_mime: string | null
  media_thumbnail_path: string | null
  media_metadata: Record<string, unknown> | null
  authenticity_score: number | null
  authenticity_analysis: string | null
  authenticity_checked_at: string | null
}

export interface FeedFilters {
  source_types: string[]
  keyword: string
  date_from: string | null
  date_to: string | null
}

export interface FeedState {
  posts: Post[]
  filters: FeedFilters
  addPost: (post: Post) => void
  setPosts: (posts: Post[]) => void
  setFilters: (filters: Partial<FeedFilters>) => void
}

export const useFeedStore = create<FeedState>((set) => ({
  posts: [],
  filters: {
    source_types: [],
    keyword: '',
    date_from: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    date_to: null,
  },
  addPost: (post) => set((s) => {
    if (s.posts.some((p) => p.id === post.id)) return s;
    return { posts: [post, ...s.posts].slice(0, 1000) };
  }),
  setPosts: (posts) => set({ posts }),
  setFilters: (filters) =>
    set((s) => ({ filters: { ...s.filters, ...filters } })),
}))

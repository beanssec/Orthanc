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
  author: string | null
  has_media: boolean | null
  media_type: string | null
  has_geo: boolean | null
  location: string | null
  entity: string | null
  min_authenticity: number | null
  max_authenticity: number | null
  sort: 'newest' | 'oldest'
}

export interface FacetItem {
  value: string
  count: number
}

export interface Facets {
  source_types: FacetItem[]
  authors: FacetItem[]
  media_types: FacetItem[]
  has_geo_count: number
  total_posts: number
}

export interface FeedState {
  posts: Post[]
  filters: FeedFilters
  totalCount: number
  facets: Facets | null
  addPost: (post: Post) => void
  setPosts: (posts: Post[]) => void
  setFilters: (filters: Partial<FeedFilters>) => void
  setTotalCount: (count: number) => void
  setFacets: (facets: Facets) => void
}

const DEFAULT_FILTERS: FeedFilters = {
  source_types: [],
  keyword: '',
  date_from: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
  date_to: null,
  author: null,
  has_media: null,
  media_type: null,
  has_geo: null,
  location: null,
  entity: null,
  min_authenticity: null,
  max_authenticity: null,
  sort: 'newest',
}

export const useFeedStore = create<FeedState>((set) => ({
  posts: [],
  filters: DEFAULT_FILTERS,
  totalCount: 0,
  facets: null,
  addPost: (post) => set((s) => {
    if (s.posts.some((p) => p.id === post.id)) return s;
    return { posts: [post, ...s.posts].slice(0, 1000) };
  }),
  setPosts: (posts) => set({ posts }),
  setFilters: (filters) =>
    set((s) => ({ filters: { ...s.filters, ...filters } })),
  setTotalCount: (totalCount) => set({ totalCount }),
  setFacets: (facets) => set({ facets }),
}))

export const DEFAULT_FEED_FILTERS = DEFAULT_FILTERS

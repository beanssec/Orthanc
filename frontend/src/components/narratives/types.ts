// Narrative Intelligence — shared TypeScript interfaces

export interface Narrative {
  id: string;
  title: string;
  summary: string | null;
  status: 'active' | 'stale' | 'resolved';
  first_seen: string;
  last_updated: string;
  post_count: number;
  source_count: number;
  divergence_score: number; // 0-1
  evidence_score: number;   // 0-1
  consensus: string | null; // confirmed, disputed, denied, unverified
  topic_keywords: string[];
}

export interface NarrativePost {
  id: string;
  source_type: string;
  author: string;
  content: string;
  timestamp: string;
  stance: string | null;
  stance_confidence: number | null;
  stance_summary: string | null;
}

export interface Claim {
  id: string;
  claim_text: string;
  claim_type: string;
  status: 'unverified' | 'confirmed' | 'debunked' | 'disputed';
  evidence_count: number;
  first_claimed_at: string | null;
  first_claimed_by: string | null;
  location: { lat: number; lng: number } | null;
}

export interface NarrativeDetail extends Narrative {
  posts: NarrativePost[];
  claims: Claim[];
  stance_by_group: Record<string, { color: string; stances: Record<string, number> }>;
}

export interface SourceGroupResponse {
  id: string;
  name: string;
  display_name: string;
  color: string;
  description: string;
  member_count: number;
  members: { name: string; type: string }[];
}

export interface BiasPoint {
  source_id: string;
  source_name: string;
  source_type: string;
  x: number; // -1 (western) to +1 (eastern)
  y: number; // 0 (unreliable) to 1 (reliable)
  color: string;
  group: string;
}

export interface BiasCompassResponse {
  points: BiasPoint[];
}

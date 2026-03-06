import { create } from 'zustand';
import api from '../services/api';

export interface AlertRule {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  rule_type: 'keyword' | 'velocity' | 'correlation' | 'geo_proximity' | 'silence';
  severity: 'flash' | 'urgent' | 'routine';

  // keyword
  keywords: string[] | null;
  keyword_mode: string | null;
  source_types: string[] | null;

  // velocity
  entity_name: string | null;
  velocity_threshold: number | null;
  velocity_window_minutes: number | null;

  // correlation
  directives: Record<string, unknown> | null;

  // geo_proximity
  geo_lat: number | null;
  geo_lng: number | null;
  geo_radius_km: number | null;
  geo_label: string | null;

  // silence
  silence_entity: string | null;
  silence_source_type: string | null;
  silence_expected_interval_minutes: number | null;
  silence_last_seen: string | null;

  cooldown_minutes: number;
  delivery_channels: string[] | null;
  telegram_chat_id: string | null;
  webhook_url: string | null;

  last_fired_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertEvent {
  id: string;
  rule_id: string;
  user_id: string;
  severity: 'flash' | 'urgent' | 'routine';
  title: string;
  summary: string | null;
  matched_post_ids: string[] | null;
  matched_entities: string[] | null;
  context: Record<string, unknown> | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  fired_at: string;
  rule_name: string | null;
  rule_type: string | null;
}

export interface AlertEventList {
  items: AlertEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface AlertRuleCreate {
  name: string;
  description?: string;
  enabled?: boolean;
  rule_type: string;
  severity: string;
  keywords?: string[];
  keyword_mode?: string;
  source_types?: string[];
  entity_name?: string;
  velocity_threshold?: number;
  velocity_window_minutes?: number;
  directives?: Record<string, unknown>;
  // geo_proximity
  geo_lat?: number;
  geo_lng?: number;
  geo_radius_km?: number;
  geo_label?: string;
  // silence
  silence_entity?: string;
  silence_source_type?: string;
  silence_expected_interval_minutes?: number;
  cooldown_minutes?: number;
  delivery_channels?: string[];
  telegram_chat_id?: string;
  webhook_url?: string;
}

interface AlertState {
  rules: AlertRule[];
  events: AlertEvent[];
  totalEvents: number;
  eventPage: number;
  unacknowledgedCount: number;
  loadingRules: boolean;
  loadingEvents: boolean;
  error: string | null;

  fetchRules: () => Promise<void>;
  fetchEvents: (page?: number, severity?: string | null, acknowledged?: boolean | null) => Promise<void>;
  createRule: (data: AlertRuleCreate) => Promise<AlertRule>;
  updateRule: (id: string, data: Partial<AlertRuleCreate>) => Promise<AlertRule>;
  deleteRule: (id: string) => Promise<void>;
  toggleRule: (id: string, enabled: boolean) => Promise<void>;
  acknowledgeEvent: (id: string) => Promise<void>;
  testRule: (id: string) => Promise<unknown>;
  addIncomingAlert: (event: AlertEvent) => void;
}

export const useAlertStore = create<AlertState>((set, get) => ({
  rules: [],
  events: [],
  totalEvents: 0,
  eventPage: 1,
  unacknowledgedCount: 0,
  loadingRules: false,
  loadingEvents: false,
  error: null,

  fetchRules: async () => {
    set({ loadingRules: true, error: null });
    try {
      const res = await api.get<AlertRule[]>('/alerts/rules/');
      set({ rules: res.data, loadingRules: false });
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      set({ error: msg ?? 'Failed to load rules', loadingRules: false });
    }
  },

  fetchEvents: async (page = 1, severity = null, acknowledged = null) => {
    set({ loadingEvents: true });
    try {
      const params: Record<string, unknown> = { page, page_size: 50 };
      if (severity) params.severity = severity;
      if (acknowledged !== null) params.acknowledged = acknowledged;
      const res = await api.get<AlertEventList>('/alerts/events/', { params });
      const unacked = res.data.items.filter((e) => !e.acknowledged).length;
      set({
        events: res.data.items,
        totalEvents: res.data.total,
        eventPage: page,
        unacknowledgedCount: unacked,
        loadingEvents: false,
      });
    } catch {
      set({ loadingEvents: false });
    }
  },

  createRule: async (data) => {
    const res = await api.post<AlertRule>('/alerts/rules/', data);
    set((s) => ({ rules: [res.data, ...s.rules] }));
    return res.data;
  },

  updateRule: async (id, data) => {
    const res = await api.put<AlertRule>(`/alerts/rules/${id}`, data);
    set((s) => ({
      rules: s.rules.map((r) => (r.id === id ? res.data : r)),
    }));
    return res.data;
  },

  deleteRule: async (id) => {
    await api.delete(`/alerts/rules/${id}`);
    set((s) => ({ rules: s.rules.filter((r) => r.id !== id) }));
  },

  toggleRule: async (id, enabled) => {
    await get().updateRule(id, { enabled });
  },

  acknowledgeEvent: async (id) => {
    const res = await api.post<AlertEvent>(`/alerts/events/${id}/acknowledge`);
    set((s) => ({
      events: s.events.map((e) => (e.id === id ? res.data : e)),
      unacknowledgedCount: Math.max(0, s.unacknowledgedCount - 1),
    }));
  },

  testRule: async (id) => {
    const res = await api.post(`/alerts/rules/${id}/test`);
    return res.data;
  },

  addIncomingAlert: (event) => {
    set((s) => ({
      events: [event, ...s.events].slice(0, 100),
      unacknowledgedCount: s.unacknowledgedCount + 1,
    }));
  },
}));

import { create } from 'zustand';
import api from '../services/api';

// ── Types ──────────────────────────────────────────────────

export interface Holding {
  id: string;
  ticker: string;
  exchange: string;
  quantity: number;
  avg_cost: number | null;
  currency: string | null;
  notes: string | null;
  current_price: number | null;
  market_value: number | null;
  profit_loss: number | null;
  profit_loss_pct: number | null;
}

export interface PortfolioSummary {
  holdings: Holding[];
  total_value: number;
  total_profit_loss: number;
  total_profit_loss_pct: number;
}

export interface Quote {
  ticker: string;
  exchange: string;
  price: number | null;
  change_pct: number | null;
  volume: number | null;
  market_cap: number | null;
  currency: string | null;
  fetched_at: string | null;
}

export interface Watchlist {
  indices: Quote[];
  commodities: Quote[];
  forex: Quote[];
  crypto: Quote[];
}

export interface CashtagPost {
  source_type: string;
  content: string | null;
  author: string | null;
  raw_json: {
    sentiment?: string;
    ticker?: string;
    timestamp?: string;
    [key: string]: unknown;
  };
}

export interface Signal {
  id: string;
  signal_type: string;
  severity: string;
  title: string;
  summary: string;
  affected_tickers: string[];
  trigger_entities: string[];
  trigger_post_count: number;
  portfolio_impact: string | null;
  generated_at: string;
}

export interface EntityMapping {
  id: string;
  entity_name: string;
  entity_type: string;
  ticker: string;
  exchange: string;
  relationship: string;
  confidence: number;
}

// ── Store State ────────────────────────────────────────────

interface FinanceState {
  // Portfolio
  portfolio: PortfolioSummary | null;
  portfolioLoading: boolean;
  portfolioError: string | null;

  // Watchlist
  watchlist: Watchlist | null;
  watchlistLoading: boolean;
  watchlistError: string | null;

  // Cashtags
  cashtags: CashtagPost[];
  cashtagsLoading: boolean;
  cashtagsError: string | null;

  // Signals
  signals: Signal[];
  signalsLoading: boolean;
  signalsError: string | null;
  scanLoading: boolean;
  lastScanAt: string | null;

  // Mappings
  mappings: EntityMapping[];
  mappingsLoading: boolean;
  mappingsError: string | null;

  // Actions
  fetchPortfolio: () => Promise<void>;
  addHolding: (data: {
    ticker: string;
    exchange: string;
    quantity: number;
    avg_cost: number | null;
    notes: string | null;
  }) => Promise<void>;
  updateHolding: (id: string, data: Partial<Holding>) => Promise<void>;
  deleteHolding: (id: string) => Promise<void>;

  fetchWatchlist: () => Promise<void>;
  fetchCashtags: () => Promise<void>;

  fetchSignals: () => Promise<void>;
  scanForSignals: () => Promise<void>;

  fetchMappings: () => Promise<void>;
  addMapping: (data: {
    entity_name: string;
    entity_type: string;
    ticker: string;
    exchange: string;
    relationship: string;
    confidence: number;
  }) => Promise<void>;
  deleteMapping: (id: string) => Promise<void>;
}

// ── Store ──────────────────────────────────────────────────

export const useFinanceStore = create<FinanceState>((set, get) => ({
  portfolio: null,
  portfolioLoading: false,
  portfolioError: null,

  watchlist: null,
  watchlistLoading: false,
  watchlistError: null,

  cashtags: [],
  cashtagsLoading: false,
  cashtagsError: null,

  signals: [],
  signalsLoading: false,
  signalsError: null,
  scanLoading: false,
  lastScanAt: null,

  mappings: [],
  mappingsLoading: false,
  mappingsError: null,

  // ── Portfolio ──
  fetchPortfolio: async () => {
    set({ portfolioLoading: true, portfolioError: null });
    try {
      const res = await api.get('/finance/portfolio');
      set({ portfolio: res.data });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to load portfolio');
      set({ portfolioError: msg });
    } finally {
      set({ portfolioLoading: false });
    }
  },

  addHolding: async (data) => {
    await api.post('/finance/portfolio', data);
    await get().fetchPortfolio();
  },

  updateHolding: async (id, data) => {
    await api.put(`/finance/portfolio/${id}`, data);
    await get().fetchPortfolio();
  },

  deleteHolding: async (id) => {
    await api.delete(`/finance/portfolio/${id}`);
    set((s) => ({
      portfolio: s.portfolio
        ? {
            ...s.portfolio,
            holdings: s.portfolio.holdings.filter((h) => h.id !== id),
          }
        : null,
    }));
    // Re-fetch to update totals
    await get().fetchPortfolio();
  },

  // ── Watchlist ──
  fetchWatchlist: async () => {
    set({ watchlistLoading: true, watchlistError: null });
    try {
      const res = await api.get('/finance/watchlist');
      set({ watchlist: res.data });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to load watchlist');
      set({ watchlistError: msg });
    } finally {
      set({ watchlistLoading: false });
    }
  },

  // ── Cashtags ──
  fetchCashtags: async () => {
    set({ cashtagsLoading: true, cashtagsError: null });
    try {
      const res = await api.get('/finance/cashtags');
      set({ cashtags: res.data });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to load cashtags');
      set({ cashtagsError: msg });
    } finally {
      set({ cashtagsLoading: false });
    }
  },

  // ── Signals ──
  fetchSignals: async () => {
    set({ signalsLoading: true, signalsError: null });
    try {
      const res = await api.get('/finance/signals');
      set({ signals: res.data });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to load signals');
      set({ signalsError: msg });
    } finally {
      set({ signalsLoading: false });
    }
  },

  scanForSignals: async () => {
    set({ scanLoading: true });
    try {
      const res = await api.post('/finance/signals/scan');
      const newSignals: Signal[] = Array.isArray(res.data) ? res.data : [];
      set((s) => ({
        signals: [
          ...newSignals,
          ...s.signals.filter(
            (old) => !newSignals.some((n) => n.id === old.id)
          ),
        ],
        lastScanAt: new Date().toISOString(),
      }));
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Scan failed');
      set({ signalsError: msg });
    } finally {
      set({ scanLoading: false });
    }
  },

  // ── Mappings ──
  fetchMappings: async () => {
    set({ mappingsLoading: true, mappingsError: null });
    try {
      const res = await api.get('/finance/mappings');
      set({ mappings: res.data });
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to load mappings');
      set({ mappingsError: msg });
    } finally {
      set({ mappingsLoading: false });
    }
  },

  addMapping: async (data) => {
    await api.post('/finance/mappings', data);
    await get().fetchMappings();
  },

  deleteMapping: async (id) => {
    await api.delete(`/finance/mappings/${id}`);
    set((s) => ({ mappings: s.mappings.filter((m) => m.id !== id) }));
  },
}));

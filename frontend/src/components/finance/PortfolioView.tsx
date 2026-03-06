import { useEffect, useState, useMemo, useCallback } from 'react';
import { useFinanceStore, type Holding } from '../../stores/financeStore';
import '../../styles/finance.css';

// ── Types ──────────────────────────────────────────────────

type SortKey = 'ticker' | 'exchange' | 'quantity' | 'avg_cost' | 'current_price' | 'market_value' | 'profit_loss' | 'profit_loss_pct';
type SortDir = 'asc' | 'desc';

const EXCHANGES = ['NYSE', 'NASDAQ', 'ASX', 'LSE', 'CRYPTO', 'COMMODITY'];

interface HoldingFormData {
  ticker: string;
  exchange: string;
  quantity: string;
  avg_cost: string;
  notes: string;
}

const EMPTY_FORM: HoldingFormData = {
  ticker: '',
  exchange: 'NYSE',
  quantity: '',
  avg_cost: '',
  notes: '',
};

// ── Helpers ────────────────────────────────────────────────

function fmt(value: number | null | undefined, decimals = 2, prefix = ''): string {
  if (value == null) return '—';
  return prefix + value.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return '—';
  const sign = value >= 0 ? '+' : '';
  return sign + value.toFixed(2) + '%';
}

function plClass(value: number | null | undefined): string {
  if (value == null) return '';
  if (value > 0) return 'fin-positive';
  if (value < 0) return 'fin-negative';
  return 'fin-neutral';
}

// ── Add/Edit Holding Modal ─────────────────────────────────

interface HoldingModalProps {
  initial?: Holding | null;
  onClose: () => void;
  onSave: (data: HoldingFormData) => Promise<void>;
}

function HoldingModal({ initial, onClose, onSave }: HoldingModalProps) {
  const [form, setForm] = useState<HoldingFormData>(
    initial
      ? {
          ticker: initial.ticker,
          exchange: initial.exchange,
          quantity: String(initial.quantity),
          avg_cost: initial.avg_cost != null ? String(initial.avg_cost) : '',
          notes: initial.notes ?? '',
        }
      : EMPTY_FORM
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set(field: keyof HoldingFormData, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.ticker.trim()) { setError('Ticker is required'); return; }
    if (!form.quantity || isNaN(Number(form.quantity)) || Number(form.quantity) <= 0) {
      setError('Quantity must be a positive number');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(form);
      onClose();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to save');
      setError(msg);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fin-modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="fin-modal">
        <div className="fin-modal__title">{initial ? 'Edit Holding' : 'Add Holding'}</div>
        <form className="fin-modal__form" onSubmit={handleSubmit}>
          <div className="fin-form-row">
            <label className="fin-form-label">Ticker *</label>
            <input
              className="input"
              type="text"
              placeholder="e.g. AAPL"
              value={form.ticker}
              onChange={(e) => set('ticker', e.target.value.toUpperCase())}
              autoFocus
              disabled={!!initial}
            />
          </div>
          <div className="fin-form-row">
            <label className="fin-form-label">Exchange</label>
            <select className="select" value={form.exchange} onChange={(e) => set('exchange', e.target.value)}>
              {EXCHANGES.map((ex) => (
                <option key={ex} value={ex}>{ex}</option>
              ))}
            </select>
          </div>
          <div className="fin-form-row">
            <label className="fin-form-label">Quantity *</label>
            <input
              className="input"
              type="number"
              step="any"
              min="0"
              placeholder="e.g. 100"
              value={form.quantity}
              onChange={(e) => set('quantity', e.target.value)}
            />
          </div>
          <div className="fin-form-row">
            <label className="fin-form-label">Avg Cost (per unit)</label>
            <input
              className="input"
              type="number"
              step="any"
              min="0"
              placeholder="e.g. 182.50"
              value={form.avg_cost}
              onChange={(e) => set('avg_cost', e.target.value)}
            />
          </div>
          <div className="fin-form-row">
            <label className="fin-form-label">Notes</label>
            <input
              className="input"
              type="text"
              placeholder="Optional notes…"
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
            />
          </div>

          {error && <div className="fin-error-inline">⚠ {error}</div>}

          <div className="fin-modal__actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? <><span className="spinner spinner-sm" /> Saving…</> : (initial ? '✓ Save Changes' : '+ Add Holding')}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────

export function PortfolioView() {
  const {
    portfolio,
    portfolioLoading,
    portfolioError,
    fetchPortfolio,
    addHolding,
    updateHolding,
    deleteHolding,
  } = useFinanceStore();

  const [sortKey, setSortKey] = useState<SortKey>('ticker');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [showAddModal, setShowAddModal] = useState(false);
  const [editHolding, setEditHolding] = useState<Holding | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  useEffect(() => {
    fetchPortfolio();
  }, [fetchPortfolio]);

  const holdings = portfolio?.holdings ?? [];

  const sorted = useMemo(() => {
    return [...holdings].sort((a, b) => {
      let cmp = 0;
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av == null && bv == null) cmp = 0;
      else if (av == null) cmp = -1;
      else if (bv == null) cmp = 1;
      else if (typeof av === 'string' && typeof bv === 'string') {
        cmp = av.localeCompare(bv);
      } else {
        cmp = (av as number) - (bv as number);
      }
      return sortDir === 'desc' ? -cmp : cmp;
    });
  }, [holdings, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return <span className="portfolio-table__sort-icon">↕</span>;
    return <span className="portfolio-table__sort-icon">{sortDir === 'desc' ? '↓' : '↑'}</span>;
  }

  const handleAdd = useCallback(async (form: HoldingFormData) => {
    await addHolding({
      ticker: form.ticker.trim().toUpperCase(),
      exchange: form.exchange,
      quantity: Number(form.quantity),
      avg_cost: form.avg_cost ? Number(form.avg_cost) : null,
      notes: form.notes.trim() || null,
    });
  }, [addHolding]);

  const handleEdit = useCallback(async (form: HoldingFormData) => {
    if (!editHolding) return;
    await updateHolding(editHolding.id, {
      quantity: Number(form.quantity),
      avg_cost: form.avg_cost ? Number(form.avg_cost) : null,
      notes: form.notes.trim() || null,
    });
  }, [editHolding, updateHolding]);

  async function handleDelete(id: string) {
    setDeleteLoading(true);
    try {
      await deleteHolding(id);
    } finally {
      setDeleteLoading(false);
      setDeleteConfirmId(null);
    }
  }

  const totalValue = portfolio?.total_value ?? null;
  const totalPL = portfolio?.total_profit_loss ?? null;
  const totalPLPct = portfolio?.total_profit_loss_pct ?? null;

  return (
    <div className="portfolio-view">
      {/* ── Header ── */}
      <div className="portfolio-header">
        <span className="portfolio-header__title">📊 Portfolio</span>
        <button className="btn btn-primary" onClick={() => setShowAddModal(true)}>
          + Add Holding
        </button>
      </div>

      {/* ── Summary strip ── */}
      {portfolio && (
        <div className="portfolio-summary">
          <div className="portfolio-summary__cell">
            <div className="portfolio-summary__label">Total Value</div>
            <div className="portfolio-summary__value">{fmt(totalValue, 2, '$')}</div>
          </div>
          <div className="portfolio-summary__cell">
            <div className="portfolio-summary__label">Total P&amp;L</div>
            <div className={`portfolio-summary__value ${plClass(totalPL)}`}>
              {totalPL != null ? (totalPL >= 0 ? '+' : '') + fmt(totalPL, 2, '$') : '—'}
            </div>
          </div>
          <div className="portfolio-summary__cell">
            <div className="portfolio-summary__label">P&amp;L %</div>
            <div className={`portfolio-summary__value ${plClass(totalPLPct)}`}>
              {fmtPct(totalPLPct)}
            </div>
          </div>
          <div className="portfolio-summary__cell">
            <div className="portfolio-summary__label">Holdings</div>
            <div className="portfolio-summary__value">{holdings.length}</div>
          </div>
        </div>
      )}

      {/* ── Holdings table ── */}
      {portfolioLoading && !portfolio ? (
        <div className="fin-loading">
          <span className="spinner" /> Loading portfolio…
        </div>
      ) : portfolioError ? (
        <div className="fin-error">⚠ {portfolioError}</div>
      ) : (
        <div className="portfolio-table-wrap">
          {holdings.length === 0 ? (
            <div className="portfolio-empty">
              <div className="portfolio-empty__icon">📊</div>
              <div style={{ fontWeight: 600, color: 'var(--text-secondary)', fontSize: 14 }}>
                No holdings yet
              </div>
              <div>Add your first holding to start tracking portfolio performance</div>
              <button className="btn btn-primary" style={{ marginTop: 8 }} onClick={() => setShowAddModal(true)}>
                + Add Holding
              </button>
            </div>
          ) : (
            <table className="portfolio-table">
              <thead>
                <tr>
                  <th onClick={() => handleSort('ticker')}>Ticker {sortIcon('ticker')}</th>
                  <th onClick={() => handleSort('exchange')}>Exchange {sortIcon('exchange')}</th>
                  <th className="num" onClick={() => handleSort('quantity')}>Qty {sortIcon('quantity')}</th>
                  <th className="num" onClick={() => handleSort('avg_cost')}>Avg Cost {sortIcon('avg_cost')}</th>
                  <th className="num" onClick={() => handleSort('current_price')}>Curr Price {sortIcon('current_price')}</th>
                  <th className="num" onClick={() => handleSort('market_value')}>Mkt Value {sortIcon('market_value')}</th>
                  <th className="num" onClick={() => handleSort('profit_loss')}>P&amp;L ($) {sortIcon('profit_loss')}</th>
                  <th className="num" onClick={() => handleSort('profit_loss_pct')}>P&amp;L % {sortIcon('profit_loss_pct')}</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((h) => {
                  const isDeleteConfirm = deleteConfirmId === h.id;
                  return (
                    <tr key={h.id}>
                      <td className="ticker-cell">{h.ticker}</td>
                      <td className="text-cell">{h.exchange}</td>
                      <td className="num">{h.quantity.toLocaleString()}</td>
                      <td className="num">{fmt(h.avg_cost, 2, '$')}</td>
                      <td className="num">{fmt(h.current_price, 2, '$')}</td>
                      <td className="num">{fmt(h.market_value, 2, '$')}</td>
                      <td className={`num ${plClass(h.profit_loss)}`}>
                        {h.profit_loss != null ? (h.profit_loss >= 0 ? '+' : '') + fmt(h.profit_loss, 2, '$') : '—'}
                      </td>
                      <td className={`num ${plClass(h.profit_loss_pct)}`}>
                        {fmtPct(h.profit_loss_pct)}
                      </td>
                      <td>
                        {isDeleteConfirm ? (
                          <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Delete?</span>
                            <button
                              className="btn btn-danger btn-sm"
                              disabled={deleteLoading}
                              onClick={() => handleDelete(h.id)}
                            >
                              {deleteLoading ? '…' : 'Yes'}
                            </button>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => setDeleteConfirmId(null)}
                            >
                              No
                            </button>
                          </span>
                        ) : (
                          <span style={{ display: 'flex', gap: 4 }}>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={() => setEditHolding(h)}
                            >
                              ✎ Edit
                            </button>
                            <button
                              className="btn btn-ghost btn-sm"
                              style={{ color: 'var(--danger)' }}
                              onClick={() => setDeleteConfirmId(h.id)}
                            >
                              🗑
                            </button>
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Modals ── */}
      {showAddModal && (
        <HoldingModal onClose={() => setShowAddModal(false)} onSave={handleAdd} />
      )}
      {editHolding && (
        <HoldingModal
          initial={editHolding}
          onClose={() => setEditHolding(null)}
          onSave={handleEdit}
        />
      )}
    </div>
  );
}

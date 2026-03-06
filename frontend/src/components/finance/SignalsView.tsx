import { useEffect, useState, useMemo } from 'react';
import { useFinanceStore, type Signal } from '../../stores/financeStore';
import '../../styles/finance.css';

// ── Types ──────────────────────────────────────────────────

type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low';
type TypeFilter = 'all' | 'opportunity' | 'risk' | 'impact';

// ── Helpers ────────────────────────────────────────────────

function formatDateTime(ts: string): string {
  return new Date(ts).toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
  return Math.floor(seconds / 86400) + 'd ago';
}

function severityIcon(sev: string): string {
  switch (sev.toLowerCase()) {
    case 'critical': return '🔴';
    case 'high': return '🟠';
    case 'medium': return '🟡';
    case 'low': return '🔵';
    default: return '⚪';
  }
}

function relBadgeClass(rel: string): string {
  switch (rel.toLowerCase()) {
    case 'direct': return 'rel-badge--direct';
    case 'sector': return 'rel-badge--sector';
    case 'geopolitical': return 'rel-badge--geopolitical';
    case 'supply_chain': case 'supply chain': return 'rel-badge--supply-chain';
    default: return 'rel-badge--direct';
  }
}

function relLabel(rel: string): string {
  return rel.replace('_', ' ').toUpperCase();
}

// ── Signal Card ────────────────────────────────────────────

interface SignalCardProps {
  signal: Signal;
  expanded: boolean;
  onToggle: () => void;
}

function SignalCard({ signal, expanded, onToggle }: SignalCardProps) {
  const sev = signal.severity.toLowerCase();
  const type = signal.signal_type.toLowerCase();

  return (
    <div className={`signal-card signal-card--${sev}`}>
      {/* Header (clickable) */}
      <div className="signal-card__header" onClick={onToggle}>
        <div className="signal-card__badges">
          <span className={`signal-badge signal-badge--${sev}`}>
            {severityIcon(signal.severity)} {signal.severity.toUpperCase()}
          </span>
          <span className={`signal-badge signal-badge--${type}`}>
            {type.toUpperCase()}
          </span>
        </div>
        <div className="signal-card__title-wrap">
          <div className="signal-card__title">{signal.title}</div>
          {/* Inline metadata chips — always visible */}
          <div className="signal-card__meta-chips">
            {signal.affected_tickers?.length > 0 && signal.affected_tickers.map((t) => (
              <span key={t} className="signal-ticker-tag">${t}</span>
            ))}
            {signal.trigger_entities?.length > 0 && signal.trigger_entities.slice(0, 3).map((e) => (
              <span key={e} className="signal-entity-tag">{e}</span>
            ))}
            {signal.trigger_post_count > 0 && (
              <span className="signal-post-count-tag">Based on {signal.trigger_post_count} posts</span>
            )}
          </div>
          {!expanded && (
            <div className="signal-card__summary-preview">{signal.summary}</div>
          )}
        </div>
        <div className="signal-card__header-right">
          <span className="signal-card__timestamp">{timeAgo(signal.generated_at)}</span>
          <div className="signal-card__chevron">{expanded ? '▲' : '▼'}</div>
        </div>
      </div>

      {/* Expanded body */}
      {expanded && (
        <div className="signal-card__body">
          {/* Summary */}
          <div className="signal-card__summary">{signal.summary}</div>

          {/* Portfolio impact */}
          {signal.portfolio_impact && (
            <div className="signal-card__impact">
              💼 {signal.portfolio_impact}
            </div>
          )}

          {/* Footer */}
          <div className="signal-card__footer">
            <span>{formatDateTime(signal.generated_at)}</span>
            <span className="signal-card__footer-sep">·</span>
            <span>{signal.trigger_post_count} posts triggered</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Mapping Form ───────────────────────────────────────────

interface MappingFormData {
  entity_name: string;
  entity_type: string;
  ticker: string;
  exchange: string;
  relationship: string;
  confidence: string;
}

const EMPTY_MAPPING: MappingFormData = {
  entity_name: '',
  entity_type: 'ORG',
  ticker: '',
  exchange: 'NYSE',
  relationship: 'DIRECT',
  confidence: '0.8',
};

const ENTITY_TYPES_LIST = ['ORG', 'PERSON', 'GPE', 'EVENT', 'NORP', 'OTHER'];
const RELATIONSHIPS = ['DIRECT', 'SECTOR', 'GEOPOLITICAL', 'SUPPLY_CHAIN'];
const EXCHANGES = ['NYSE', 'NASDAQ', 'ASX', 'LSE', 'CRYPTO', 'COMMODITY'];

// ── Mappings Section ───────────────────────────────────────

function MappingsSection() {
  const { mappings, mappingsLoading, mappingsError, fetchMappings, addMapping, deleteMapping } =
    useFinanceStore();

  const [open, setOpen] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [form, setForm] = useState<MappingFormData>(EMPTY_MAPPING);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  useEffect(() => {
    if (open && mappings.length === 0 && !mappingsLoading) {
      fetchMappings();
    }
  }, [open, mappings.length, mappingsLoading, fetchMappings]);

  function setF(field: keyof MappingFormData, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!form.entity_name.trim()) { setFormError('Entity name required'); return; }
    if (!form.ticker.trim()) { setFormError('Ticker required'); return; }
    const conf = Number(form.confidence);
    if (isNaN(conf) || conf < 0 || conf > 1) { setFormError('Confidence must be 0.0–1.0'); return; }
    setSaving(true);
    setFormError(null);
    try {
      await addMapping({
        entity_name: form.entity_name.trim(),
        entity_type: form.entity_type,
        ticker: form.ticker.trim().toUpperCase(),
        exchange: form.exchange,
        relationship: form.relationship,
        confidence: conf,
      });
      setForm(EMPTY_MAPPING);
      setShowAddForm(false);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Failed to save');
      setFormError(msg);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string) {
    await deleteMapping(id);
    setDeleteConfirmId(null);
  }

  return (
    <div className="mappings-section">
      {/* Toggle header */}
      <div
        className={`mappings-section__toggle ${open ? 'mappings-section__toggle-open' : ''}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="mappings-section__toggle-title">
          🔗 OSINT → Finance Mappings
          <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>
            ({mappings.length || '…'} entities)
          </span>
        </span>
        <span className="mappings-section__toggle-chevron">{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div className="mappings-section__body">
          {/* Header row */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span className="fin-section-title" style={{ marginBottom: 0 }}>Entity → Ticker Mappings</span>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setShowAddForm((v) => !v)}
            >
              {showAddForm ? '✕ Cancel' : '+ Add Mapping'}
            </button>
          </div>

          {/* Add form */}
          {showAddForm && (
            <form className="mapping-add-form" onSubmit={handleAdd}>
              <div className="fin-form-row">
                <label className="fin-form-label">Entity Name</label>
                <input className="input" placeholder="e.g. Tesla Inc." value={form.entity_name} onChange={(e) => setF('entity_name', e.target.value)} />
              </div>
              <div className="fin-form-row">
                <label className="fin-form-label">Entity Type</label>
                <select className="select" value={form.entity_type} onChange={(e) => setF('entity_type', e.target.value)}>
                  {ENTITY_TYPES_LIST.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="fin-form-row">
                <label className="fin-form-label">Ticker</label>
                <input className="input" placeholder="TSLA" value={form.ticker} onChange={(e) => setF('ticker', e.target.value.toUpperCase())} />
              </div>
              <div className="fin-form-row">
                <label className="fin-form-label">Exchange</label>
                <select className="select" value={form.exchange} onChange={(e) => setF('exchange', e.target.value)}>
                  {EXCHANGES.map((ex) => <option key={ex} value={ex}>{ex}</option>)}
                </select>
              </div>
              <div className="fin-form-row">
                <label className="fin-form-label">Relationship</label>
                <select className="select" value={form.relationship} onChange={(e) => setF('relationship', e.target.value)}>
                  {RELATIONSHIPS.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div className="fin-form-row">
                <label className="fin-form-label">Confidence (0–1)</label>
                <input className="input" type="number" step="0.1" min="0" max="1" value={form.confidence} onChange={(e) => setF('confidence', e.target.value)} />
              </div>
              {formError && <div className="fin-error-inline" style={{ gridColumn: '1 / -1' }}>⚠ {formError}</div>}
              <div className="mapping-add-form__actions">
                <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
                  {saving ? <><span className="spinner spinner-sm" /> Saving…</> : '+ Add Mapping'}
                </button>
              </div>
            </form>
          )}

          {/* Table */}
          {mappingsLoading ? (
            <div className="fin-loading"><span className="spinner" /> Loading mappings…</div>
          ) : mappingsError ? (
            <div className="fin-error">⚠ {mappingsError}</div>
          ) : (
            <div className="mappings-table-wrap">
              <table className="mappings-table">
                <thead>
                  <tr>
                    <th>Entity</th>
                    <th>Type</th>
                    <th>Ticker</th>
                    <th>Exchange</th>
                    <th>Relationship</th>
                    <th>Confidence</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {mappings.length === 0 ? (
                    <tr>
                      <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>
                        No mappings configured
                      </td>
                    </tr>
                  ) : (
                    mappings.map((m) => {
                      const isDelConfirm = deleteConfirmId === m.id;
                      return (
                        <tr key={m.id}>
                          <td>{m.entity_name}</td>
                          <td>
                            <span className="signal-entity-tag">{m.entity_type}</span>
                          </td>
                          <td className="ticker-cell">{m.ticker}</td>
                          <td>{m.exchange}</td>
                          <td>
                            <span className={`rel-badge ${relBadgeClass(m.relationship)}`}>
                              {relLabel(m.relationship)}
                            </span>
                          </td>
                          <td className="conf-cell">{(m.confidence * 100).toFixed(0)}%</td>
                          <td>
                            {isDelConfirm ? (
                              <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                                <button className="btn btn-danger btn-sm" onClick={() => handleDelete(m.id)}>
                                  Yes
                                </button>
                                <button className="btn btn-secondary btn-sm" onClick={() => setDeleteConfirmId(null)}>
                                  No
                                </button>
                              </span>
                            ) : (
                              <button
                                className="btn btn-ghost btn-sm"
                                style={{ color: 'var(--danger)' }}
                                onClick={() => setDeleteConfirmId(m.id)}
                              >
                                🗑
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────

export function SignalsView() {
  const {
    signals,
    signalsLoading,
    signalsError,
    scanLoading,
    lastScanAt,
    fetchSignals,
    scanForSignals,
  } = useFinanceStore();

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  const [scanError, setScanError] = useState<string | null>(null);

  useEffect(() => {
    fetchSignals();
  }, [fetchSignals]);

  const filtered = useMemo(() => {
    let list = signals;
    if (severityFilter !== 'all') {
      list = list.filter((s) => s.severity.toLowerCase() === severityFilter);
    }
    if (typeFilter !== 'all') {
      list = list.filter((s) => s.signal_type.toLowerCase() === typeFilter);
    }
    return list;
  }, [signals, severityFilter, typeFilter]);

  async function handleScan() {
    setScanError(null);
    try {
      await scanForSignals();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err instanceof Error ? err.message : 'Scan failed');
      setScanError(msg);
    }
  }

  return (
    <div className="signals-view">
      {/* ── Header ── */}
      <div className="signals-header">
        <span className="signals-header__title">🔔 Signals</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {filtered.length} signal{filtered.length !== 1 ? 's' : ''}
          {severityFilter !== 'all' || typeFilter !== 'all' ? ' (filtered)' : ''}
        </span>
      </div>

      {/* ── Action bar ── */}
      <div className="signals-actionbar">
        <div className="signals-actionbar__scan">
          <button
            className="btn btn-primary"
            disabled={scanLoading}
            onClick={handleScan}
          >
            {scanLoading ? (
              <><span className="spinner spinner-sm" /> Scanning…</>
            ) : (
              '🔍 Scan for Opportunities'
            )}
          </button>
          {lastScanAt && (
            <span className="signals-actionbar__last-scan">
              Last scan: {new Date(lastScanAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>

        <div className="signals-actionbar__filters">
          <span className="signals-actionbar__filter-label">Severity:</span>
          <select
            className="select select-sm"
            style={{ width: 110 }}
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value as SeverityFilter)}
          >
            <option value="all">All</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>

          <span className="signals-actionbar__filter-label">Type:</span>
          <select
            className="select select-sm"
            style={{ width: 120 }}
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
          >
            <option value="all">All</option>
            <option value="opportunity">Opportunity</option>
            <option value="risk">Risk</option>
            <option value="impact">Impact</option>
          </select>
        </div>
      </div>

      {/* ── Error states ── */}
      {scanError && <div className="signals-error">⚠ Scan error: {scanError}</div>}
      {signalsError && <div className="signals-error">⚠ {signalsError}</div>}

      {/* ── Signals feed ── */}
      {signalsLoading && signals.length === 0 ? (
        <div className="fin-loading">
          <span className="spinner" /> Loading signals…
        </div>
      ) : filtered.length === 0 ? (
        <div className="signals-empty">
          <div className="signals-empty__icon">🔔</div>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', fontSize: 14 }}>
            {signals.length === 0 ? 'No signals yet' : 'No signals match filters'}
          </div>
          <div>
            {signals.length === 0
              ? "Click 'Scan for Opportunities' to analyze current OSINT data for financial signals."
              : 'Try changing severity or type filters.'}
          </div>
        </div>
      ) : (
        <div className="signals-feed">
          {filtered.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              expanded={expandedId === signal.id}
              onToggle={() => setExpandedId((prev) => (prev === signal.id ? null : signal.id))}
            />
          ))}
        </div>
      )}

      {/* ── Mappings section ── */}
      <MappingsSection />
    </div>
  );
}

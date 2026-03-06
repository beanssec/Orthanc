import { useState, useEffect, useRef, KeyboardEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useAlertStore } from '../../stores/alertStore';
import type { AlertRule, AlertRuleCreate } from '../../stores/alertStore';
import { LoadingSpinner } from '../common/LoadingSpinner';
import { Modal } from '../common/Modal';
import { ConfirmDialog } from '../common/ConfirmDialog';
import '../../styles/alerts.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SEVERITY_EMOJI: Record<string, string> = {
  flash: '🔴',
  urgent: '🟠',
  routine: '🔵',
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`badge badge-severity-${severity}`}>
      {SEVERITY_EMOJI[severity] ?? '🔔'} {severity.toUpperCase()}
    </span>
  );
}

function TypeBadge({ type }: { type: string }) {
  return <span className={`badge badge-type-${type}`}>{type.toUpperCase()}</span>;
}

function formatRelative(iso: string | null): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// Keyword tags input
// ---------------------------------------------------------------------------

function KeywordTagsInput({
  value,
  onChange,
}: {
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const addTag = () => {
    const tag = input.trim();
    if (tag && !value.includes(tag)) {
      onChange([...value, tag]);
    }
    setInput('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag();
    } else if (e.key === 'Backspace' && !input && value.length > 0) {
      onChange(value.slice(0, -1));
    }
  };

  return (
    <div className="keyword-tags" onClick={() => inputRef.current?.focus()}>
      {value.map((kw) => (
        <span key={kw} className="keyword-tag">
          {kw}
          <button
            className="keyword-tag-remove"
            onClick={(e) => { e.stopPropagation(); onChange(value.filter((k) => k !== kw)); }}
          >
            ×
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        className="keyword-tags-input"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={addTag}
        placeholder={value.length === 0 ? 'Type keyword + Enter' : ''}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Severity selector
// ---------------------------------------------------------------------------

function SeveritySelector({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const opts = ['routine', 'urgent', 'flash'];
  return (
    <div className="severity-selector">
      {opts.map((s) => (
        <button
          key={s}
          className={`severity-btn severity-btn-${s}${value === s ? ` selected-${s}` : ''}`}
          onClick={() => onChange(s)}
          type="button"
        >
          {SEVERITY_EMOJI[s]} {s}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Correlation stage builder
// ---------------------------------------------------------------------------

interface StageCondition {
  type: 'keyword_match' | 'entity_velocity' | 'source_count';
  keywords?: string[];
  mode?: string;
  entities?: string[];
  threshold?: number;
  window_minutes?: number;
  min_sources?: number;
}

interface Stage {
  stage: number;
  condition: StageCondition;
  time_window_minutes?: number;
  severity: string;
}

function CorrelationStageBuilder({
  stages,
  onChange,
}: {
  stages: Stage[];
  onChange: (s: Stage[]) => void;
}) {
  const updateStage = (idx: number, patch: Partial<Stage>) => {
    const updated = stages.map((s, i) => (i === idx ? { ...s, ...patch } : s));
    onChange(updated);
  };

  const updateCondition = (idx: number, patch: Partial<StageCondition>) => {
    updateStage(idx, { condition: { ...stages[idx].condition, ...patch } });
  };

  const addStage = () => {
    if (stages.length >= 3) return;
    onChange([
      ...stages,
      {
        stage: stages.length + 1,
        condition: { type: 'keyword_match', keywords: [] },
        time_window_minutes: 60,
        severity: 'urgent',
      },
    ]);
  };

  const removeStage = (idx: number) => {
    onChange(stages.filter((_, i) => i !== idx).map((s, i) => ({ ...s, stage: i + 1 })));
  };

  return (
    <div className="correlation-stages">
      {stages.map((stage, idx) => (
        <div key={idx}>
          {idx > 0 && (
            <div className="correlation-stage-arrow">↓ then within</div>
          )}
          <div className="correlation-stage-block">
            <div className="correlation-stage-header">
              <span className="correlation-stage-label">Stage {stage.stage}</span>
              {idx > 0 && (
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ color: 'var(--danger)' }}
                  onClick={() => removeStage(idx)}
                  type="button"
                >
                  ✕ Remove
                </button>
              )}
            </div>

            {idx > 0 && (
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <label className="form-label">Time window from previous stage (minutes)</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={stage.time_window_minutes ?? 60}
                  onChange={(e) => updateStage(idx, { time_window_minutes: +e.target.value })}
                />
              </div>
            )}

            <div className="form-group" style={{ marginBottom: '10px' }}>
              <label className="form-label">Condition Type</label>
              <select
                className="select"
                value={stage.condition.type}
                onChange={(e) =>
                  updateCondition(idx, { type: e.target.value as StageCondition['type'] })
                }
              >
                <option value="keyword_match">Keyword Match</option>
                <option value="entity_velocity">Entity Velocity</option>
                <option value="source_count">Source Count</option>
              </select>
            </div>

            {stage.condition.type === 'keyword_match' && (
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <label className="form-label">Keywords</label>
                <KeywordTagsInput
                  value={stage.condition.keywords ?? []}
                  onChange={(v) => updateCondition(idx, { keywords: v })}
                />
              </div>
            )}

            {stage.condition.type === 'entity_velocity' && (
              <>
                <div className="form-group" style={{ marginBottom: '10px' }}>
                  <label className="form-label">Entities (comma-separated)</label>
                  <input
                    className="input"
                    type="text"
                    placeholder="Iran, Israel, Russia"
                    value={(stage.condition.entities ?? []).join(', ')}
                    onChange={(e) =>
                      updateCondition(idx, {
                        entities: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                      })
                    }
                  />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                  <div className="form-group">
                    <label className="form-label">Threshold (x baseline)</label>
                    <input
                      className="input"
                      type="number"
                      min={1}
                      step={0.5}
                      value={stage.condition.threshold ?? 3}
                      onChange={(e) => updateCondition(idx, { threshold: +e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Window (minutes)</label>
                    <input
                      className="input"
                      type="number"
                      min={5}
                      value={stage.condition.window_minutes ?? 60}
                      onChange={(e) => updateCondition(idx, { window_minutes: +e.target.value })}
                    />
                  </div>
                </div>
              </>
            )}

            {stage.condition.type === 'source_count' && (
              <div className="form-group" style={{ marginBottom: '10px' }}>
                <label className="form-label">Minimum sources</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  value={stage.condition.min_sources ?? 3}
                  onChange={(e) => updateCondition(idx, { min_sources: +e.target.value })}
                />
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Severity at this stage</label>
              <SeveritySelector
                value={stage.severity}
                onChange={(v) => updateStage(idx, { severity: v })}
              />
            </div>
          </div>
        </div>
      ))}

      {stages.length < 3 && (
        <button className="btn btn-secondary btn-sm" onClick={addStage} type="button">
          + Add Stage
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard — Step 1: Rule Type
// ---------------------------------------------------------------------------

function Step1RuleType({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const types = [
    {
      id: 'keyword',
      icon: '🎯',
      title: 'Keyword Match',
      desc: 'Fire immediately when incoming posts contain matching keywords or regex patterns.',
    },
    {
      id: 'velocity',
      icon: '📈',
      title: 'Entity Velocity',
      desc: 'Alert when an entity is mentioned significantly more than its 7-day baseline.',
    },
    {
      id: 'correlation',
      icon: '🔗',
      title: 'Correlation Rule',
      desc: 'Multi-stage OSSIM-style directives. Stage 1 opens a window; Stage 2+ must match within it.',
    },
    {
      id: 'geo_proximity',
      icon: '📍',
      title: 'Geo-Proximity',
      desc: 'Alert when an event occurs within a specified radius of a geographic location.',
    },
    {
      id: 'silence',
      icon: '🔇',
      title: 'Silence Detection',
      desc: "Alert if we don't hear from an entity or source for a specified period.",
    },
  ];

  return (
    <div className="rule-type-cards">
      {types.map((t) => (
        <button
          key={t.id}
          className={`rule-type-card${value === t.id ? ' selected' : ''}`}
          onClick={() => onChange(t.id)}
          type="button"
        >
          <div className="rule-type-card-icon">{t.icon}</div>
          <div className="rule-type-card-title">{t.title}</div>
          <div className="rule-type-card-desc">{t.desc}</div>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard — Step 2: Configure Conditions
// ---------------------------------------------------------------------------

interface ConditionState {
  // keyword
  keywords: string[];
  keyword_mode: string;
  source_types: string[];
  severity: string;
  // velocity
  entity_name: string;
  velocity_threshold: number;
  velocity_window_minutes: number;
  // correlation
  stages: Stage[];
  // geo_proximity
  geo_lat: number;
  geo_lng: number;
  geo_radius_km: number;
  geo_label: string;
  // silence
  silence_entity: string;
  silence_source_type: string;
  silence_expected_hours: number;
}

function Step2Conditions({
  ruleType,
  cond,
  onChange,
}: {
  ruleType: string;
  cond: ConditionState;
  onChange: (patch: Partial<ConditionState>) => void;
}) {
  const sourceOptions = ['telegram', 'x', 'rss', 'reddit', 'discord', 'webhook'];

  if (ruleType === 'keyword') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div className="form-group">
          <label className="form-label">Keywords</label>
          <KeywordTagsInput value={cond.keywords} onChange={(v) => onChange({ keywords: v })} />
          <span className="form-error" style={{ color: 'var(--text-muted)', fontSize: '11px' }}>
            Press Enter or comma to add each keyword
          </span>
        </div>

        <div className="form-group">
          <label className="form-label">Match Mode</label>
          <select
            className="select"
            value={cond.keyword_mode}
            onChange={(e) => onChange({ keyword_mode: e.target.value })}
          >
            <option value="any">Any — match if any keyword found</option>
            <option value="all">All — match only if ALL keywords found</option>
            <option value="regex">Regex — first keyword as pattern</option>
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">Source Filter (optional)</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '4px' }}>
            {sourceOptions.map((src) => (
              <label key={src} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={cond.source_types.includes(src)}
                  onChange={(e) =>
                    onChange({
                      source_types: e.target.checked
                        ? [...cond.source_types, src]
                        : cond.source_types.filter((s) => s !== src),
                    })
                  }
                />
                {src}
              </label>
            ))}
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Severity</label>
          <SeveritySelector value={cond.severity} onChange={(v) => onChange({ severity: v })} />
        </div>
      </div>
    );
  }

  if (ruleType === 'velocity') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div className="form-group">
          <label className="form-label">Entity Name</label>
          <input
            className="input"
            type="text"
            placeholder="e.g. Iran, Russia, NATO"
            value={cond.entity_name}
            onChange={(e) => onChange({ entity_name: e.target.value })}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          <div className="form-group">
            <label className="form-label">Threshold (x baseline)</label>
            <input
              className="input"
              type="number"
              min={1}
              step={0.5}
              placeholder="3.0"
              value={cond.velocity_threshold}
              onChange={(e) => onChange({ velocity_threshold: +e.target.value })}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Window (minutes)</label>
            <input
              className="input"
              type="number"
              min={5}
              placeholder="60"
              value={cond.velocity_window_minutes}
              onChange={(e) => onChange({ velocity_window_minutes: +e.target.value })}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Severity</label>
          <SeveritySelector value={cond.severity} onChange={(v) => onChange({ severity: v })} />
        </div>
      </div>
    );
  }

  if (ruleType === 'geo_proximity') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div className="form-group">
          <label className="form-label">Location Name</label>
          <input
            className="input"
            type="text"
            placeholder="e.g. Baghdad, Tehran, Kyiv"
            value={cond.geo_label}
            onChange={(e) => onChange({ geo_label: e.target.value })}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          <div className="form-group">
            <label className="form-label">Latitude</label>
            <input
              className="input"
              type="number"
              step="0.0001"
              min="-90"
              max="90"
              placeholder="33.3412"
              value={cond.geo_lat || ''}
              onChange={(e) => onChange({ geo_lat: parseFloat(e.target.value) || 0 })}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Longitude</label>
            <input
              className="input"
              type="number"
              step="0.0001"
              min="-180"
              max="180"
              placeholder="44.3975"
              value={cond.geo_lng || ''}
              onChange={(e) => onChange({ geo_lng: parseFloat(e.target.value) || 0 })}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">
            Radius: <strong>{cond.geo_radius_km} km</strong>
            {cond.geo_radius_km >= 1000
              ? ` (~${(cond.geo_radius_km / 1000).toFixed(1)} Mm)`
              : cond.geo_radius_km >= 100
              ? ` (~${(cond.geo_radius_km / 1.609).toFixed(0)} miles)`
              : ''}
          </label>
          <input
            className="input"
            type="range"
            min="1"
            max="500"
            step="1"
            value={cond.geo_radius_km}
            onChange={(e) => onChange({ geo_radius_km: +e.target.value })}
            style={{ padding: '0', marginTop: '4px' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
            <span>1 km</span>
            <span>250 km</span>
            <span>500 km</span>
          </div>
        </div>

        <div className="form-group">
          <label className="form-label">Severity</label>
          <SeveritySelector value={cond.severity} onChange={(v) => onChange({ severity: v })} />
        </div>
      </div>
    );
  }

  if (ruleType === 'silence') {
    const sourceOptions = ['telegram', 'x', 'rss', 'reddit', 'discord', 'webhook'];
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ padding: '10px 12px', background: 'var(--surface-2)', borderRadius: '6px', fontSize: '12px', color: 'var(--text-muted)' }}>
          Choose <strong>either</strong> an entity name <em>or</em> a source type — not both.
        </div>

        <div className="form-group">
          <label className="form-label">Entity Name (monitor a tracked entity)</label>
          <input
            className="input"
            type="text"
            placeholder="e.g. Iran, Hezbollah, Russia"
            value={cond.silence_entity}
            onChange={(e) => onChange({ silence_entity: e.target.value, silence_source_type: e.target.value ? '' : cond.silence_source_type })}
          />
        </div>

        <div style={{ textAlign: 'center', fontSize: '12px', color: 'var(--text-muted)' }}>— or —</div>

        <div className="form-group">
          <label className="form-label">Source Type (monitor an entire feed)</label>
          <select
            className="select"
            value={cond.silence_source_type}
            onChange={(e) => onChange({ silence_source_type: e.target.value, silence_entity: e.target.value ? '' : cond.silence_entity })}
          >
            <option value="">— select source —</option>
            {sourceOptions.map((src) => (
              <option key={src} value={src}>{src}</option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">
            Alert if no activity for <strong>{cond.silence_expected_hours}h</strong>
          </label>
          <input
            className="input"
            type="number"
            min="0.5"
            max="168"
            step="0.5"
            value={cond.silence_expected_hours}
            onChange={(e) => onChange({ silence_expected_hours: +e.target.value })}
          />
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '3px' }}>
            Checked every 5 minutes. Minimum 0.5h (30 min).
          </span>
        </div>

        <div className="form-group">
          <label className="form-label">Severity</label>
          <SeveritySelector value={cond.severity} onChange={(v) => onChange({ severity: v })} />
        </div>
      </div>
    );
  }

  // correlation
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <CorrelationStageBuilder
        stages={cond.stages}
        onChange={(s) => onChange({ stages: s })}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard — Step 3: Delivery & Review
// ---------------------------------------------------------------------------

interface DeliveryState {
  name: string;
  description: string;
  delivery_channels: string[];
  telegram_chat_id: string;
  webhook_url: string;
  cooldown_minutes: number;
}

function Step3Delivery({
  ruleType,
  cond,
  delivery,
  onChange,
}: {
  ruleType: string;
  cond: ConditionState;
  delivery: DeliveryState;
  onChange: (patch: Partial<DeliveryState>) => void;
}) {
  const toggleChannel = (ch: string) => {
    const channels = delivery.delivery_channels.includes(ch)
      ? delivery.delivery_channels.filter((c) => c !== ch)
      : [...delivery.delivery_channels, ch];
    onChange({ delivery_channels: channels });
  };

  const reviewRows: Array<{ label: string; value: string }> = [
    { label: 'Type', value: ruleType.replace('_', ' ').toUpperCase() },
    { label: 'Severity', value: (cond.severity ?? '—').toUpperCase() },
    ...(ruleType === 'keyword'
      ? [
          { label: 'Keywords', value: cond.keywords.join(', ') || '—' },
          { label: 'Mode', value: cond.keyword_mode },
        ]
      : ruleType === 'velocity'
      ? [
          { label: 'Entity', value: cond.entity_name || '—' },
          { label: 'Threshold', value: `${cond.velocity_threshold}x` },
          { label: 'Window', value: `${cond.velocity_window_minutes} min` },
        ]
      : ruleType === 'geo_proximity'
      ? [
          { label: 'Location', value: cond.geo_label || `${cond.geo_lat}, ${cond.geo_lng}` },
          { label: 'Center', value: `${cond.geo_lat}, ${cond.geo_lng}` },
          { label: 'Radius', value: `${cond.geo_radius_km} km` },
        ]
      : ruleType === 'silence'
      ? [
          { label: 'Monitor', value: cond.silence_entity || cond.silence_source_type || '—' },
          { label: 'Silence after', value: `${cond.silence_expected_hours}h` },
        ]
      : [{ label: 'Stages', value: `${cond.stages.length} stage(s)` }]),
    { label: 'Channels', value: delivery.delivery_channels.join(', ') || 'none' },
    { label: 'Cooldown', value: `${delivery.cooldown_minutes} min` },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
        <div className="form-group">
          <label className="form-label">Rule Name *</label>
          <input
            className="input"
            type="text"
            placeholder="e.g. Nuclear Keyword Alert"
            value={delivery.name}
            onChange={(e) => onChange({ name: e.target.value })}
          />
        </div>
        <div className="form-group">
          <label className="form-label">Cooldown (minutes)</label>
          <input
            className="input"
            type="number"
            min={1}
            value={delivery.cooldown_minutes}
            onChange={(e) => onChange({ cooldown_minutes: +e.target.value })}
          />
        </div>
      </div>

      <div className="form-group">
        <label className="form-label">Description (optional)</label>
        <input
          className="input"
          type="text"
          placeholder="What this rule monitors"
          value={delivery.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      </div>

      <div className="form-group">
        <label className="form-label">Delivery Channels</label>
        <div style={{ display: 'flex', gap: '12px', marginTop: '6px' }}>
          {['in_app', 'telegram', 'webhook'].map((ch) => (
            <label key={ch} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={delivery.delivery_channels.includes(ch)}
                onChange={() => toggleChannel(ch)}
              />
              {ch === 'in_app' ? '🔔 In-App' : ch === 'telegram' ? '📱 Telegram' : '🔗 Webhook'}
            </label>
          ))}
        </div>
      </div>

      {delivery.delivery_channels.includes('telegram') && (
        <div className="form-group">
          <label className="form-label">Telegram Chat ID</label>
          <input
            className="input"
            type="text"
            placeholder="e.g. 123456789"
            value={delivery.telegram_chat_id}
            onChange={(e) => onChange({ telegram_chat_id: e.target.value })}
          />
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '3px' }}>
            Bot must be added to your Telegram chat first
          </span>
        </div>
      )}

      {delivery.delivery_channels.includes('webhook') && (
        <div className="form-group">
          <label className="form-label">Webhook URL</label>
          <input
            className="input"
            type="url"
            placeholder="https://hooks.example.com/..."
            value={delivery.webhook_url}
            onChange={(e) => onChange({ webhook_url: e.target.value })}
          />
        </div>
      )}

      <div>
        <div className="form-label" style={{ marginBottom: '8px' }}>Review</div>
        <div className="rule-review">
          {reviewRows.map((row) => (
            <div key={row.label} className="rule-review-row">
              <span className="rule-review-label">{row.label}</span>
              <span className="rule-review-value">{row.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// New Rule Wizard Modal
// ---------------------------------------------------------------------------

const defaultCondition = (): ConditionState => ({
  keywords: [],
  keyword_mode: 'any',
  source_types: [],
  severity: 'routine',
  entity_name: '',
  velocity_threshold: 3,
  velocity_window_minutes: 60,
  stages: [
    {
      stage: 1,
      condition: { type: 'keyword_match', keywords: [] },
      time_window_minutes: 60,
      severity: 'routine',
    },
    {
      stage: 2,
      condition: { type: 'keyword_match', keywords: [] },
      time_window_minutes: 120,
      severity: 'urgent',
    },
  ],
  // geo_proximity
  geo_lat: 0,
  geo_lng: 0,
  geo_radius_km: 100,
  geo_label: '',
  // silence
  silence_entity: '',
  silence_source_type: '',
  silence_expected_hours: 6,
});

const defaultDelivery = (): DeliveryState => ({
  name: '',
  description: '',
  delivery_channels: ['in_app'],
  telegram_chat_id: '',
  webhook_url: '',
  cooldown_minutes: 60,
});

function RuleWizardModal({
  onClose,
  onSaved,
  editRule,
}: {
  onClose: () => void;
  onSaved: () => void;
  editRule?: AlertRule | null;
}) {
  const [step, setStep] = useState(1);
  const [ruleType, setRuleType] = useState(editRule?.rule_type ?? 'keyword');
  const [cond, setCond] = useState<ConditionState>(() => {
    if (!editRule) return defaultCondition();
    return {
      keywords: editRule.keywords ?? [],
      keyword_mode: editRule.keyword_mode ?? 'any',
      source_types: editRule.source_types ?? [],
      severity: editRule.severity,
      entity_name: editRule.entity_name ?? '',
      velocity_threshold: editRule.velocity_threshold ?? 3,
      velocity_window_minutes: editRule.velocity_window_minutes ?? 60,
      stages: (editRule.directives as { stages?: Stage[] })?.stages ?? defaultCondition().stages,
      // geo_proximity
      geo_lat: editRule.geo_lat ?? 0,
      geo_lng: editRule.geo_lng ?? 0,
      geo_radius_km: editRule.geo_radius_km ?? 100,
      geo_label: editRule.geo_label ?? '',
      // silence
      silence_entity: editRule.silence_entity ?? '',
      silence_source_type: editRule.silence_source_type ?? '',
      silence_expected_hours: editRule.silence_expected_interval_minutes
        ? editRule.silence_expected_interval_minutes / 60
        : 6,
    };
  });
  const [delivery, setDelivery] = useState<DeliveryState>(() => {
    if (!editRule) return defaultDelivery();
    return {
      name: editRule.name,
      description: editRule.description ?? '',
      delivery_channels: editRule.delivery_channels ?? ['in_app'],
      telegram_chat_id: editRule.telegram_chat_id ?? '',
      webhook_url: editRule.webhook_url ?? '',
      cooldown_minutes: editRule.cooldown_minutes,
    };
  });
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [testResult, setTestResult] = useState<unknown>(null);
  const [testing, setTesting] = useState(false);

  const { createRule, updateRule, testRule } = useAlertStore();

  const buildPayload = (): AlertRuleCreate => {
    const base: AlertRuleCreate = {
      name: delivery.name,
      description: delivery.description || undefined,
      rule_type: ruleType,
      severity: cond.severity,
      cooldown_minutes: delivery.cooldown_minutes,
      delivery_channels: delivery.delivery_channels,
      telegram_chat_id: delivery.telegram_chat_id || undefined,
      webhook_url: delivery.webhook_url || undefined,
    };
    if (ruleType === 'keyword') {
      base.keywords = cond.keywords;
      base.keyword_mode = cond.keyword_mode;
      base.source_types = cond.source_types.length > 0 ? cond.source_types : undefined;
    } else if (ruleType === 'velocity') {
      base.entity_name = cond.entity_name;
      base.velocity_threshold = cond.velocity_threshold;
      base.velocity_window_minutes = cond.velocity_window_minutes;
    } else if (ruleType === 'geo_proximity') {
      base.geo_lat = cond.geo_lat;
      base.geo_lng = cond.geo_lng;
      base.geo_radius_km = cond.geo_radius_km;
      base.geo_label = cond.geo_label || undefined;
    } else if (ruleType === 'silence') {
      base.silence_entity = cond.silence_entity || undefined;
      base.silence_source_type = cond.silence_source_type || undefined;
      base.silence_expected_interval_minutes = Math.round(cond.silence_expected_hours * 60);
    } else {
      // correlation
      base.directives = { stages: cond.stages };
      // Use max stage severity as rule severity
      const maxSeverity = cond.stages.reduce((acc, s) => {
        const rank: Record<string, number> = { routine: 0, urgent: 1, flash: 2 };
        return (rank[s.severity] ?? 0) > (rank[acc] ?? 0) ? s.severity : acc;
      }, 'routine');
      base.severity = maxSeverity;
    }
    return base;
  };

  const handleSave = async () => {
    if (!delivery.name.trim()) { setError('Rule name is required.'); return; }
    setSaving(true);
    setError('');
    try {
      if (editRule) {
        await updateRule(editRule.id, buildPayload());
      } else {
        await createRule(buildPayload());
      }
      onSaved();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to save rule.');
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!editRule) { setError('Save the rule first to test it.'); return; }
    setTesting(true);
    try {
      const res = await testRule(editRule.id);
      setTestResult(res);
    } catch {
      setError('Test failed.');
    } finally {
      setTesting(false);
    }
  };

  const stepLabels = ['Rule Type', 'Conditions', 'Delivery'];

  return (
    <Modal
      title={editRule ? `Edit Rule: ${editRule.name}` : 'New Alert Rule'}
      onClose={onClose}
      footer={
        <div style={{ display: 'flex', gap: '8px', width: '100%', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: '6px' }}>
            {step > 1 && (
              <button className="btn btn-secondary" onClick={() => setStep(step - 1)}>← Back</button>
            )}
          </div>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
            {step < 3 ? (
              <button className="btn btn-primary" onClick={() => setStep(step + 1)}>Next →</button>
            ) : (
              <>
                {editRule && (
                  <button className="btn btn-secondary" onClick={handleTest} disabled={testing}>
                    {testing ? <LoadingSpinner size="sm" /> : '▶ Test'}
                  </button>
                )}
                <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                  {saving ? <LoadingSpinner size="sm" /> : editRule ? 'Update Rule' : 'Create Rule'}
                </button>
              </>
            )}
          </div>
        </div>
      }
    >
      <div style={{ minWidth: '560px' }}>
        {/* Step indicators */}
        <div className="wizard-steps" style={{ marginBottom: '20px' }}>
          {stepLabels.map((label, i) => {
            const num = i + 1;
            const state = num < step ? 'done' : num === step ? 'active' : '';
            return (
              <div key={label} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
                <div className={`wizard-step ${state}`}>
                  <span className="wizard-step-num">{num < step ? '✓' : num}</span>
                  <span>{label}</span>
                </div>
                {i < stepLabels.length - 1 && <div className="wizard-step-sep" style={{ flex: 1, height: '1px', background: 'var(--border)', margin: '0 8px' }} />}
              </div>
            );
          })}
        </div>

        {error && <div className="error-message" style={{ marginBottom: '12px' }}>{error}</div>}

        {step === 1 && (
          <Step1RuleType value={ruleType} onChange={(v) => { setRuleType(v); setCond(defaultCondition()); }} />
        )}
        {step === 2 && (
          <Step2Conditions
            ruleType={ruleType}
            cond={cond}
            onChange={(patch) => setCond((s) => ({ ...s, ...patch }))}
          />
        )}
        {step === 3 && (
          <Step3Delivery
            ruleType={ruleType}
            cond={cond}
            delivery={delivery}
            onChange={(patch) => setDelivery((s) => ({ ...s, ...patch }))}
          />
        )}

        {testResult && (
          <div className="test-result-panel">
            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px' }}>
              Test Result — {(testResult as { match_count: number }).match_count} matches in last hour ({(testResult as { posts_checked: number }).posts_checked} posts checked)
            </div>
            {(testResult as { matches: Array<{ content_preview?: string }> }).matches.slice(0, 5).map((m, i) => (
              <div key={i} className="test-match-item">
                {m.content_preview ?? JSON.stringify(m)}
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Rule card
// ---------------------------------------------------------------------------

function RuleCard({
  rule,
  onEdit,
  onDelete,
}: {
  rule: AlertRule;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { toggleRule } = useAlertStore();
  const [toggling, setToggling] = useState(false);

  const handleToggle = async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.stopPropagation();
    setToggling(true);
    await toggleRule(rule.id, e.target.checked);
    setToggling(false);
  };

  return (
    <div className={`alert-rule-card severity-${rule.severity}${!rule.enabled ? ' disabled' : ''}`}>
      <div className="alert-rule-header" onClick={() => setExpanded(!expanded)}>
        <span className="alert-rule-name">{rule.name}</span>
        <div className="alert-rule-meta">
          <TypeBadge type={rule.rule_type} />
          <SeverityBadge severity={rule.severity} />
          {rule.last_fired_at ? (
            <span>fired {formatRelative(rule.last_fired_at)}</span>
          ) : (
            <span style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: 11 }}>never fired</span>
          )}
        </div>
        <div className="alert-rule-actions" onClick={(e) => e.stopPropagation()}>
          <label className="toggle">
            <input
              type="checkbox"
              checked={rule.enabled}
              onChange={handleToggle}
              disabled={toggling}
            />
            <span className="toggle-slider" />
          </label>
          <button className="btn btn-ghost btn-sm" onClick={onEdit} title="Edit">✎</button>
          <button
            className="btn btn-ghost btn-sm"
            style={{ color: 'var(--danger)' }}
            onClick={onDelete}
            title="Delete"
          >
            ✕
          </button>
        </div>
        <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>{expanded ? '▲' : '▼'}</span>
      </div>

      {expanded && (
        <div className="alert-rule-details">
          <div className="alert-rule-details-grid">
            {rule.rule_type === 'keyword' && (
              <>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Keywords</span>
                  <span className="alert-rule-detail-value">{(rule.keywords ?? []).join(', ') || '—'}</span>
                </div>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Mode</span>
                  <span className="alert-rule-detail-value">{rule.keyword_mode ?? '—'}</span>
                </div>
              </>
            )}
            {rule.rule_type === 'velocity' && (
              <>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Entity</span>
                  <span className="alert-rule-detail-value">{rule.entity_name ?? '—'}</span>
                </div>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Threshold</span>
                  <span className="alert-rule-detail-value">{rule.velocity_threshold}x in {rule.velocity_window_minutes}min</span>
                </div>
              </>
            )}
            {rule.rule_type === 'correlation' && (
              <div className="alert-rule-detail-item">
                <span className="alert-rule-detail-label">Stages</span>
                <span className="alert-rule-detail-value">
                  {((rule.directives as { stages?: unknown[] })?.stages ?? []).length} stage(s)
                </span>
              </div>
            )}
            {rule.rule_type === 'geo_proximity' && (
              <>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Location</span>
                  <span className="alert-rule-detail-value">{rule.geo_label ?? `${rule.geo_lat}, ${rule.geo_lng}`}</span>
                </div>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Radius</span>
                  <span className="alert-rule-detail-value">{rule.geo_radius_km} km</span>
                </div>
              </>
            )}
            {rule.rule_type === 'silence' && (
              <>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Monitor</span>
                  <span className="alert-rule-detail-value">{rule.silence_entity ?? rule.silence_source_type ?? '—'}</span>
                </div>
                <div className="alert-rule-detail-item">
                  <span className="alert-rule-detail-label">Silence after</span>
                  <span className="alert-rule-detail-value">
                    {rule.silence_expected_interval_minutes
                      ? `${(rule.silence_expected_interval_minutes / 60).toFixed(1)}h`
                      : '—'}
                  </span>
                </div>
                {rule.silence_last_seen && (
                  <div className="alert-rule-detail-item">
                    <span className="alert-rule-detail-label">Last seen</span>
                    <span className="alert-rule-detail-value">{formatRelative(rule.silence_last_seen)}</span>
                  </div>
                )}
              </>
            )}
            <div className="alert-rule-detail-item">
              <span className="alert-rule-detail-label">Delivery</span>
              <span className="alert-rule-detail-value">{(rule.delivery_channels ?? []).join(', ')}</span>
            </div>
            <div className="alert-rule-detail-item">
              <span className="alert-rule-detail-label">Cooldown</span>
              <span className="alert-rule-detail-value">{rule.cooldown_minutes} min</span>
            </div>
            <div className="alert-rule-detail-item">
              <span className="alert-rule-detail-label">Created</span>
              <span className="alert-rule-detail-value">{formatRelative(rule.created_at)}</span>
            </div>
          </div>
          {rule.description && (
            <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
              {rule.description}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Alert History tab
// ---------------------------------------------------------------------------

function AlertHistoryTab({ highlightId }: { highlightId?: string | null }) {
  const { events, totalEvents, loadingEvents, fetchEvents, acknowledgeEvent } = useAlertStore();
  const [severityFilter, setSeverityFilter] = useState<string>('');
  const [ackedFilter, setAckedFilter] = useState<boolean | null>(null);

  useEffect(() => {
    fetchEvents(1, severityFilter || null, ackedFilter);
  }, [severityFilter, ackedFilter, fetchEvents]);

  // Scroll to highlighted event after events load
  useEffect(() => {
    if (highlightId && events.length > 0) {
      const el = document.getElementById(`alert-event-${highlightId}`);
      if (el) {
        setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'center' }), 200);
      }
    }
  }, [highlightId, events]);

  if (loadingEvents) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div>
      <div className="alert-event-filters">
        <select
          className="select"
          style={{ width: '140px' }}
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
        >
          <option value="">All severities</option>
          <option value="flash">Flash</option>
          <option value="urgent">Urgent</option>
          <option value="routine">Routine</option>
        </select>
        <select
          className="select"
          style={{ width: '160px' }}
          value={ackedFilter === null ? '' : String(ackedFilter)}
          onChange={(e) => setAckedFilter(e.target.value === '' ? null : e.target.value === 'true')}
        >
          <option value="">All events</option>
          <option value="false">Unacknowledged</option>
          <option value="true">Acknowledged</option>
        </select>
        <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {totalEvents} total events
        </span>
      </div>

      {events.length === 0 ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
          No alert events yet. Rules will appear here when they fire.
        </div>
      ) : (
        <div className="alert-events-list">
          {events.map((ev) => (
            <div
              key={ev.id}
              id={`alert-event-${ev.id}`}
              className={`alert-event-row severity-${ev.severity}${ev.acknowledged ? ' acknowledged' : ''}${highlightId && String(ev.id) === String(highlightId) ? ' alert-event-row--highlighted' : ''}`}
            >
              <span className="alert-event-emoji">{SEVERITY_EMOJI[ev.severity] ?? '🔔'}</span>
              <div className="alert-event-content">
                <div className="alert-event-title">{ev.title}</div>
                {ev.summary && <div className="alert-event-summary">{ev.summary}</div>}
                <div className="alert-event-meta">
                  <span>{formatRelative(ev.fired_at)}</span>
                  {ev.rule_name && <span>Rule: {ev.rule_name}</span>}
                  {ev.matched_entities && ev.matched_entities.length > 0 && (
                    <span>Entities: {ev.matched_entities.join(', ')}</span>
                  )}
                </div>
              </div>
              {!ev.acknowledged && (
                <div className="alert-event-actions">
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => acknowledgeEvent(ev.id)}
                  >
                    ✓ Ack
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main AlertsPage
// ---------------------------------------------------------------------------

export function AlertsPage() {
  const [searchParams] = useSearchParams();
  // If ?highlight= param is set, switch to history tab automatically
  const [activeTab, setActiveTab] = useState<'rules' | 'history'>(
    searchParams.get('highlight') ? 'history' : 'rules'
  );
  const highlightId = searchParams.get('highlight');
  const [showWizard, setShowWizard] = useState(false);
  const [editRule, setEditRule] = useState<AlertRule | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AlertRule | null>(null);

  const { rules, loadingRules, fetchRules, deleteRule } = useAlertStore();

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  const handleSaved = () => {
    setShowWizard(false);
    setEditRule(null);
    fetchRules();
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await deleteRule(deleteTarget.id);
    setDeleteTarget(null);
  };

  return (
    <div>
      {/* Page header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h2 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Alert Rules ({rules.length})
        </h2>
        <button className="btn btn-primary btn-sm" onClick={() => setShowWizard(true)}>
          + New Rule
        </button>
      </div>

      {/* Tab bar */}
      <div className="alerts-tabs">
        <button
          className={`alerts-tab${activeTab === 'rules' ? ' active' : ''}`}
          onClick={() => setActiveTab('rules')}
        >
          Rules
        </button>
        <button
          className={`alerts-tab${activeTab === 'history' ? ' active' : ''}`}
          onClick={() => setActiveTab('history')}
        >
          Alert History
        </button>
      </div>

      {/* Rules tab */}
      {activeTab === 'rules' && (
        <>
          {loadingRules ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '40px' }}>
              <LoadingSpinner size="lg" />
            </div>
          ) : rules.length === 0 ? (
            <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
              <div style={{ fontSize: '32px', marginBottom: '12px' }}>🔕</div>
              <div>No alert rules configured.</div>
              <div style={{ marginTop: '4px', marginBottom: '16px' }}>
                Create keyword, velocity, correlation, geo-proximity, or silence rules to monitor your feed.
              </div>
              <button className="btn btn-primary btn-sm" onClick={() => setShowWizard(true)}>
                Create your first rule
              </button>
            </div>
          ) : (
            <div className="alert-rules-list">
              {rules.map((rule) => (
                <RuleCard
                  key={rule.id}
                  rule={rule}
                  onEdit={() => setEditRule(rule)}
                  onDelete={() => setDeleteTarget(rule)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* History tab */}
      {activeTab === 'history' && <AlertHistoryTab highlightId={highlightId} />}

      {/* Wizard modal */}
      {(showWizard || editRule) && (
        <RuleWizardModal
          onClose={() => { setShowWizard(false); setEditRule(null); }}
          onSaved={handleSaved}
          editRule={editRule}
        />
      )}

      {/* Delete confirm */}
      {deleteTarget && (
        <ConfirmDialog
          title="Delete Rule"
          message={`Delete alert rule "${deleteTarget.name}"? All associated alert history will also be removed.`}
          confirmLabel="Delete"
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
          danger
        />
      )}
    </div>
  );
}

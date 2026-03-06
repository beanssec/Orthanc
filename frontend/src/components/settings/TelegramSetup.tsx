import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../services/api';
import { LoadingSpinner } from '../common/LoadingSpinner';

type Step = 'loading' | 'connected' | 'phone' | 'code' | '2fa' | 'done';

interface TelegramStatus {
  authenticated: boolean;
  phone?: string;
  username?: string;
  last_activity?: string | null;
}

export function TelegramSetup() {
  const [step, setStep] = useState<Step>('loading');
  const [phone, setPhone] = useState('');
  const [phoneCodeHash, setPhoneCodeHash] = useState('');
  const [code, setCode] = useState('');
  const [twoFA, setTwoFA] = useState('');
  const [connectedPhone, setConnectedPhone] = useState('');
  const [connectedUsername, setConnectedUsername] = useState('');
  const [lastActivity, setLastActivity] = useState<string | null>(null);
  const [telegramSourceCount, setTelegramSourceCount] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const res = await api.get<TelegramStatus>('/telegram/auth/status');
        if (res.data.authenticated) {
          setConnectedPhone(res.data.phone ?? '');
          setConnectedUsername(res.data.username ?? '');
          setLastActivity(res.data.last_activity ?? null);
          setStep('connected');
        } else {
          setStep('phone');
        }
      } catch {
        setStep('phone');
      }
    };
    checkStatus();
    // Fetch Telegram source count
    api.get('/sources/').then((res) => {
      const sources = res.data as Array<{ type: string }>;
      setTelegramSourceCount(sources.filter((s) => s.type === 'telegram').length);
    }).catch(() => {});
  }, []);

  const handleStartAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phone.trim()) { setError('Phone number is required.'); return; }
    setError('');
    setLoading(true);
    try {
      const res = await api.post('/telegram/auth/start', { phone: phone.trim() });
      setPhoneCodeHash(res.data.phone_code_hash);
      setStep('code');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Failed to send code. Check your phone number.');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) { setError('Code is required.'); return; }
    setError('');
    setLoading(true);
    try {
      const res = await api.post('/telegram/auth/verify', { phone: phone.trim(), code: code.trim(), phone_code_hash: phoneCodeHash });
      if (res.data.status === '2fa_required') {
        setStep('2fa');
      } else {
        setStep('done');
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Invalid code. Try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleTwoFA = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!twoFA.trim()) { setError('2FA password is required.'); return; }
    setError('');
    setLoading(true);
    try {
      await api.post('/telegram/auth/2fa', { password: twoFA });
      setStep('done');
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? 'Invalid 2FA password.');
    } finally {
      setLoading(false);
    }
  };

  const stepCard = (content: React.ReactNode) => (
    <div style={{ maxWidth: '420px' }}>
      <div style={{ marginBottom: '16px' }}>
        <h2 style={{ fontSize: '13px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
          Telegram Account Setup
        </h2>
      </div>
      <div className="card">{content}</div>
    </div>
  );

  if (step === 'loading') {
    return stepCard(
      <div style={{ display: 'flex', justifyContent: 'center', padding: '20px' }}>
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (step === 'connected') {
    return stepCard(
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div className="banner banner-success">
          ✓ Connected{connectedPhone ? ` as ${connectedPhone}` : ''}
          {connectedUsername ? ` (@${connectedUsername})` : ''}
        </div>

        {/* Connection details */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px' }}>
          {connectedPhone && (
            <div style={{ display: 'flex', gap: '8px' }}>
              <span style={{ color: 'var(--text-muted)', minWidth: 120 }}>Phone number</span>
              <span style={{ fontFamily: 'monospace', color: 'var(--text-primary)' }}>{connectedPhone}</span>
            </div>
          )}
          {telegramSourceCount !== null && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <span style={{ color: 'var(--text-muted)', minWidth: 120 }}>Active channels</span>
              <span style={{ color: 'var(--text-primary)' }}>
                {telegramSourceCount} channel{telegramSourceCount !== 1 ? 's' : ''} monitored
              </span>
              <Link to="/settings/sources" style={{ fontSize: 11, color: 'var(--accent)' }}>
                Manage →
              </Link>
            </div>
          )}
          {lastActivity && (
            <div style={{ display: 'flex', gap: '8px' }}>
              <span style={{ color: 'var(--text-muted)', minWidth: 120 }}>Last activity</span>
              <span style={{ color: 'var(--text-secondary)' }}>
                {new Date(lastActivity).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
              </span>
            </div>
          )}
        </div>

        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          Your Telegram account is authenticated. The collector can access channels you've subscribed to in{' '}
          <Link to="/settings/sources" style={{ color: 'var(--accent)' }}>Settings → Sources</Link>.
        </p>
        <button
          className="btn btn-ghost"
          style={{ color: 'var(--danger)', alignSelf: 'flex-start', fontSize: '12px' }}
          onClick={() => setStep('phone')}
        >
          Re-authenticate with a different account
        </button>
      </div>
    );
  }

  if (step === 'done') {
    return stepCard(
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div className="banner banner-success">
          ✓ Authentication complete
        </div>
        <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          Your Telegram account has been linked. The collector will now be able to access channels you monitor.
        </p>
      </div>
    );
  }

  const steps = ['Phone', 'Code', '2FA'];
  const stepIndex = step === 'phone' ? 0 : step === 'code' ? 1 : 2;

  return (
    <div style={{ maxWidth: '420px' }}>
      <div style={{ marginBottom: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <h2 style={{ fontSize: '13px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-secondary)' }}>
          Telegram Account Setup
        </h2>
        {/* Step indicator */}
        <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
          {steps.map((s, i) => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <div style={{
                width: '20px', height: '20px',
                borderRadius: '50%',
                backgroundColor: i < stepIndex ? 'var(--success)' : i === stepIndex ? 'var(--accent)' : 'var(--border)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: '10px', fontWeight: 600, color: i <= stepIndex ? '#fff' : 'var(--text-muted)',
                flexShrink: 0,
              }}>
                {i < stepIndex ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: '11px', color: i === stepIndex ? 'var(--text-primary)' : 'var(--text-muted)' }}>{s}</span>
              {i < steps.length - 1 && (
                <div style={{ width: '20px', height: '1px', backgroundColor: i < stepIndex ? 'var(--success)' : 'var(--border)', margin: '0 2px' }} />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        {step === 'phone' && (
          <form onSubmit={handleStartAuth} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {error && <div className="error-message">{error}</div>}
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Enter your Telegram phone number to begin. A verification code will be sent to your Telegram app.
            </p>
            <div className="form-group">
              <input
                className="input"
                type="tel"
                placeholder="+1 555 000 0000"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                autoFocus
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={loading} style={{ alignSelf: 'flex-start' }}>
              {loading ? <><LoadingSpinner size="sm" /> Sending...</> : 'Send Code'}
            </button>
          </form>
        )}

        {step === 'code' && (
          <form onSubmit={handleVerifyCode} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {error && <div className="error-message">{error}</div>}
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Enter the code sent to your Telegram app for <strong style={{ color: 'var(--text-primary)' }}>{phone}</strong>.
            </p>
            <div className="form-group">
              <input
                className="input mono"
                type="text"
                placeholder="12345"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoFocus
                maxLength={10}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button className="btn btn-secondary" type="button" onClick={() => { setStep('phone'); setError(''); }}>Back</button>
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? <><LoadingSpinner size="sm" /> Verifying...</> : 'Verify Code'}
              </button>
            </div>
          </form>
        )}

        {step === '2fa' && (
          <form onSubmit={handleTwoFA} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {error && <div className="error-message">{error}</div>}
            <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Your account has Two-Factor Authentication enabled. Enter your 2FA password to continue.
            </p>
            <div className="form-group">
              <input
                className="input"
                type="password"
                placeholder="2FA Password"
                value={twoFA}
                onChange={(e) => setTwoFA(e.target.value)}
                autoFocus
                autoComplete="current-password"
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={loading} style={{ alignSelf: 'flex-start' }}>
              {loading ? <><LoadingSpinner size="sm" /> Verifying...</> : 'Submit'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

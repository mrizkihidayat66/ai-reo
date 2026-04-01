import React, { useState } from 'react';
import {
  Plus, X, CheckCircle, XCircle, Loader, ToggleLeft, ToggleRight,
  Trash2, ChevronRight, Zap, Globe, Server, Cpu, Tag
} from 'lucide-react';
import { useProviders } from '../context/ProvidersContext';
import type { ProviderConfig, TestResult } from '../context/ProvidersContext';

// ---------------------------------------------------------------------------
// Provider type metadata
// ---------------------------------------------------------------------------

interface PTypeMeta {
  label: string;
  icon: React.ReactNode;
  needs_key: boolean;
  needs_url: boolean;
  default_url: string;
  default_models: string[];
  color: string;
}

const PROVIDER_TYPES: Record<string, PTypeMeta> = {
  openai: {
    label: 'OpenAI',
    icon: <Zap size={16} />,
    needs_key: true, needs_url: false,
    default_url: '',
    default_models: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
    color: '#10a37f',
  },
  anthropic: {
    label: 'Anthropic',
    icon: <Cpu size={16} />,
    needs_key: true, needs_url: false,
    default_url: '',
    default_models: ['claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229'],
    color: '#d4720b',
  },
  google: {
    label: 'Google Gemini',
    icon: <Globe size={16} />,
    needs_key: true, needs_url: false,
    default_url: '',
    default_models: ['gemini/gemini-2.0-flash', 'gemini/gemini-2.0-pro', 'gemini/gemini-1.5-pro'],
    color: '#4285f4',
  },
  mistral: {
    label: 'Mistral AI',
    icon: <Zap size={16} />,
    needs_key: true, needs_url: false,
    default_url: '',
    default_models: ['mistral/mistral-large-latest', 'mistral/mistral-medium-latest', 'mistral/mistral-small-latest'],
    color: '#ff7000',
  },
  ollama: {
    label: 'Ollama (Local)',
    icon: <Server size={16} />,
    needs_key: true, needs_url: true,
    default_url: 'http://localhost:11434',
    default_models: ['ollama/llama3', 'ollama/mistral', 'ollama/codellama'],
    color: '#5c6fff',
  },
  lmstudio: {
    label: 'LM Studio',
    icon: <Server size={16} />,
    needs_key: true, needs_url: true,
    default_url: 'http://localhost:1234/v1',
    default_models: ['openai/local-model'],
    color: '#8b5cf6',
  },
  generic: {
    label: 'OpenAI-Compatible API',
    icon: <Globe size={16} />,
    needs_key: true, needs_url: true,
    default_url: 'http://localhost:8080/v1',
    default_models: ['openai/local-model'],
    color: '#64748b',
  },
};

// ---------------------------------------------------------------------------
// Tags Input component (bootstrap-tagsinput style)
// ---------------------------------------------------------------------------

interface TagsInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

const TagsInput: React.FC<TagsInputProps> = ({ tags, onChange, placeholder = 'Add model, press Enter or comma…' }) => {
  const [inputValue, setInputValue] = useState('');
  const inputRef = React.useRef<HTMLInputElement>(null);

  const addTag = (raw: string) => {
    const parts = raw.split(',').map(s => s.trim()).filter(Boolean);
    const unique = parts.filter(p => !tags.includes(p));
    if (unique.length > 0) onChange([...tags, ...unique]);
  };

  const removeTag = (tag: string) => onChange(tags.filter(t => t !== tag));

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      if (inputValue.trim()) {
        addTag(inputValue);
        setInputValue('');
      }
    } else if (e.key === 'Backspace' && !inputValue && tags.length > 0) {
      removeTag(tags[tags.length - 1]);
    }
  };

  const handleBlur = () => {
    if (inputValue.trim()) {
      addTag(inputValue);
      setInputValue('');
    }
  };

  return (
    <div
      onClick={() => inputRef.current?.focus()}
      style={{
        display: 'flex', flexWrap: 'wrap', gap: '0.35rem',
        padding: '0.45rem 0.6rem',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border-color)',
        borderRadius: 'var(--radius-md)',
        minHeight: '44px',
        cursor: 'text',
        alignItems: 'center',
      }}
    >
      {tags.map(tag => (
        <span
          key={tag}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
            padding: '0.2rem 0.55rem 0.2rem 0.7rem',
            background: 'rgba(92,111,255,0.15)',
            border: '1px solid rgba(92,111,255,0.35)',
            borderRadius: '4px',
            fontSize: '0.78rem',
            color: 'var(--accent-primary)',
            fontFamily: 'var(--font-mono)',
            fontWeight: 500,
            userSelect: 'none',
          }}
        >
          {tag}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); removeTag(tag); }}
            style={{
              display: 'flex', alignItems: 'center',
              color: 'rgba(92,111,255,0.6)',
              lineHeight: 0, padding: '1px',
              borderRadius: '2px',
              transition: 'color 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--danger)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'rgba(92,111,255,0.6)')}
          >
            <X size={11} />
          </button>
        </span>
      ))}
      <input
        ref={inputRef}
        value={inputValue}
        onChange={e => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        placeholder={tags.length === 0 ? placeholder : ''}
        style={{
          flex: 1, minWidth: '140px',
          background: 'transparent', border: 'none', outline: 'none',
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.82rem',
          padding: '0.1rem 0.2rem',
        }}
      />
    </div>
  );
};

// ---------------------------------------------------------------------------
// Add Provider Modal
// ---------------------------------------------------------------------------

interface AddModalProps {
  onClose: () => void;
  onAdded: () => void;
}

const AddProviderModal: React.FC<AddModalProps> = ({ onClose, onAdded }) => {
  const { addProvider, testProvider } = useProviders();
  const [step, setStep] = useState<'pick' | 'configure'>('pick');
  const [ptype, setPtype] = useState<string>('');
  const [displayName, setDisplayName] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('auto');
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [error, setError] = useState('');

  const meta = ptype ? PROVIDER_TYPES[ptype] : null;

  const pickType = (type: string) => {
    const m = PROVIDER_TYPES[type];
    setPtype(type);
    setDisplayName(m.label);
    setBaseUrl(m.default_url);
    setModels(m.default_models);
    setSelectedModel('auto');
    setTestResult(null);
    setStep('configure');
  };

  const doSave = async (): Promise<ProviderConfig | null> => {
    const p = await addProvider({
      display_name: displayName,
      provider_type: ptype,
      api_key: apiKey,
      base_url: baseUrl,
      models,
      selected_model: selectedModel,
      enabled: true,
    });
    return p;
  };

  const handleTest = async () => {
    setError('');
    setTesting(true);
    setTestResult(null);
    try {
      const saved = await doSave();
      if (!saved) return;
      const result = await testProvider(saved.id);
      setTestResult(result);
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await doSave();
      onAdded();
      onClose();
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '1rem',
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="glass-panel animate-fade-in" style={{ width: '100%', maxWidth: '540px', padding: '2rem' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
          <h2 style={{ fontSize: '1.2rem' }}>
            {step === 'pick' ? 'Choose Provider Type' : (
              <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ color: meta?.color }}>{meta?.icon}</span>
                Configure {meta?.label}
              </span>
            )}
          </h2>
          <button onClick={onClose} style={{ color: 'var(--text-muted)', padding: '0.25rem' }}>
            <X size={20} />
          </button>
        </div>

        {/* Step 1: Pick provider type */}
        {step === 'pick' ? (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            {Object.entries(PROVIDER_TYPES).map(([type, m]) => (
              <button
                key={type}
                onClick={() => pickType(type)}
                style={{
                  padding: '1rem',
                  border: '1px solid var(--border-color)',
                  borderRadius: 'var(--radius-md)',
                  background: 'var(--bg-tertiary)',
                  color: 'var(--text-primary)',
                  display: 'flex', alignItems: 'center', gap: '0.75rem',
                  transition: 'all 0.2s ease',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
                onMouseEnter={e => {
                  (e.currentTarget as HTMLElement).style.borderColor = m.color;
                  (e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)';
                  (e.currentTarget as HTMLElement).style.boxShadow = `0 4px 12px ${m.color}22`;
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-color)';
                  (e.currentTarget as HTMLElement).style.transform = 'none';
                  (e.currentTarget as HTMLElement).style.boxShadow = 'none';
                }}
              >
                <span style={{
                  width: 32, height: 32, borderRadius: 'var(--radius-sm)',
                  background: `${m.color}22`, display: 'flex', alignItems: 'center',
                  justifyContent: 'center', color: m.color, flexShrink: 0,
                }}>
                  {m.icon}
                </span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>{m.label}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '0.1rem' }}>
                    {[m.needs_key && 'API Key', m.needs_url && 'Base URL'].filter(Boolean).join(' + ') || 'Auto-detect'}
                  </div>
                </div>
              </button>
            ))}
          </div>
        ) : (
          /* Step 2: Configure */
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

            {/* Display Name */}
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>Display Name</label>
              <input className="input" value={displayName} onChange={e => setDisplayName(e.target.value)} required />
            </div>

            {/* API Key — shown for all provider types */}
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
                API Key
                {!meta?.needs_key && <span style={{ marginLeft: '0.4rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>(optional for local servers)</span>}
              </label>
              <input
                className="input mono"
                type="password"
                placeholder={meta?.needs_key ? 'sk-...' : 'Leave blank if not required'}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
              />
            </div>

            {/* Base URL */}
            {meta?.needs_url && (
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>Base URL</label>
                <input className="input mono" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} required />
              </div>
            )}

            {/* Models tag input */}
            <div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
                <Tag size={12} /> Available Models
                <span style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontWeight: 400 }}>— type name + Enter or comma to add</span>
              </label>
              <TagsInput tags={models} onChange={setModels} />
            </div>

            {/* Selected Model */}
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>Active Model</label>
              <select
                className="input"
                value={selectedModel}
                onChange={e => setSelectedModel(e.target.value)}
                style={{ cursor: 'pointer' }}
              >
                <option value="auto">auto (use first available)</option>
                {models.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>

            {/* Error */}
            {error && (
              <div style={{ color: 'var(--danger)', fontSize: '0.85rem', padding: '0.5rem 0.75rem', background: 'rgba(239,68,68,0.1)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(239,68,68,0.2)' }}>
                {error}
              </div>
            )}

            {/* Test result inline */}
            {testResult && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.5rem',
                padding: '0.5rem 0.75rem', borderRadius: 'var(--radius-sm)',
                background: testResult.ok ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                border: `1px solid ${testResult.ok ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.25)'}`,
                fontSize: '0.85rem',
                animation: 'fadeIn 0.3s ease',
              }}>
                {testResult.ok
                  ? <><CheckCircle size={15} color="var(--success)" /><span style={{ color: 'var(--success)' }}>Connected successfully — {testResult.latency_ms}ms latency</span></>
                  : <><XCircle size={15} color="var(--danger)" /><span style={{ color: 'var(--danger)' }}>{testResult.error}</span></>
                }
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', marginTop: '0.25rem' }}>
              {/* Back — far left */}
              <button
                type="button"
                onClick={() => { setStep('pick'); setTestResult(null); setError(''); }}
                style={{ padding: '0.5rem 1rem', color: 'var(--text-secondary)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)', background: 'var(--bg-tertiary)', cursor: 'pointer', fontSize: '0.85rem' }}
              >
                ← Back
              </button>

              {/* Spacer */}
              <div style={{ flex: 1 }} />

              {/* Test Connection — right side */}
              <button
                type="button"
                onClick={handleTest}
                disabled={testing || loading || !displayName.trim() || (meta?.needs_url && !baseUrl.trim())}
                style={{
                  padding: '0.5rem 1rem', fontSize: '0.85rem', fontWeight: 600,
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                  border: '1px solid var(--border-color)', borderRadius: 'var(--radius-md)',
                  background: 'var(--bg-tertiary)',
                  color: (testing || loading || !displayName.trim() || (meta?.needs_url && !baseUrl.trim())) ? 'var(--text-muted)' : 'var(--text-primary)',
                  cursor: (testing || loading || !displayName.trim() || (meta?.needs_url && !baseUrl.trim())) ? 'not-allowed' : 'pointer',
                  transition: 'all 0.2s',
                  opacity: (testing || loading || !displayName.trim() || (meta?.needs_url && !baseUrl.trim())) ? 0.6 : 1,
                }}
              >
                {testing ? <Loader size={13} className="animate-pulse" /> : <Zap size={13} />}
                {testing ? 'Testing…' : 'Test Connection'}
              </button>

              {/* Add Provider — far right */}
              <button
                className="btn-primary"
                type="submit"
                disabled={loading || testing || !displayName.trim() || (meta?.needs_url && !baseUrl.trim())}
                style={{
                  padding: '0.5rem 1.4rem', fontSize: '0.85rem',
                  display: 'flex', alignItems: 'center', gap: '0.4rem',
                  ...(testResult?.ok ? { background: 'linear-gradient(135deg, var(--success), #059669)', border: 'none' } : {}),
                }}
              >
                {loading ? 'Saving…' : (testResult?.ok ? '✓ Add Provider' : 'Add Provider')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Provider Card
// ---------------------------------------------------------------------------

interface CardProps {
  provider: ProviderConfig;
}

const ProviderCard: React.FC<CardProps> = ({ provider }) => {
  const { testProvider, updateProvider, removeProvider } = useProviders();
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const meta = PROVIDER_TYPES[provider.provider_type];

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    const result = await testProvider(provider.id);
    setTestResult(result);
    setTesting(false);
  };

  const toggleEnabled = () => {
    updateProvider(provider.id, { enabled: !provider.enabled });
    fetch(`http://localhost:9000/providers/${provider.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !provider.enabled }),
    });
  };

  return (
    <div style={{
      border: `1px solid ${provider.enabled ? (meta?.color ?? '#5c6fff') + '44' : 'var(--border-color)'}`,
      borderRadius: 'var(--radius-lg)',
      padding: '1.25rem',
      background: 'var(--bg-secondary)',
      transition: 'all 0.3s ease',
      opacity: provider.enabled ? 1 : 0.6,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{
            width: 36, height: 36, borderRadius: 'var(--radius-md)',
            background: `${meta?.color ?? '#5c6fff'}22`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: meta?.color ?? '#5c6fff',
          }}>
            {meta?.icon}
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{provider.display_name}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.1rem', fontFamily: 'var(--font-mono)' }}>
              {provider.selected_model === 'auto' ? `auto → ${provider.models[0] ?? 'none'}` : provider.selected_model}
            </div>
          </div>
        </div>

        {/* Status badges + controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          {provider.tested && (
            <span style={{ fontSize: '0.7rem', padding: '0.2rem 0.5rem', background: 'rgba(16,185,129,0.15)', color: 'var(--success)', borderRadius: '20px', fontWeight: 600, whiteSpace: 'nowrap' }}>
              ✓ Tested
            </span>
          )}
          <button onClick={toggleEnabled} title={provider.enabled ? 'Disable' : 'Enable'} style={{ color: provider.enabled ? 'var(--accent-primary)' : 'var(--text-muted)', lineHeight: 0 }}>
            {provider.enabled ? <ToggleRight size={28} /> : <ToggleLeft size={28} />}
          </button>
          <button onClick={() => removeProvider(provider.id)} title="Remove" style={{ color: 'var(--text-muted)', padding: '0.25rem', lineHeight: 0 }}>
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {/* Model tags */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginBottom: '1rem' }}>
        {provider.models.slice(0, 4).map(m => (
          <span key={m} style={{
            fontSize: '0.72rem', padding: '0.15rem 0.5rem',
            background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)',
            borderRadius: '4px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
          }}>
            {m}
          </span>
        ))}
        {provider.models.length > 4 && (
          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', padding: '0.15rem 0.3rem' }}>
            +{provider.models.length - 4} more
          </span>
        )}
      </div>

      {/* Test Connection */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          onClick={handleTest}
          disabled={testing}
          style={{
            padding: '0.4rem 1rem', fontSize: '0.82rem', fontWeight: 600,
            border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)',
            background: 'var(--bg-tertiary)', color: 'var(--text-secondary)',
            display: 'flex', alignItems: 'center', gap: '0.4rem',
            cursor: testing ? 'wait' : 'pointer', transition: 'all 0.2s',
          }}
        >
          {testing ? <Loader size={13} className="animate-pulse" /> : <Zap size={13} />}
          {testing ? 'Testing…' : 'Test Connection'}
        </button>

        {testResult && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', animation: 'fadeIn 0.3s' }}>
            {testResult.ok
              ? <><CheckCircle size={14} color="var(--success)" /><span style={{ color: 'var(--success)' }}>{testResult.latency_ms}ms</span></>
              : <><XCircle size={14} color="var(--danger)" /><span style={{ color: 'var(--danger)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{testResult.error}</span></>
            }
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Main Providers Page
// ---------------------------------------------------------------------------

interface ProvidersPageProps {
  onContinue: () => void;
}

export const ProvidersPage: React.FC<ProvidersPageProps> = ({ onContinue }) => {
  const { providers, hasReadyProvider } = useProviders();
  const [showModal, setShowModal] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      background: 'radial-gradient(ellipse at 30% 20%, rgba(92,111,255,0.06) 0%, transparent 60%)',
    }}>
      {/* Top bar */}
      <div style={{ padding: '1.5rem 2rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '1.4rem', marginBottom: '0.2rem' }}>LLM Provider Configuration</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Configure and test your AI providers before starting binary analysis.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            onClick={() => setShowModal(true)}
            className="btn-primary"
            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.55rem 1.1rem' }}
          >
            <Plus size={16} /> Add Provider
          </button>
          <button
            onClick={onContinue}
            disabled={!hasReadyProvider}
            style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              padding: '0.55rem 1.4rem', borderRadius: 'var(--radius-md)',
              fontWeight: 600, fontSize: '0.9rem',
              background: hasReadyProvider ? 'linear-gradient(135deg, var(--success), #059669)' : 'var(--bg-tertiary)',
              color: hasReadyProvider ? 'white' : 'var(--text-muted)',
              border: hasReadyProvider ? 'none' : '1px solid var(--border-color)',
              cursor: hasReadyProvider ? 'pointer' : 'not-allowed',
              transition: 'all 0.2s ease',
              opacity: hasReadyProvider ? 1 : 0.6,
            }}
          >
            Continue <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '2rem' }}>
        {providers.length === 0 ? (
          <div className="flex-center" style={{ height: '60%', flexDirection: 'column', gap: '1rem', color: 'var(--text-muted)' }}>
            <Cpu size={48} strokeWidth={1} />
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>No providers configured</div>
              <div style={{ fontSize: '0.9rem' }}>Click <strong>Add Provider</strong> to connect an LLM backend.</div>
            </div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1rem' }}>
            {providers.map(p => <ProviderCard key={`${p.id}-${refreshKey}`} provider={p} />)}
          </div>
        )}

        {providers.length > 0 && !hasReadyProvider && (
          <div className="animate-fade-in" style={{ marginTop: '1.5rem', padding: '1rem', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 'var(--radius-md)', background: 'rgba(245,158,11,0.05)', color: 'var(--warning)', fontSize: '0.88rem' }}>
            ⚠ Enable at least one provider and click <strong>Test Connection</strong> to unlock the Continue button.
          </div>
        )}
      </div>

      {showModal && <AddProviderModal onClose={() => setShowModal(false)} onAdded={() => setRefreshKey(k => k + 1)} />}
    </div>
  );
};

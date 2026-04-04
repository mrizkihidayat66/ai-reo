import React, { useEffect, useState } from 'react';
import {
  Brain, ArrowRight, RefreshCw, Loader2, Bot,
  Code2, Zap, Unlock, Bug, Smartphone, Key, Network, Cpu, Bomb, Shield, FileText,
} from 'lucide-react';

const API = 'http://localhost:9000';

interface AgentInfo {
  name: string;
  description: string;
  primary_tools: string;
  route_keywords: string[];
  allowed_tools: string[];
}

interface AgentsPageProps {
  onContinue: () => void;
  onGoToSettings?: () => void;
  onGoToTools?: () => void;
}

const AGENT_STYLE: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  orchestrator:      { color: '#8b5cf6', icon: <Brain size={16} />,      label: 'Orchestrator' },
  static_analyst:    { color: '#3b82f6', icon: <Code2 size={16} />,      label: 'Static Analyst' },
  dynamic_analyst:   { color: '#f97316', icon: <Zap size={16} />,        label: 'Dynamic Analyst' },
  deobfuscator:      { color: '#ec4899', icon: <Unlock size={16} />,     label: 'Deobfuscator' },
  debugger:          { color: '#f59e0b', icon: <Bug size={16} />,        label: 'Debugger' },
  mobile_analyst:    { color: '#10b981', icon: <Smartphone size={16} />, label: 'Mobile Analyst' },
  crypto_analyst:    { color: '#f59e0b', icon: <Key size={16} />,        label: 'Crypto Analyst' },
  network_analyst:   { color: '#06b6d4', icon: <Network size={16} />,    label: 'Network Analyst' },
  firmware_analyst:  { color: '#8b5cf6', icon: <Cpu size={16} />,        label: 'Firmware Analyst' },
  exploit_developer: { color: '#ef4444', icon: <Bomb size={16} />,       label: 'Exploit Developer' },
  code_auditor:      { color: '#6b7280', icon: <Shield size={16} />,     label: 'Code Auditor' },
  documentation:     { color: '#10b981', icon: <FileText size={16} />,   label: 'Documentation' },
};

const getStyle = (name: string) =>
  AGENT_STYLE[name] || { color: 'var(--text-muted)', icon: <Bot size={16} />, label: name };

export const AgentsPage: React.FC<AgentsPageProps> = ({ onContinue, onGoToSettings, onGoToTools }) => {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAgents = async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const res = await fetch(`${API}/agents`);
      if (!res.ok) throw new Error('Failed to fetch agents');
      const data: AgentInfo[] = await res.json();
      setAgents(data);
    } catch (err) {
      console.error('Failed to fetch agents:', err);
    } finally {
      setLoading(false);
      if (showSpinner) setRefreshing(false);
    }
  };

  useEffect(() => { fetchAgents(); }, []);

  if (loading) {
    return (
      <div className="page-container animate-fade-in">
        <div className="tools-loading">
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
          <span>Loading agent registry...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container animate-fade-in">
      <div className="tools-page">
        {/* Header */}
        <div className="tools-header">
          <div className="tools-title-row">
            <Brain size={24} color="var(--accent-primary)" />
            <h1 className="tools-title">Analysis Agents</h1>
          </div>
          <p className="tools-subtitle">
            AI-REO uses {agents.length} specialist agents. The Orchestrator routes tasks between them
            based on the current Knowledge Graph and analysis objectives.
          </p>
        </div>

        {/* Agent grid */}
        <div className="tools-section">
          <div className="tools-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
            {agents.map(agent => {
              const style = getStyle(agent.name);
              return (
                <div
                  key={agent.name}
                  className="tools-card tools-card-ready"
                  style={{ borderLeft: `3px solid ${style.color}` }}
                >
                  {/* Card header */}
                  <div className="tools-card-header" style={{ marginBottom: '0.5rem' }}>
                    <span style={{ color: style.color, display: 'flex', alignItems: 'center', gap: '0.4rem', fontWeight: 600 }}>
                      {style.icon}
                      {style.label}
                    </span>
                    <code style={{ fontSize: '0.65rem', color: 'var(--text-muted)', background: 'var(--bg-tertiary)', padding: '0.1rem 0.35rem', borderRadius: '4px' }}>
                      {agent.name}
                    </code>
                  </div>

                  {/* Description */}
                  <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.6rem 0', lineHeight: 1.45 }}>
                    {agent.description}
                  </p>

                  {/* Primary tools */}
                  {agent.primary_tools && agent.primary_tools !== '(none — report synthesis only)' && (
                    <div style={{ marginBottom: '0.4rem' }}>
                      <span style={{ fontSize: '0.65rem', textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', fontWeight: 600 }}>
                        Primary Tools
                      </span>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem', marginTop: '0.3rem' }}>
                        {agent.primary_tools.split(',').map(t => t.trim()).filter(Boolean).map(t => (
                          <span key={t} style={{
                            fontSize: '0.65rem', background: `${style.color}22`,
                            color: style.color, borderRadius: '4px', padding: '0.1rem 0.35rem',
                            border: `1px solid ${style.color}44`,
                          }}>
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Allowed tool count */}
                  {agent.allowed_tools.length > 0 && (
                    <p style={{ fontSize: '0.68rem', color: 'var(--text-muted)', margin: '0.35rem 0 0 0' }}>
                      {agent.allowed_tools.length} tool{agent.allowed_tools.length !== 1 ? 's' : ''} accessible
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Actions */}
        <div className="tools-actions">
          {onGoToSettings && (
            <button className="tools-back-btn" onClick={onGoToSettings}>
              ← Providers
            </button>
          )}
          {onGoToTools && (
            <button className="tools-back-btn" onClick={onGoToTools}>
              ← Tools
            </button>
          )}
          <button className="tools-refresh-btn" onClick={() => fetchAgents(true)} disabled={refreshing}>
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <button className="btn-primary tools-continue-btn" onClick={onContinue}>
            Continue to Sessions
            <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
};

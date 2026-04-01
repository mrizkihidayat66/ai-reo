import React, { useEffect, useState, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useWs } from '../context/WebSocketContext';
import { GraphPanel } from './GraphPanel';
import {
  Activity, Terminal, Send, Pause, Play, Settings, ArrowLeft,
  Wrench, AlertCircle, Brain, Code2, FileText, Zap, Bot,
} from 'lucide-react';

interface DashboardProps {
  sessionName?: string;
  onGoToSettings?: () => void;
  onGoToTools?: () => void;
  onBackToSessions?: () => void;
}

const API = 'http://localhost:9000';

/* Agent visual identity */
const AGENT_STYLE: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  orchestrator:    { color: '#8b5cf6', icon: <Brain size={14} />,    label: 'Orchestrator' },
  static_analyst:  { color: '#3b82f6', icon: <Code2 size={14} />,   label: 'Static Analyst' },
  dynamic_analyst: { color: '#f97316', icon: <Zap size={14} />,     label: 'Dynamic Analyst' },
  documentation:   { color: '#10b981', icon: <FileText size={14} />, label: 'Documentation' },
  'ai-reo':        { color: '#06b6d4', icon: <Bot size={14} />,     label: 'AI-REO' },
  direct_chat:     { color: '#06b6d4', icon: <Bot size={14} />,     label: 'AI-REO' },
};

const getAgentStyle = (agent: string) =>
  AGENT_STYLE[agent] || { color: 'var(--text-muted)', icon: <Bot size={14} />, label: agent || 'Assistant' };

const ToolResultCard: React.FC<{ agent?: string; tool?: string; preview?: string }> = ({ agent, tool, preview }) => {
  const [expanded, setExpanded] = useState(false);
  const formattedPreview = React.useMemo(() => {
    if (!preview) return '(no output)';
    try { return JSON.stringify(JSON.parse(preview), null, 2); }
    catch { return preview; }
  }, [preview]);
  return (
    <div className="feed-tool-result">
      <button className="feed-tool-header" onClick={() => setExpanded(e => !e)}>
        <Wrench size={12} color="var(--success)" />
        <span className="feed-tool-name">{agent}:{tool}</span>
        <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: '0.7rem' }}>{expanded ? '▲ collapse' : '▼ expand'}</span>
      </button>
      {expanded && (
        <pre className="feed-tool-output">{formattedPreview}</pre>
      )}
    </div>
  );
};

const OrchestratorCard: React.FC<{ plan: any; timestamp?: string }> = ({ plan, timestamp }) => {
  const [expanded, setExpanded] = useState(false);
  const targetStyle = getAgentStyle(plan.next_agent);
  const orchStyle = getAgentStyle('orchestrator');
  return (
    <div className="feed-orchestrator-route" onClick={() => setExpanded(e => !e)} style={{ cursor: 'pointer' }}>
      <span style={{ color: orchStyle.color, display: 'flex', alignItems: 'center' }}>{orchStyle.icon}</span>
      <span className="feed-orch-arrow">→</span>
      <span style={{ color: targetStyle.color, fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
        {targetStyle.icon}{targetStyle.label}
      </span>
      {plan.goal && (
        <span className="feed-orch-goal" title={plan.goal}>
          "{expanded ? plan.goal : (plan.goal.length > 80 ? plan.goal.slice(0, 80) + '…' : plan.goal)}"
        </span>
      )}
      {timestamp && <span className="feed-orch-time">{timestamp}</span>}
      {expanded && plan.reasoning && (
        <div className="feed-orch-reasoning">{plan.reasoning}</div>
      )}
    </div>
  );
};

export const AnalysisDashboard: React.FC<DashboardProps> = ({ sessionName, onGoToSettings, onGoToTools, onBackToSessions }) => {
  const { isConnected, logs, session, sendCommand, clearLogs } = useWs();
  const [goal, setGoal] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [userMessages, setUserMessages] = useState<{ id: string; text: string; ts: string }[]>([]);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [currentGoal, setCurrentGoal] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Normalize a DB history row into the same shape as a live WS chat_message log entry
  const normalizeHistoryEntry = (h: any) => ({
    id: h.id,
    type: 'chat_message' as const,
    timestamp: h.timestamp ? new Date(h.timestamp).toLocaleTimeString() : '',
    content: {
      agent: h.agent,
      content: h.response || '',
      goal_completed: false,
      findings_count: 0,
    },
  });

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, history, userMessages]);

  // Load chat history on mount
  useEffect(() => {
    if (!session) return;
    fetch(`${API}/sessions/${session}/history`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setHistory(data))
      .catch(() => {});
  }, [session]);

  // Track active agent and pause state from WS logs
  useEffect(() => {
    const agentLogs = logs.filter(l => l.type === 'agent_state_override' || l.type === 'agent_step');
    if (agentLogs.length > 0) {
      const last = agentLogs[agentLogs.length - 1];
      setActiveAgent(last.content?.active_agent || last.content?.agent || null);
      if (last.content?.current_goal) setCurrentGoal(last.content.current_goal);
    }
    const pauseLogs = logs.filter(l => l.type === 'pause_state');
    if (pauseLogs.length > 0) {
      setIsPaused(pauseLogs[pauseLogs.length - 1].content?.paused ?? false);
    }
  }, [logs]);

  // Track errors
  useEffect(() => {
    const errors = logs.filter(l => l.type === 'error');
    if (errors.length > 0) {
      setErrorBanner(errors[errors.length - 1].content?.message || 'An error occurred.');
    }
  }, [logs]);

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!goal.trim() || !session) return;

    // Optimistic UI: show user message immediately as right-side bubble
    const msg = { id: `user-${Date.now()}`, text: goal, ts: new Date().toLocaleTimeString() };
    setUserMessages(prev => [...prev, msg]);

    setAnalyzing(true);
    setIsPaused(false);
    setErrorBanner(null);
    setActiveAgent(null);
    setCurrentGoal(null);
    const submittedGoal = goal;
    setGoal('');

    try {
      await fetch(`${API}/sessions/${session}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: submittedGoal }),
      });
    } finally {
      setAnalyzing(false);
      setIsPaused(false);
      setActiveAgent(null);
      setCurrentGoal(null);
      // Reload history (now includes user + all agent messages), then clear live state
      fetch(`${API}/sessions/${session}/history`)
        .then(r => r.ok ? r.json() : [])
        .then(data => {
          setHistory(data);
          clearLogs();
          setUserMessages([]);
        })
        .catch(() => {});
    }
  };

  const handleTogglePause = () => {
    sendCommand('toggle_pause');
  };

  const renderLogEntry = (log: any) => {
    const { type, content } = log;

    if (type === 'agent_state_override') return null;
    if (type === 'system') return null;
    if (type === 'pause_state') {
      const paused: boolean = content?.paused ?? false;
      return (
        <div className="feed-info-line">
          {paused ? '⏸' : '▶'} {content?.message || (paused ? 'Paused' : 'Resumed')}
        </div>
      );
    }

    if (type === 'chat_message') {
      const rawContent: string = content?.content || '';
      const agent = content?.agent || '';

      // User message: right-side bubble
      if (agent === 'user') {
        if (!rawContent.trim()) return null;
        return (
          <div className="chat-msg chat-msg-user-bubble">
            <div className="chat-msg-header">
              <span className="chat-msg-agent" style={{ color: 'var(--accent-primary)' }}>You</span>
              <span className="chat-msg-time">{log.timestamp}</span>
            </div>
            <div className="chat-msg-body">{rawContent}</div>
          </div>
        );
      }

      // System messages (pause/resume persisted)
      if (agent === 'system') {
        if (!rawContent.trim()) return null;
        return <div className="feed-info-line">{rawContent}</div>;
      }

      // Orchestrator: expandable routing card
      if (agent === 'orchestrator') {
        try {
          const plan = JSON.parse(rawContent.trim());
          if (plan?.next_agent) {
            return <OrchestratorCard plan={plan} timestamp={log.timestamp} />;
          }
        } catch {}
        return null;
      }

      if (!rawContent.trim()) return null;

      const style = getAgentStyle(agent);
      return (
        <div className="chat-msg" style={{ borderLeftColor: style.color }}>
          <div className="chat-msg-header">
            <span style={{ color: style.color }}>{style.icon}</span>
            <span className="chat-msg-agent" style={{ color: style.color }}>{style.label}</span>
            <span className="chat-msg-time">{log.timestamp}</span>
            {content?.goal_completed && <span className="chat-msg-badge chat-msg-badge-done">✓ Done</span>}
            {content?.findings_count > 0 && (
              <span className="chat-msg-badge chat-msg-badge-findings">+{content.findings_count} findings</span>
            )}
          </div>
          <div className="chat-msg-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{rawContent}</ReactMarkdown>
          </div>
        </div>
      );
    }

    if (type === 'agent_step') {
      const msg: string = content?.message || '';
      if (msg.endsWith('is working...') || msg.endsWith('is thinking...')) return null;
      const style = getAgentStyle(content?.agent);
      return (
        <div className="feed-agent-step" style={{ borderLeftColor: style.color }}>
          {style.icon}
          <span>{msg}</span>
        </div>
      );
    }

    if (type === 'tool_result') {
      return (
        <ToolResultCard
          agent={content?.agent}
          tool={content?.tool}
          preview={content?.result_preview}
        />
      );
    }

    if (type === 'status') return null; // pause_state replaces old status
    if (type === 'error') return null; // handled by banner

    return null;
  };

  return (
    <div className="dashboard animate-fade-in">

      {/* Error Banner */}
      {errorBanner && (
        <div className="dashboard-error-banner">
          <AlertCircle size={16} />
          <span>{errorBanner}</span>
          <button onClick={() => setErrorBanner(null)} className="dashboard-error-dismiss">✕</button>
        </div>
      )}

      {/* Header */}
      <div className="glass-panel dashboard-header">
        <div className="dashboard-header-left">
          {onBackToSessions && (
            <button onClick={onBackToSessions} className="dashboard-back-btn">
              <ArrowLeft size={14} /> Sessions
            </button>
          )}
          <Activity size={20} color={isConnected ? 'var(--success)' : 'var(--danger)'} className={isConnected ? 'animate-pulse' : ''} />
          <div className="dashboard-session-info">
            <span className="dashboard-session-name">{sessionName || 'Session'}</span>
            <span className="mono dashboard-session-id">{session}</span>
          </div>
        </div>

        {/* Active Agent Badge */}
        {analyzing && activeAgent && (
          <div className="dashboard-active-badge" style={{ borderColor: getAgentStyle(activeAgent).color + '66' }}>
            <span className="animate-pulse" style={{ color: getAgentStyle(activeAgent).color }}>●</span>
            <span style={{ color: getAgentStyle(activeAgent).color }}>{getAgentStyle(activeAgent).label}</span>
            {currentGoal && <span className="dashboard-active-goal">{currentGoal.substring(0, 50)}</span>}
          </div>
        )}

        <div className="dashboard-header-actions">
          {onGoToTools && (
            <button onClick={onGoToTools} className="dashboard-action-btn">
              <Wrench size={14} /> Tools
            </button>
          )}
          <button onClick={onGoToSettings} className="dashboard-action-btn">
            <Settings size={14} /> Providers
          </button>
          <button
            onClick={handleTogglePause}
            className={`dashboard-action-btn${isPaused ? ' dashboard-btn-active' : ''}`}
            disabled={!analyzing}
            title={isPaused ? 'Resume analysis' : 'Pause analysis'}
          >
            {isPaused ? <><Play size={14} /> Resume</> : <><Pause size={14} /> Pause</>}
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="dashboard-main">

        {/* Chat Feed */}
        <div className="glass-panel dashboard-feed">
          <div className="panel-header">
            <Terminal size={16} color="var(--accent-primary)" />
            <span className="panel-title">Analysis Feed</span>
          </div>

          <div ref={scrollRef} className="dashboard-feed-scroll">
            {/* Persisted history — normalized through the same renderLogEntry function */}
            {history.map((h: any) => {
              const normalized = normalizeHistoryEntry(h);
              const rendered = renderLogEntry(normalized);
              if (!rendered) return null;
              return (
                <div key={h.id} className="animate-fade-in feed-entry">
                  <span className="mono feed-timestamp">{normalized.timestamp}</span>
                  {rendered}
                </div>
              );
            })}

            {/* Separator between history and live stream when both have content */}
            {history.length > 0 && logs.some(l => renderLogEntry(l) !== null) && (
              <div className="feed-section-sep">▸ Live</div>
            )}

            {/* User messages (optimistic — right-side bubble) */}
            {userMessages.map(m => (
              <div key={m.id} className="chat-msg chat-msg-user-bubble">
                <div className="chat-msg-header">
                  <span className="chat-msg-agent" style={{ color: 'var(--accent-primary)' }}>You</span>
                  <span className="chat-msg-time">{m.ts}</span>
                </div>
                <div className="chat-msg-body">{m.text}</div>
              </div>
            ))}

            {/* Live WebSocket stream — only renders entries with visible content */}
            {history.length === 0 && logs.length === 0 && userMessages.length === 0 && !analyzing ? (
              <div className="feed-empty mono animate-pulse">
                Awaiting Agent Activity...
              </div>
            ) : logs.map((log) => {
              const rendered = renderLogEntry(log);
              if (!rendered) return null;
              return (
                <div key={log.id} className="animate-fade-in feed-entry">
                  <span className="mono feed-timestamp">{log.timestamp}</span>
                  {rendered}
                </div>
              );
            })}

            {/* 3-dot typing indicator — looks like an agent chat bubble */}
            {analyzing && (() => {
              const s = activeAgent ? getAgentStyle(activeAgent) : getAgentStyle('ai-reo');
              return (
                <div className="chat-msg feed-typing-bubble" style={{ borderLeftColor: s.color }}>
                  <div className="chat-msg-header">
                    <span style={{ color: s.color }}>{s.icon}</span>
                    <span className="chat-msg-agent" style={{ color: s.color }}>{s.label}</span>
                    {currentGoal && (
                      <span className="feed-typing-goal">
                        {currentGoal.length > 60 ? currentGoal.slice(0, 60) + '…' : currentGoal}
                      </span>
                    )}
                  </div>
                  <div className="feed-typing-dots">
                    <span className="feed-typing-dot" style={{ background: s.color }} />
                    <span className="feed-typing-dot" style={{ background: s.color }} />
                    <span className="feed-typing-dot" style={{ background: s.color }} />
                  </div>
                </div>
              );
            })()}
          </div>
        </div>

        {/* Knowledge Graph Panel */}
        <GraphPanel sessionId={session} isActive={analyzing} />
      </div>

      {/* Input Bar */}
      <div className="glass-panel dashboard-input-bar">
        <form onSubmit={handleAnalyze} className="dashboard-input-form">
          <input
            className="input mono"
            placeholder="Type a message or analysis goal..."
            value={goal}
            onChange={e => setGoal(e.target.value)}
            disabled={analyzing}
          />
          <button className="btn-primary dashboard-send-btn" type="submit" disabled={analyzing || !goal.trim()}>
            <Send size={16} /> {analyzing ? 'Running...' : 'Send'}
          </button>
        </form>
      </div>
    </div>
  );
};

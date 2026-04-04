import React, { useEffect, useState, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useWs } from '../context/WebSocketContext';
import { GraphPanel } from './GraphPanel';
import {
  Activity, Terminal, Send, Pause, Play, Settings, ArrowLeft,
  Wrench, AlertCircle, Brain, Code2, FileText, Zap, Bot, Unlock, Bug,
  Smartphone, Key, Network, Cpu, Bomb, Shield,
} from 'lucide-react';

interface DashboardProps {
  sessionName?: string;
  onGoToSettings?: () => void;
  onGoToTools?: () => void;
  onGoToAgents?: () => void;
  onBackToSessions?: () => void;
}

const API = 'http://localhost:9000';

/* Agent visual identity */
const AGENT_STYLE: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  orchestrator:      { color: '#8b5cf6', icon: <Brain size={14} />,      label: 'Orchestrator' },
  static_analyst:    { color: '#3b82f6', icon: <Code2 size={14} />,      label: 'Static Analyst' },
  dynamic_analyst:   { color: '#f97316', icon: <Zap size={14} />,        label: 'Dynamic Analyst' },
  deobfuscator:      { color: '#ec4899', icon: <Unlock size={14} />,     label: 'Deobfuscator' },
  debugger:          { color: '#f59e0b', icon: <Bug size={14} />,        label: 'Debugger' },
  mobile_analyst:    { color: '#10b981', icon: <Smartphone size={14} />, label: 'Mobile Analyst' },
  crypto_analyst:    { color: '#d97706', icon: <Key size={14} />,        label: 'Crypto Analyst' },
  network_analyst:   { color: '#06b6d4', icon: <Network size={14} />,    label: 'Network Analyst' },
  firmware_analyst:  { color: '#7c3aed', icon: <Cpu size={14} />,        label: 'Firmware Analyst' },
  exploit_developer: { color: '#ef4444', icon: <Bomb size={14} />,       label: 'Exploit Dev' },
  code_auditor:      { color: '#6b7280', icon: <Shield size={14} />,     label: 'Code Auditor' },
  documentation:     { color: '#10b981', icon: <FileText size={14} />,   label: 'Documentation' },
  'ai-reo':          { color: '#06b6d4', icon: <Bot size={14} />,        label: 'AI-REO' },
  direct_chat:       { color: '#06b6d4', icon: <Bot size={14} />,        label: 'AI-REO' },
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

// ---------------------------------------------------------------------------
// Slash command definitions
// ---------------------------------------------------------------------------
const SLASH_COMMANDS: Array<{
  cmd: string; desc: string;
  transform?: (args: string) => string;
  localHandler?: boolean;
}> = [
  { cmd: '/ask',         desc: 'Ask a question — fast answer, no agents',     transform: (a) => a },
  { cmd: '/analyze',     desc: 'Full multi-agent pipeline',                    transform: (a) => a || 'Perform comprehensive reverse engineering analysis.' },
  { cmd: '/next',        desc: 'Suggest and execute the next best step',       transform: () => 'Based on findings so far, suggest and execute the most impactful next analysis step.' },
  { cmd: '/static',      desc: 'Static analysis — structure, sections, entropy', transform: () => 'Perform comprehensive static analysis: file format, sections, headers, entropy, imports, exports, strings, and disassemble key functions.' },
  { cmd: '/dynamic',     desc: 'Dynamic / runtime analysis',                   transform: () => 'Perform dynamic analysis to observe runtime behavior, API calls, and memory access patterns.' },
  { cmd: '/strings',     desc: 'Extract and analyze printable strings',        transform: () => 'Extract all printable strings. Highlight interesting artifacts: URLs, credentials, error messages, function names, paths.' },
  { cmd: '/imports',     desc: 'Analyze imported functions / libraries',       transform: () => 'Analyze all imported functions and libraries. Flag suspicious or security-relevant API calls.' },
  { cmd: '/exports',     desc: 'List exported symbols',                        transform: () => 'List and analyze all exported symbols and functions.' },
  { cmd: '/entrypoint',  desc: 'Locate and analyze entry point',              transform: () => 'Find the binary entry point (EP). Disassemble the first 50 instructions. Identify startup routines.' },
  { cmd: '/disasm',      desc: 'Disassemble a function or region',            transform: (a) => a ? `Disassemble and explain: ${a}` : 'Disassemble and explain main() or the entry point function.' },
  { cmd: '/decompile',   desc: 'Decompile to high-level pseudocode',          transform: (a) => a ? `Decompile to readable pseudocode: ${a}` : 'Decompile the most important functions using Ghidra.' },
  { cmd: '/crypto',      desc: 'Detect cryptographic routines',               transform: () => 'Identify all cryptographic algorithms, constants, and routines in the binary.' },
  { cmd: '/packer',      desc: 'Detect packing / obfuscation / DRM',          transform: () => 'Detect packing, compression, encryption, or protection. Check entropy, look for packer signatures (UPX, ASPACK, VMProtect, Themida, etc.), and report all indicators.' },
  { cmd: '/unpack',      desc: 'Attempt to unpack / decompress',              transform: () => 'Attempt to unpack or decompress the binary. Try UPX decompression, locate the OEP, and analyze the unpacked payload.' },
  { cmd: '/obfuscation', desc: 'Identify obfuscation techniques',             transform: () => 'Identify all obfuscation techniques: code flow, string encoding, junk code, opaque predicates, VM-based protection.' },
  { cmd: '/vuln',        desc: 'Scan for vulnerabilities',                    transform: () => 'Search for potential vulnerabilities: buffer overflows, format strings, dangerous function calls, memory corruption patterns.' },
  { cmd: '/logic',       desc: 'Analyze program logic / control flow',        transform: () => 'Map the main program logic: control flow graph, key decision branches, and execution paths.' },
  { cmd: '/run',         desc: 'Execute a specific tool directly',            transform: (a) => `Execute this specific analysis and report results: ${a}` },
  { cmd: '/script',      desc: 'Generate and save a reusable script',         transform: (a) => `Write, execute, and save a reusable analysis script for: ${a}. Use scripts_write to save it to the persistent shared scripts directory.` },
  { cmd: '/tools',       desc: 'List all available tools and readiness status',      localHandler: true },
  { cmd: '/agents',      desc: 'List all analysis agents, roles and tools',           localHandler: true },
  { cmd: '/help',        desc: 'Show all slash commands with descriptions',           localHandler: true },
  { cmd: '/skills',      desc: 'List loaded skills and which agents use them',        localHandler: true },
  { cmd: '/stop',        desc: 'Pause analysis',                              localHandler: true },
  { cmd: '/resume',      desc: 'Resume analysis',                             localHandler: true },
  { cmd: '/documentation', desc: 'Generate detailed report of current analysis findings', transform: () => 'Generate a comprehensive documentation report summarizing all findings discovered so far. Include binary metadata, discovered functions, strings, imports, vulnerabilities, and an executive summary. Update the Knowledge Graph with any missing nodes.' },
  { cmd: '/knowledge_import', desc: 'Import & merge a Knowledge Graph from an exported session', localHandler: true },
];

export const AnalysisDashboard: React.FC<DashboardProps> = ({ sessionName, onGoToSettings, onGoToTools, onGoToAgents, onBackToSessions }) => {
  const { isConnected, logs, session, sendCommand, clearLogs } = useWs();
  const [goal, setGoal] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisDone, setAnalysisDone] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [userMessages, setUserMessages] = useState<{ id: string; text: string; ts: string }[]>([]);
  const [localMessages, setLocalMessages] = useState<{ id: string; agent: string; text: string; ts: string }[]>([]);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [currentGoal, setCurrentGoal] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [slashMenuIndex, setSlashMenuIndex] = useState<number>(-1);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const kgImportRef = useRef<HTMLInputElement>(null);

  // Normalize a DB history row into the same shape as a live WS LogMessage entry
  const normalizeHistoryEntry = (h: any): any => {
    if (h.type === 'tool_result') {
      return {
        id: h.id,
        type: 'tool_result' as const,
        timestamp: h.timestamp ? new Date(h.timestamp).toLocaleTimeString() : '',
        content: {
          agent: h.agent,
          tool: h.tool,
          result_preview: h.result_preview || '',
          exit_code: h.exit_code,
        },
      };
    }
    // Default: chat_message — agent field drives specific rendering (user/orchestrator/agent)
    return {
      id: h.id,
      type: 'chat_message' as const,
      timestamp: h.timestamp ? new Date(h.timestamp).toLocaleTimeString() : '',
      content: {
        agent: h.agent,
        content: h.response || '',
        goal_completed: false,
        findings_count: 0,
      },
    };
  };

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

  // Drive completion from the analysis_complete WebSocket event so the
  // indicator persists for the full pipeline duration (not just HTTP round-trip)
  useEffect(() => {
    const done = logs.find(l => l.type === 'analysis_complete');
    if (!done || !analyzing) return;
    setAnalyzing(false);
    setAnalysisDone(true);
    setIsPaused(false);
    setActiveAgent(null);
    setCurrentGoal(null);
    if (session) {
      fetch(`${API}/sessions/${session}/history`)
        .then(r => r.ok ? r.json() : [])
        .then(data => { setHistory(data); clearLogs(); setUserMessages([]); })
        .catch(() => {});
    }
  }, [logs]);

  const handleTogglePause = () => {
    sendCommand('toggle_pause');
  };

  const handleKgImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !session) return;
    e.target.value = '';
    try {
      const text = await file.text();
      const graphData = JSON.parse(text);
      const res = await fetch(`${API}/sessions/${session}/kg/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(graphData),
      });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || 'Import failed');
      setUserMessages(prev => [...prev, {
        id: `import-${Date.now()}`,
        text: `[/knowledge_import] Imported ${result.imported} node(s) from ${file.name}. ${result.skipped} duplicate(s) skipped.`,
        ts: new Date().toLocaleTimeString(),
      }]);
    } catch (err: any) {
      setErrorBanner(`KG import failed: ${err.message}`);
    }
  };

  // -------------------------------------------------------------------------
  // Slash command & submission logic
  // -------------------------------------------------------------------------

  const submitGoal = async (goalText: string, displayText?: string, mode?: string) => {
    if (!goalText.trim() || !session) return;
    const displayMsg = displayText || goalText;
    const msg = { id: `user-${Date.now()}`, text: displayMsg, ts: new Date().toLocaleTimeString() };
    setUserMessages(prev => [...prev, msg]);
    setAnalyzing(true);
    setAnalysisDone(false);
    setIsPaused(false);
    setErrorBanner(null);
    setActiveAgent(null);
    setCurrentGoal(null);
    setGoal('');
    setSlashMenuIndex(-1);
    try {
      const body: Record<string, string> = { goal: goalText };
      if (mode) body.mode = mode;
      const res = await fetch(`${API}/sessions/${session}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        // HTTP-level failure (e.g. 500): the WS event won't arrive, so reset manually
        setAnalyzing(false);
        setErrorBanner('Analysis failed. Check the server logs.');
      }
      // On success the analysis_complete WS event drives all completion state
    } catch {
      setAnalyzing(false);
      setErrorBanner('Network error: could not reach the server.');
    }
  };

  const parseAndSubmit = (rawInput: string) => {
    const trimmed = rawInput.trim();
    if (!trimmed || !session) return;

    if (trimmed.startsWith('/')) {
      const spaceIdx = trimmed.indexOf(' ');
      const cmdPart = (spaceIdx === -1 ? trimmed : trimmed.slice(0, spaceIdx)).toLowerCase();
      const argsPart = spaceIdx === -1 ? '' : trimmed.slice(spaceIdx + 1).trim();

      const slashCmd = SLASH_COMMANDS.find(c => c.cmd === cmdPart);

      // Local-only commands — never call the LLM
      if (slashCmd?.localHandler) {
        setGoal('');

        if (cmdPart === '/stop')   { sendCommand('pause');  return; }
        if (cmdPart === '/resume') { sendCommand('resume'); return; }
        if (cmdPart === '/knowledge_import') {
          kgImportRef.current?.click();
          return;
        }

        // Show user message immediately
        setUserMessages(prev => [...prev, {
          id: `user-${Date.now()}`, text: trimmed, ts: new Date().toLocaleTimeString(),
        }]);

        const ts = new Date().toLocaleTimeString();
        const localId = `local-${Date.now()}`;

        if (cmdPart === '/help') {
          const helpMd = [
            '## Available Slash Commands\n',
            '| Command | Description |',
            '|---------|-------------|',
            ...SLASH_COMMANDS.map(c => `| \`${c.cmd}\` | ${c.desc} |`),
          ].join('\n');
          setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: helpMd, ts }]);
          return;
        }

        if (cmdPart === '/tools') {
          fetch(`${API}/tools/status?ts=${Date.now()}`, { cache: 'no-store' })
            .then(r => r.ok ? r.json() : Promise.reject('API error'))
            .then(data => {
              const toolList: any[] = Object.values(data.tools || {});
              const docker = toolList.filter((t: any) => t.docker_required);
              const builtin = toolList.filter((t: any) => !t.docker_required);
              const lines = [
                `## Tools Status (${toolList.length} total)\n`,
                `**Docker:** ${data.docker?.available ? `✓ Connected (v${data.docker.server_version})` : '✗ Not available'}\n`,
              ];
              if (builtin.length > 0) {
                lines.push('### Built-in Tools (always ready)');
                lines.push('| Tool | Description |');
                lines.push('|------|-------------|');
                builtin.forEach((t: any) => lines.push(`| \`${t.name}\` | ${t.description || 'Built-in'} |`));
                lines.push('');
              }
              if (docker.length > 0) {
                lines.push('### Docker-Based Tools');
                lines.push('| Tool | Status | Image |');
                lines.push('|------|--------|-------|');
                docker.forEach((t: any) => lines.push(
                  `| \`${t.name}\` | ${t.ready ? '✓ Ready' : '✗ Not ready'} | \`${t.image}\` |`
                ));
              }
              setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: lines.join('\n'), ts }]);
            })
            .catch(() => setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: '⚠ Could not reach /tools/status API.', ts }]));
          return;
        }

        if (cmdPart === '/agents') {
          fetch(`${API}/agents`)
            .then(r => r.ok ? r.json() : Promise.reject('API error'))
            .then((data: any[]) => {
              const lines = [
                `## Analysis Agents (${data.length} registered)\n`,
                '| Agent | Description | Primary Tools |',
                '|-------|-------------|---------------|',
                ...data.map(a => `| **${a.name}** | ${a.description.split('.')[0]}. | ${a.primary_tools} |`),
              ];
              setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: lines.join('\n'), ts }]);
            })
            .catch(() => setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: '⚠ Could not reach /agents API.', ts }]));
          return;
        }

        if (cmdPart === '/skills') {
          fetch(`${API}/skills`)
            .then(r => r.ok ? r.json() : Promise.reject('API error'))
            .then((data: any[]) => {
              if (data.length === 0) {
                setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: 'No skills loaded. Add `.md` skill files to the `src/ai_reo/skills/` directory.', ts }]);
                return;
              }
              const lines = [
                `## Loaded Skills (${data.length})\n`,
                '| Skill | For Agents | Tags |',
                '|-------|------------|------|',
                ...data.map((s: any) => `| **${s.name}** | ${s.universal ? 'All agents' : s.targets.join(', ')} | ${s.tags.join(', ')} |`),
              ];
              setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: lines.join('\n'), ts }]);
            })
            .catch(() => setLocalMessages(prev => [...prev, { id: localId, agent: 'ai-reo', text: '⚠ Could not reach /skills API.', ts }]));
          return;
        }

        return;
      }

      if (slashCmd?.transform) {
        const transformed = slashCmd.transform(argsPart);
        // /next sends with continuation mode to bypass intent classifier
        const mode = cmdPart === '/next' ? 'continuation' : undefined;
        submitGoal(transformed || argsPart || trimmed, trimmed, mode);
        return;
      }
    }

    submitGoal(trimmed);
  };

  const handleAnalyze = (e: React.FormEvent) => {
    e.preventDefault();
    if (!goal.trim() || !session || analyzing) return;
    parseAndSubmit(goal);
  };

  const renderLogEntry = (log: LogEntry): React.ReactNode => {
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

      // Auto-detect JSON responses and format them as code blocks
      const trimmedContent = rawContent.trim();
      const looksLikeJson = (trimmedContent.startsWith('{') || trimmedContent.startsWith('[')) && !trimmedContent.startsWith('```');
      let displayContent = rawContent;
      if (looksLikeJson) {
        try {
          displayContent = '```json\n' + JSON.stringify(JSON.parse(trimmedContent), null, 2) + '\n```';
        } catch { /* leave as-is if not valid JSON */ }
      }

      return (
        <div className="chat-msg" style={{ borderLeftColor: style.color }}>
          <div className="chat-msg-header">
            <span style={{ color: style.color }}>{style.icon}</span>
            <span className="chat-msg-agent" style={{ color: style.color }}>{style.label}</span>
            {content?.goal_completed && <span className="chat-msg-badge chat-msg-badge-done">Done</span>}
            {content?.findings_count > 0 && (
              <span className="chat-msg-badge chat-msg-badge-findings">+{content.findings_count} findings</span>
            )}
          </div>
          <div className="chat-msg-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayContent}</ReactMarkdown>
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
    if (type === 'analysis_complete') return null; // shown via analysisDone state

    return null;
  };

  return (
    <div className="dashboard animate-fade-in">

      {/* Hidden file input for /knowledge_import */}
      <input
        ref={kgImportRef}
        type="file"
        accept=".json"
        style={{ display: 'none' }}
        onChange={handleKgImport}
      />

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
          {onGoToAgents && (
            <button onClick={onGoToAgents} className="dashboard-action-btn">
              <Brain size={14} /> Agents
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
              <div key={m.id} className="animate-fade-in feed-entry">
                <span className="mono feed-timestamp">{m.ts}</span>
                <div className="chat-msg chat-msg-user-bubble">
                  <div className="chat-msg-header">
                    <span className="chat-msg-agent" style={{ color: 'var(--accent-primary)' }}>You</span>
                  </div>
                  <div className="chat-msg-body">{m.text}</div>
                </div>
              </div>
            ))}

            {/* Local slash-command responses (tools/agents/help/skills) */}
            {localMessages.map(m => {
              const style = getAgentStyle(m.agent);
              return (
                <div key={m.id} className="animate-fade-in feed-entry">
                  <span className="mono feed-timestamp">{m.ts}</span>
                  <div className="chat-msg" style={{ borderLeftColor: style.color }}>
                    <div className="chat-msg-header">
                      <span style={{ color: style.color }}>{style.icon}</span>
                      <span className="chat-msg-agent" style={{ color: style.color }}>{style.label}</span>
                    </div>
                    <div className="chat-msg-body">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              );
            })}

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

            {/* Analysis complete badge — shown after pipeline finishes, persists until next submit */}
            {!analyzing && analysisDone && (
              <div className="feed-analysis-complete animate-fade-in">
                <span style={{ color: 'var(--success)' }}>&#10003;</span> Analysis complete — type a follow-up or new goal
              </div>
            )}
          </div>
        </div>

        {/* Knowledge Graph Panel */}
        <GraphPanel sessionId={session} isActive={analyzing} />
      </div>

      {/* Input Bar */}
      <div className="glass-panel dashboard-input-bar">
        {/* Slash command menu */}
        {goal.startsWith('/') && !analyzing && (() => {
          const q = goal.toLowerCase();
          const matches = SLASH_COMMANDS.filter(
            c => c.cmd.startsWith(q) || (c as any).aliases?.some((a: string) => a.startsWith(q))
          );
          if (matches.length === 0) return null;
          return (
            <div className="slash-menu">
              {matches.map((c, idx) => (
                <button
                  key={c.cmd}
                  className={`slash-menu-item${slashMenuIndex === idx ? ' slash-menu-item-active' : ''}`}
                  type="button"
                  onMouseDown={e => { e.preventDefault(); setGoal(c.cmd + ' '); setSlashMenuIndex(-1); inputRef.current?.focus(); }}
                >
                  <span className="slash-menu-cmd">{c.cmd}</span>
                  <span className="slash-menu-desc">{c.desc}</span>
                </button>
              ))}
            </div>
          );
        })()}
        <form onSubmit={handleAnalyze} className="dashboard-input-form">
          <textarea
            ref={inputRef}
            className="input mono dashboard-textarea"
            placeholder="Type a message, goal, or /command…"
            value={goal}
            rows={1}
            onChange={e => { setGoal(e.target.value); setSlashMenuIndex(-1); }}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                // If slash menu is open and an item is highlighted, complete it
                if (goal.startsWith('/') && !analyzing) {
                  const q = goal.toLowerCase();
                  const matches = SLASH_COMMANDS.filter(
                    c => c.cmd.startsWith(q) || (c as any).aliases?.some((a: string) => a.startsWith(q))
                  );
                  if (slashMenuIndex >= 0 && slashMenuIndex < matches.length) {
                    e.preventDefault();
                    setGoal(matches[slashMenuIndex].cmd + ' ');
                    setSlashMenuIndex(-1);
                    return;
                  }
                }
                e.preventDefault();
                handleAnalyze(e as unknown as React.FormEvent);
              }
              if ((e.key === 'Tab' || e.key === 'ArrowDown') && goal.startsWith('/') && !analyzing) {
                e.preventDefault();
                const q = goal.toLowerCase();
                const matches = SLASH_COMMANDS.filter(
                  c => c.cmd.startsWith(q) || (c as any).aliases?.some((a: string) => a.startsWith(q))
                );
                if (matches.length > 0) {
                  const next = (slashMenuIndex + 1) % matches.length;
                  setSlashMenuIndex(next);
                  // If only one match, complete it immediately on Tab
                  if (matches.length === 1) { setGoal(matches[0].cmd + ' '); setSlashMenuIndex(-1); }
                }
              }
              if (e.key === 'ArrowUp' && goal.startsWith('/') && !analyzing) {
                e.preventDefault();
                const q = goal.toLowerCase();
                const matches = SLASH_COMMANDS.filter(
                  c => c.cmd.startsWith(q) || (c as any).aliases?.some((a: string) => a.startsWith(q))
                );
                if (matches.length > 0) {
                  setSlashMenuIndex(prev => prev <= 0 ? matches.length - 1 : prev - 1);
                }
              }
              if (e.key === 'Escape') { setSlashMenuIndex(-1); }
            }}
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

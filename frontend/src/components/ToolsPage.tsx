import React, { useEffect, useState, useCallback } from 'react';
import { Wrench, Check, X, Download, Loader2, Server, ArrowRight, RefreshCw } from 'lucide-react';

const API = 'http://localhost:9000';

interface ToolInfo {
  name: string;
  ready: boolean;
  docker_required: boolean;
  docker_available: boolean;
  image: string;
  image_available: boolean;
  error: string | null;
}

interface DockerInfo {
  available: boolean;
  server_version?: string;
  images_count?: number;
  containers_running?: number;
  error?: string;
}

interface ToolsPageProps {
  onContinue: () => void;
  onGoToSettings?: () => void;
}

export const ToolsPage: React.FC<ToolsPageProps> = ({ onContinue, onGoToSettings }) => {
  const [tools, setTools] = useState<Record<string, ToolInfo>>({});
  const [docker, setDocker] = useState<DockerInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [settingUp, setSettingUp] = useState<string | null>(null); // tool name being set up, or 'all'
  const [testingTool, setTestingTool] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; message: string }>>({});

  const fetchStatus = useCallback(async (showSpinner: boolean = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const res = await fetch(`${API}/tools/status?ts=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error('Failed to fetch');
      const data = await res.json();
      setTools(data.tools || {});
      setDocker(data.docker || null);
      setTestResults({});
    } catch (err) {
      console.error('Failed to fetch tool status:', err);
    } finally {
      setLoading(false);
      if (showSpinner) setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const setupTool = async (toolName: string) => {
    setSettingUp(toolName);
    try {
      await fetch(`${API}/tools/${toolName}/setup`, { method: 'POST' });
      await fetchStatus();
    } catch (err) {
      console.error(`Failed to set up ${toolName}:`, err);
    } finally {
      setSettingUp(null);
    }
  };

  const setupAll = async () => {
    setSettingUp('all');
    try {
      await fetch(`${API}/tools/setup`, { method: 'POST' });
      await fetchStatus();
    } catch (err) {
      console.error('Failed to set up all tools:', err);
    } finally {
      setSettingUp(null);
    }
  };

  const testTool = async (toolName: string) => {
    setTestingTool(toolName);
    try {
      const res = await fetch(`${API}/tools/${toolName}/test`, { method: 'POST' });
      const data = await res.json();
      setTestResults(prev => ({
        ...prev,
        [toolName]: { ok: data.ok, message: data.ok ? 'Test passed' : (data.error || 'Test failed') },
      }));
    } catch (err: any) {
      setTestResults(prev => ({ ...prev, [toolName]: { ok: false, message: err.message } }));
    } finally {
      setTestingTool(null);
    }
  };

  const allReady = Object.values(tools).every(t => t.ready);
  const dockerTools = Object.values(tools).filter(t => t.docker_required);
  const nonDockerTools = Object.values(tools).filter(t => !t.docker_required);
  const missingCount = dockerTools.filter(t => !t.ready).length;

  if (loading) {
    return (
      <div className="page-container animate-fade-in">
        <div className="tools-loading">
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-primary)' }} />
          <span>Checking tool readiness...</span>
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
            <Wrench size={24} color="var(--accent-primary)" />
            <h1 className="tools-title">Analysis Tools</h1>
          </div>
          <p className="tools-subtitle">
            AI-REO uses Docker containers to run reverse engineering tools securely.
            Ensure all required tool images are available before starting analysis.
          </p>
          <div style={{ marginTop: '0.75rem', display: 'flex', gap: '0.5rem' }}>
            <button
              className="tools-refresh-btn"
              onClick={async () => {
                setRefreshing(true);
                try {
                  await fetch(`${API}/tools/setup/environment`, { method: 'POST' });
                } finally {
                  await fetchStatus(false);
                  setRefreshing(false);
                }
              }}
              disabled={refreshing || !!settingUp}
            >
              <Server size={14} /> {refreshing ? 'Preparing...' : 'Environment Setup'}
            </button>
          </div>
        </div>

        {/* Docker Status Banner */}
        <div className={`tools-docker-banner ${docker?.available ? 'tools-docker-ok' : 'tools-docker-err'}`}>
          <Server size={18} />
          <div className="tools-docker-info">
            <span className="tools-docker-label">Docker Daemon</span>
            {docker?.available ? (
              <span className="tools-docker-detail">
                Connected — v{docker.server_version} • {docker.images_count} images • {docker.containers_running} running
              </span>
            ) : (
              <span className="tools-docker-detail">
                Not available — {docker?.error || 'Docker Desktop may not be running'}
              </span>
            )}
          </div>
          {docker?.available ? <Check size={18} /> : <X size={18} />}
        </div>

        {/* Docker Tools */}
        {dockerTools.length > 0 && (
          <div className="tools-section">
            <div className="tools-section-header">
              <h2 className="tools-section-title">Docker-Based Tools</h2>
              {missingCount > 0 && docker?.available && (
                <button
                  className="btn-primary tools-setup-all"
                  onClick={setupAll}
                  disabled={!!settingUp}
                >
                  {settingUp === 'all' ? (
                    <><Loader2 size={14} className="animate-spin" /> Pulling...</>
                  ) : (
                    <><Download size={14} /> Setup All ({missingCount} missing)</>
                  )}
                </button>
              )}
            </div>

            <div className="tools-grid">
              {dockerTools.map(tool => (
                <div key={tool.name} className={`tools-card ${tool.ready ? 'tools-card-ready' : 'tools-card-missing'}`}>
                  <div className="tools-card-header">
                    <span className="tools-card-name">{tool.name}</span>
                    {tool.ready ? (
                      <span className="tools-status-badge tools-status-ready"><Check size={12} /> Ready</span>
                    ) : (
                      <span className="tools-status-badge tools-status-missing"><X size={12} /> Not Ready</span>
                    )}
                  </div>
                  <code className="tools-card-image">{tool.image}</code>
                  {!tool.ready && docker?.available && (
                    <button
                      className="tools-card-setup"
                      onClick={() => setupTool(tool.name)}
                      disabled={!!settingUp}
                    >
                      {settingUp === tool.name ? (
                        <><Loader2 size={12} className="animate-spin" /> Pulling...</>
                      ) : (
                        <><Download size={12} /> Setup</>
                      )}
                    </button>
                  )}
                  {tool.error && <span className="tools-card-error">{tool.error}</span>}
                  {!tool.ready && tool.image.startsWith('ai-reo/') && (
                    <span className="tools-card-error">This image is built locally from the repo Dockerfiles during Setup.</span>
                  )}
                  {tool.ready && (
                    <button
                      className="tools-card-test"
                      onClick={() => testTool(tool.name)}
                      disabled={!!testingTool}
                    >
                      {testingTool === tool.name ? (
                        <><Loader2 size={12} className="animate-spin" /> Testing...</>
                      ) : (
                        <>⚡ Test</>
                      )}
                    </button>
                  )}
                  {testResults[tool.name] && (
                    <span className={`tools-card-test-result ${testResults[tool.name].ok ? 'tools-test-ok' : 'tools-test-fail'}`}>
                      {testResults[tool.name].ok ? '✓' : '✗'} {testResults[tool.name].message}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Non-Docker Tools */}
        {nonDockerTools.length > 0 && (
          <div className="tools-section">
            <h2 className="tools-section-title">Built-in Tools</h2>
            <div className="tools-grid">
              {nonDockerTools.map(tool => (
                <div key={tool.name} className="tools-card tools-card-ready">
                  <div className="tools-card-header">
                    <span className="tools-card-name">{tool.name}</span>
                    <span className="tools-status-badge tools-status-ready"><Check size={12} /> Ready</span>
                  </div>
                  <span className="tools-card-image" style={{ color: 'var(--text-muted)' }}>No Docker required</span>
                  <button
                    className="tools-card-test"
                    onClick={() => testTool(tool.name)}
                    disabled={!!testingTool}
                  >
                    {testingTool === tool.name ? (
                      <><Loader2 size={12} className="animate-spin" /> Testing...</>
                    ) : (
                      <>⚡ Test</>
                    )}
                  </button>
                  {testResults[tool.name] && (
                    <span className={`tools-card-test-result ${testResults[tool.name].ok ? 'tools-test-ok' : 'tools-test-fail'}`}>
                      {testResults[tool.name].ok ? '✓' : '✗'} {testResults[tool.name].message}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="tools-actions">
          {onGoToSettings && (
            <button className="tools-back-btn" onClick={onGoToSettings}>
              ← Back to Providers
            </button>
          )}
          <button className="tools-refresh-btn" onClick={() => fetchStatus(true)} disabled={!!settingUp || refreshing}>
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} /> {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <button className="btn-primary tools-continue-btn" onClick={onContinue}>
            {allReady ? 'Continue to Sessions' : 'Skip (some tools missing)'}
            <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
};

import React, { useState, useEffect, useRef } from 'react';
import {
  Cpu, Plus, UploadCloud, Terminal, Play, Pencil, Download,
  Trash2, X, Check, FolderOpen, Settings, Hash, Calendar, Clock, Bot, Wrench, Brain,
} from 'lucide-react';

const API = 'http://localhost:9000';

interface SessionInfo {
  id: string;
  name: string | null;
  status: string;
  binary_path: string;
  binary_hash: string;
  working_dir: string | null;
  created_at: string;
}

interface SessionsPageProps {
  onOpenSession: (session: SessionInfo) => void;
  onGoToSettings?: () => void;
  onGoToTools?: () => void;
  onGoToAgents?: () => void;
}

export const SessionsPage: React.FC<SessionsPageProps> = ({ onOpenSession, onGoToSettings, onGoToTools, onGoToAgents }) => {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [uploadText, setUploadText] = useState('');
  const [uploadError, setUploadError] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  const [sessionName, setSessionName] = useState('');
  const [extractedFiles, setExtractedFiles] = useState<string[]>([]);
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  const [pendingHash, setPendingHash] = useState<string>('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Rename state
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [autoRunRunning, setAutoRunRunning] = useState(false);

  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API}/sessions`);
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
      }
    } catch { /* backend may be down */ }
    setLoading(false);
  };

  useEffect(() => { fetchSessions(); }, []);

  // ---- Upload flow ----
  const processFile = async (file: File) => {
    setUploading(true);
    setUploadError('');

    try {
      setUploadText('Creating session...');
      const name = sessionName.trim() || `${file.name} @ ${new Date().toLocaleString()}`;
      const createRes = await fetch(`${API}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ binary_path: file.name, binary_hash: 'pending', name }),
      });
      const session = await createRes.json();
      if (!createRes.ok) throw new Error(session.message || session.detail || 'Failed to create session');

      if (file.name.toLowerCase().endsWith('.zip')) {
        // ZIP: extract into session workspace, then show file picker
        setUploadText('Extracting ZIP archive...');
        const formData = new FormData();
        formData.append('file', file);
        const uploadRes = await fetch(`${API}/sessions/upload-zip?session_id=${session.id}`, {
          method: 'POST',
          body: formData,
        });
        const uploadData = await uploadRes.json();
        if (!uploadRes.ok) throw new Error(uploadData.message || uploadData.detail || 'ZIP extraction failed');

        // Show file picker — user selects primary binary
        setUploading(false);
        setExtractedFiles(uploadData.filenames);
        setPendingSessionId(session.id);
        setPendingHash(uploadData.binary_hash);
        setUploadText('');
        return;
      }

      // Regular binary: upload directly
      setUploadText('Uploading binary...');
      const formData = new FormData();
      formData.append('file', file);
      const uploadRes = await fetch(`${API}/sessions/upload?session_id=${session.id}`, {
        method: 'POST',
        body: formData,
      });
      const uploadData = await uploadRes.json();
      if (!uploadRes.ok) throw new Error(uploadData.message || uploadData.detail || 'Upload failed');

      setUploadText('Finalizing...');
      await fetch(`${API}/sessions/upload/${session.id}/finalize?binary_hash=${uploadData.binary_hash}`, {
        method: 'PATCH',
      });

      setUploading(false);
      setShowUpload(false);
      setSessionName('');
      fetchSessions();

    } catch (err: any) {
      setUploadError(err.message || String(err));
      setUploading(false);
    }
  };

  const finalizeZipSession = async (primaryFile: string) => {
    if (!pendingSessionId) return;
    try {
      // Update session binary_path to the chosen file and finalize hash
      await fetch(`${API}/sessions/${pendingSessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: sessionName.trim() || `${primaryFile} @ ${new Date().toLocaleString()}` }),
      });
      await fetch(`${API}/sessions/upload/${pendingSessionId}/finalize?binary_hash=${pendingHash}`, {
        method: 'PATCH',
      });
      setExtractedFiles([]);
      setPendingSessionId(null);
      setPendingHash('');
      setShowUpload(false);
      setSessionName('');
      fetchSessions();
    } catch (err: any) {
      setUploadError(err.message || String(err));
    }
  };

  // ---- Session actions ----
  const handleRename = async (id: string) => {
    if (!renameValue.trim()) return;
    try {
      await fetch(`${API}/sessions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: renameValue.trim() }),
      });
      setRenamingId(null);
      fetchSessions();
    } catch { /* silently fail */ }
  };

  const handleDelete = async (id: string, name: string | null) => {
    if (!confirm(`Delete session "${name || id}"? This cannot be undone.`)) return;
    try {
      await fetch(`${API}/sessions/${id}`, { method: 'DELETE' });
      fetchSessions();
    } catch { /* silently fail */ }
  };

  const handleExport = (id: string) => {
    window.open(`${API}/sessions/${id}/export`, '_blank');
  };

  const statusColor = (s: string) => {
    if (s === 'completed') return 'var(--success)';
    if (s === 'active') return 'var(--accent-primary)';
    if (s === 'error') return 'var(--danger)';
    return 'var(--text-muted)';
  };

  // ---- Auto-run CTF Test ----
  const handleAutoRun = async () => {
    if (!confirm('Auto Run will create a new session from CTF_Level5.exe and auto-analyze it.\n\nProceed?')) return;
    setAutoRunRunning(true);
    try {
      const res = await fetch(`${API}/runs/ctf-test`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        alert(`Auto Run failed: ${err.detail || 'Unknown error'}`);
        return;
      }
      const data = await res.json();
      onOpenSession({
        id: data.session_id,
        name: data.session_name,
        status: data.status,
        binary_path: 'CTF_Level5.exe',
        binary_hash: data.binary_hash,
        working_dir: null,
        created_at: new Date().toISOString(),
      });
      setTimeout(() => {
        fetch(`${API}/sessions/${data.session_id}/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ goal: data.ctf_goal }),
        });
      }, 1500);
    } catch (e: any) {
      alert(`Auto Run error: ${e.message}`);
    } finally {
      setAutoRunRunning(false);
    }
  };

  return (
    <div className="sessions-page">
      <div className="sessions-container">

        {/* Header */}
        <div className="sessions-header">
          <div className="sessions-title-row">
            <Cpu size={32} color="var(--accent-primary)" />
            <div>
              <h1 className="sessions-title">AI-REO Sessions</h1>
              <p className="sessions-count">
                {sessions.length} session{sessions.length !== 1 ? 's' : ''}
              </p>
            </div>
          </div>
          <div className="sessions-actions">
            <button className="sessions-autorun-btn" onClick={handleAutoRun} disabled={autoRunRunning}>
              <Bot size={15} /> {autoRunRunning ? 'Running...' : 'Auto Run'}
            </button>
            <button className="sessions-tools-btn" onClick={onGoToTools}>
              <Wrench size={14} /> Tools
            </button>
            <button className="sessions-tools-btn" onClick={onGoToAgents}>
              <Brain size={14} /> Agents
            </button>
            <button className="sessions-settings-btn" onClick={onGoToSettings}>
              <Settings size={14} /> Providers
            </button>
            <button
              className="btn-primary sessions-new-btn"
              onClick={() => { setShowUpload(true); setUploadError(''); setSessionName(''); setExtractedFiles([]); setPendingSessionId(null); }}
            >
              <Plus size={15} /> New Analysis
            </button>
          </div>
        </div>

        {/* Upload Modal */}
        {showUpload && (
          <div className="glass-panel animate-fade-in sessions-upload-panel">
            <div className="sessions-upload-header">
              <h3>New Analysis Session</h3>
              <button className="sessions-close-btn" onClick={() => { setShowUpload(false); setExtractedFiles([]); setPendingSessionId(null); }}>
                <X size={18} />
              </button>
            </div>

            <label className="sessions-label">Session Name (optional)</label>
            <input
              type="text"
              className="input sessions-name-input"
              value={sessionName}
              onChange={e => setSessionName(e.target.value)}
              placeholder="e.g., CrackMe v2 Analysis"
            />

            <input
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              onChange={e => {
                if (e.target.files && e.target.files.length > 0) processFile(e.target.files[0]);
              }}
            />

            <div
              className={`sessions-dropzone ${isDragging ? 'sessions-dropzone-active' : ''}`}
              onClick={() => !uploading && fileInputRef.current?.click()}
              onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={e => {
                e.preventDefault();
                setIsDragging(false);
                if (!uploading && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                  processFile(e.dataTransfer.files[0]);
                }
              }}
            >
              {uploading ? (
                <Terminal size={36} color="var(--accent-primary)" className="animate-pulse" />
              ) : (
                <UploadCloud size={36} color={isDragging ? 'var(--accent-primary)' : 'var(--text-muted)'} />
              )}
              <div className={`sessions-dropzone-text ${isDragging ? 'sessions-dropzone-text-active' : ''}`}>
                {uploading ? uploadText : (isDragging ? 'Release to upload' : 'Drag & Drop binary here')}
              </div>
              {!uploading && <div className="sessions-dropzone-hint">or click to browse</div>}
            </div>

            {/* ZIP file picker: shown after extraction when user must pick primary binary */}
            {extractedFiles.length > 0 && (
              <div className="animate-fade-in" style={{ marginTop: '1rem' }}>
                <p style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                  {extractedFiles.length} file{extractedFiles.length !== 1 ? 's' : ''} extracted. Select the primary binary to analyze:
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', maxHeight: '200px', overflowY: 'auto' }}>
                  {extractedFiles.map(f => (
                    <button
                      key={f}
                      className="sessions-action-btn sessions-action-btn-primary"
                      style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontSize: '0.85rem', fontFamily: 'monospace' }}
                      onClick={() => finalizeZipSession(f)}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {uploadError && (
              <div className="animate-fade-in sessions-upload-error">{uploadError}</div>
            )}
          </div>
        )}

        {/* Session List */}
        {loading ? (
          <div className="sessions-loading">Loading sessions...</div>
        ) : sessions.length === 0 && !showUpload ? (
          <div className="glass-panel animate-fade-in sessions-empty">
            <FolderOpen size={48} color="var(--text-muted)" />
            <h2>No Sessions Yet</h2>
            <p>Click "New Analysis" to upload a binary and start your first reverse engineering session.</p>
            <button
              className="btn-primary sessions-empty-btn"
              onClick={() => { setShowUpload(true); setUploadError(''); setSessionName(''); }}
            >
              <Plus size={15} /> New Analysis
            </button>
          </div>
        ) : (
          <div className="sessions-list">
            {sessions.map(s => (
              <div
                key={s.id}
                className="glass-panel sessions-card"
              >
                {/* Status dot */}
                <div
                  className={`sessions-status-dot ${s.status === 'active' ? 'sessions-status-dot-active' : ''}`}
                  style={{ background: statusColor(s.status) }}
                />

                {/* Info */}
                <div className="sessions-card-info">
                  {renamingId === s.id ? (
                    <div className="sessions-rename-row">
                      <input
                        className="input sessions-rename-input"
                        value={renameValue}
                        onChange={e => setRenameValue(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') handleRename(s.id); if (e.key === 'Escape') setRenamingId(null); }}
                        autoFocus
                      />
                      <button className="sessions-icon-btn sessions-icon-btn-ok" onClick={() => handleRename(s.id)}><Check size={16} /></button>
                      <button className="sessions-icon-btn" onClick={() => setRenamingId(null)}><X size={16} /></button>
                    </div>
                  ) : (
                    <div className="sessions-card-name">{s.name || s.binary_path}</div>
                  )}
                  <div className="sessions-card-meta">
                    <span className="sessions-meta-item"><Hash size={11} /> {s.binary_hash?.substring(0, 12)}…</span>
                    <span className="sessions-meta-item"><Calendar size={11} /> {new Date(s.created_at).toLocaleDateString()}</span>
                    <span className="sessions-meta-item"><Clock size={11} /> {new Date(s.created_at).toLocaleTimeString()}</span>
                  </div>
                </div>

                {/* Status badge */}
                <span className="sessions-status-badge" style={{ background: `${statusColor(s.status)}22`, color: statusColor(s.status) }}>
                  {s.status}
                </span>

                {/* Actions */}
                <div className="sessions-card-actions">
                  <button className="sessions-action-btn sessions-action-btn-primary" onClick={() => onOpenSession(s)} title="Open / Resume">
                    <Play size={14} />
                  </button>
                  <button className="sessions-action-btn" onClick={() => { setRenamingId(s.id); setRenameValue(s.name || ''); }} title="Rename">
                    <Pencil size={14} />
                  </button>
                  <button className="sessions-action-btn" onClick={() => handleExport(s.id)} title="Export ZIP">
                    <Download size={14} />
                  </button>
                  <button className="sessions-action-btn sessions-action-btn-danger" onClick={() => handleDelete(s.id, s.name)} title="Delete">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

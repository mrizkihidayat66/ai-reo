import React, { useState, useRef } from 'react';
import { Terminal, Cpu, UploadCloud, Settings, FolderOpen } from 'lucide-react';

interface SessionManagerProps {
  onSessionCreated: (id: string, path: string) => void;
  onGoToSettings?: () => void;
}

export const SessionManager: React.FC<SessionManagerProps> = ({ onSessionCreated, onGoToSettings }) => {
  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState('');
  const [errorMsg, setError] = useState('');
  const [isDragging, setIsDragging] = useState(false);
  
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dirInputRef = useRef<HTMLInputElement>(null);

  const processZip = async (file: File) => {
    setLoading(true);
    setError('');
    try {
      // Step 1: Create session with pending hash
      setLoadingText('Creating session...');
      const sessionRes = await fetch('http://localhost:9000/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ binary_path: file.name, binary_hash: 'pending' }),
      });
      const sessionData = await sessionRes.json();
      if (!sessionRes.ok) throw new Error(sessionData.detail || 'Failed to create session');

      // Step 2: Upload and extract ZIP directly into this session's workspace
      setLoadingText('Uploading and extracting ZIP...');
      const formData = new FormData();
      formData.append('file', file);
      const uploadRes = await fetch(`http://localhost:9000/sessions/upload-zip?session_id=${sessionData.id}`, {
        method: 'POST',
        body: formData,
      });
      const uploadData = await uploadRes.json();
      if (!uploadRes.ok) throw new Error(uploadData.detail || 'ZIP upload failed');

      const primaryFile = uploadData.filenames[0];
      setLoadingText(`Extracted ${uploadData.filenames.length} file(s). Finalizing...`);

      // Step 3: Finalize session with primary file info
      await fetch(`http://localhost:9000/sessions/${sessionData.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: primaryFile }),
      });
      await fetch(`http://localhost:9000/sessions/upload/${sessionData.id}/finalize?binary_hash=${uploadData.binary_hash}`, {
        method: 'PATCH',
      });

      onSessionCreated(sessionData.id, primaryFile);
    } catch (err: any) {
      setError(err.message || String(err));
      setLoading(false);
    }
  };

  const processFile = async (file: File) => {
    // Detect ZIP files
    if (file.name.toLowerCase().endsWith('.zip')) {
      return processZip(file);
    }

    setLoading(true);
    setError('');
    
    try {
      // Step 1: Create the session with a pending hash so we get a unique session_id
      setLoadingText('Spawning AI Orchestrator sandbox...');
      const sessionRes = await fetch('http://localhost:9000/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ binary_path: file.name, binary_hash: 'pending' }),
      });
      const sessionData = await sessionRes.json();
      if (!sessionRes.ok) throw new Error(sessionData.message || sessionData.detail || 'Failed to create session');

      // Step 2: Upload binary directly into this session's workspace dir
      setLoadingText('Uploading payload securely...');
      const formData = new FormData();
      formData.append('file', file);
      const uploadRes = await fetch(`http://localhost:9000/sessions/upload?session_id=${sessionData.id}`, {
        method: 'POST',
        body: formData,
      });
      const uploadData = await uploadRes.json();
      if (!uploadRes.ok) throw new Error(uploadData.message || uploadData.detail || 'Upload failed');

      // Step 3: Finalize with real hash
      await fetch(`http://localhost:9000/sessions/upload/${sessionData.id}/finalize?binary_hash=${uploadData.binary_hash}`, {
        method: 'PATCH',
      });

      onSessionCreated(sessionData.id, uploadData.filename);
    } catch (err: any) {
      setError(err.message || String(err));
      setLoading(false);
    }
  };

  const processDirectory = async (files: FileList) => {
    if (files.length === 0) return;
    setLoading(true);
    setError('');

    try {
      const first = files[0];

      // Step 1: Create session first
      setLoadingText('Creating session...');
      const sessionRes = await fetch('http://localhost:9000/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ binary_path: first.name, binary_hash: 'pending' }),
      });
      const sessionData = await sessionRes.json();
      if (!sessionRes.ok) throw new Error(sessionData.detail || 'Failed to create session');

      // Step 2: Upload all files directly into session workspace
      setLoadingText(`Uploading ${files.length} file(s)...`);
      let primaryHash = '';
      for (let i = 0; i < files.length; i++) {
        setLoadingText(`Uploading file ${i + 1}/${files.length}...`);
        const fd = new FormData();
        fd.append('file', files[i]);
        const uploadRes = await fetch(`http://localhost:9000/sessions/upload?session_id=${sessionData.id}`, {
          method: 'POST',
          body: fd,
        });
        const uploadData = await uploadRes.json();
        if (!uploadRes.ok) throw new Error(uploadData.detail || 'Upload failed');
        if (i === 0) primaryHash = uploadData.binary_hash;
      }

      // Step 3: Finalize with the primary file hash
      await fetch(`http://localhost:9000/sessions/upload/${sessionData.id}/finalize?binary_hash=${primaryHash}`, {
        method: 'PATCH',
      });

      onSessionCreated(sessionData.id, first.name);
    } catch (err: any) {
      setError(err.message || String(err));
      setLoading(false);
    }
  };

  return (
    <div className="flex-center" style={{ height: '100%', padding: '2rem' }}>
      <div className="glass-panel animate-fade-in" style={{ padding: '3rem', maxWidth: '550px', width: '100%', textAlign: 'center' }}>
        <Cpu size={48} color="var(--accent-primary)" style={{ margin: '0 auto 1.5rem auto' }} className="animate-pulse" />
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
          <button
            onClick={onGoToSettings}
            style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.4rem 0.8rem', fontSize: '0.8rem', color: 'var(--text-muted)', border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)', background: 'var(--bg-tertiary)', cursor: 'pointer' }}
          >
            <Settings size={14} /> LLM Providers
          </button>
        </div>
        <h1 style={{ marginBottom: '0.5rem' }}>AI-REO Orchestrator</h1>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '2.5rem', lineHeight: 1.6 }}>
          Drop a binary straight into the portal to inject it into the secure Docker staging arena and deploy the autonomous agent team.
        </p>
        
        <input 
          type="file" 
          ref={fileInputRef}
          style={{ display: 'none' }} 
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              processFile(e.target.files[0]);
            }
          }} 
        />

        {/* Hidden directory input */}
        <input
          type="file"
          ref={dirInputRef}
          style={{ display: 'none' }}
          /* @ts-ignore — webkitdirectory is non-standard but widely supported */
          {...({ webkitdirectory: '', multiple: true } as any)}
          onChange={(e) => {
            if (e.target.files && e.target.files.length > 0) {
              processDirectory(e.target.files);
            }
          }}
        />

        {/* Interactive Drag & Drop Area */}
        <div 
          onClick={() => !loading && fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setIsDragging(false);
            if (!loading && e.dataTransfer.files && e.dataTransfer.files.length > 0) {
              processFile(e.dataTransfer.files[0]);
            }
          }}
          style={{
            border: `2px dashed ${isDragging ? 'var(--accent-primary)' : 'var(--border-color)'}`,
            borderRadius: 'var(--radius-lg)',
            padding: '4rem 2rem',
            background: isDragging ? 'rgba(92, 111, 255, 0.05)' : 'var(--bg-tertiary)',
            cursor: loading ? 'not-allowed' : 'pointer',
            transition: 'all 0.3s ease',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '1rem',
            boxShadow: isDragging ? 'var(--shadow-glow)' : 'none'
          }}
        >
          {loading ? (
            <Terminal size={40} color="var(--accent-primary)" className="animate-pulse" />
          ) : (
            <UploadCloud size={40} color={isDragging ? 'var(--accent-primary)' : 'var(--text-muted)'} />
          )}
          
          <div style={{ fontWeight: 500, color: isDragging ? 'var(--accent-primary)' : 'var(--text-primary)' }}>
            {loading ? loadingText : (isDragging ? 'Release to upload' : 'Drag & Drop binary or .zip here')}
          </div>
          {!loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.4rem' }}>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                or click to browse local files
              </div>
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); dirInputRef.current?.click(); }}
                style={{
                  fontSize: '0.8rem', color: 'var(--accent-primary)', background: 'transparent',
                  border: '1px solid var(--border-color)', borderRadius: 'var(--radius-sm)',
                  padding: '0.3rem 0.7rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.3rem',
                }}
              >
                <FolderOpen size={13} /> Select Directory
              </button>
            </div>
          )}
        </div>
        
        {errorMsg && (
          <div className="animate-fade-in" style={{ animation: 'fadeIn 0.3s', marginTop: '1.5rem', color: 'var(--danger)', fontSize: '0.9rem', textAlign: 'center', padding: '0.75rem', background: 'rgba(239,68,68,0.1)', borderRadius: 'var(--radius-sm)' }}>
            {errorMsg}
          </div>
        )}
      </div>
    </div>
  );
};

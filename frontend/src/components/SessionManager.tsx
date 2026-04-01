import React, { useState, useRef } from 'react';
import { Terminal, Cpu, UploadCloud, Settings } from 'lucide-react';

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

  const processFile = async (file: File) => {
    setLoading(true);
    setError('');
    
    try {
      // Step 1: Securely upload binary multipart chunk streams directly to staging
      setLoadingText('Uploading payload securely...');
      const formData = new FormData();
      formData.append('file', file);
      
      const uploadRes = await fetch('http://localhost:9000/sessions/upload', {
        method: 'POST',
        body: formData
      });
      
      const uploadData = await uploadRes.json();
      if (!uploadRes.ok) throw new Error(uploadData.message || uploadData.detail || 'Upload failed');
      
      // Step 2: Spawn the analysis session utilizing the securely synced hex payload
      setLoadingText('Spawning AI Orchestrator sandbox...');
      const sessionRes = await fetch('http://localhost:9000/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          binary_path: uploadData.filename, 
          binary_hash: uploadData.binary_hash 
        })
      });
      
      const sessionData = await sessionRes.json();
      if (!sessionRes.ok) throw new Error(sessionData.message || sessionData.detail || 'Failed to create session');
      
      onSessionCreated(sessionData.id, uploadData.filename);
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
            {loading ? loadingText : (isDragging ? 'Release to upload binary' : 'Drag & Drop binary here')}
          </div>
          {!loading && (
            <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              or click to browse local files
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

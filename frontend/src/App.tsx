import React, { useState } from 'react';
import { WsProvider, useWs } from './context/WebSocketContext';
import { ProvidersProvider, useProviders } from './context/ProvidersContext';
import { ProvidersPage } from './components/ProvidersPage';
import { ToolsPage } from './components/ToolsPage';
import { SessionsPage } from './components/SessionsPage';
import { AnalysisDashboard } from './components/AnalysisDashboard';

type Stage = 'setup' | 'tools' | 'sessions' | 'dashboard';

interface SessionInfo {
  id: string;
  name: string | null;
  status: string;
  binary_path: string;
  binary_hash: string;
  working_dir: string | null;
  created_at: string;
}

const OrchestratorView: React.FC = () => {
  const { connect } = useWs();
  const { providers } = useProviders();

  const [stage, setStage] = useState<Stage>(() =>
    providers.length > 0 ? 'sessions' : 'setup'
  );
  const [activeSession, setActiveSession] = useState<SessionInfo | null>(null);

  if (stage === 'setup') {
    return <ProvidersPage onContinue={() => setStage('tools')} />;
  }

  if (stage === 'tools') {
    return (
      <ToolsPage
        onContinue={() => setStage('sessions')}
        onGoToSettings={() => setStage('setup')}
      />
    );
  }

  if (stage === 'sessions') {
    return (
      <SessionsPage
        onOpenSession={(s) => {
          setActiveSession(s);
          connect(s.id);
          setStage('dashboard');
        }}
        onGoToSettings={() => setStage('setup')}
        onGoToTools={() => setStage('tools')}
      />
    );
  }

  return (
    <AnalysisDashboard
      sessionName={activeSession?.name || activeSession?.binary_path || 'Session'}
      onGoToSettings={() => setStage('setup')}
      onGoToTools={() => setStage('tools')}
      onBackToSessions={() => {
        setActiveSession(null);
        setStage('sessions');
      }}
    />
  );
};

function App() {
  return (
    <ProvidersProvider>
      <WsProvider>
        <OrchestratorView />
      </WsProvider>
    </ProvidersProvider>
  );
}

export default App;

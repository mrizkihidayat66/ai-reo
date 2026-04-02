import React, { createContext, useContext, useRef, useState } from 'react';
import type { ReactNode } from 'react';

export interface LogMessage {
  id: string;
  type: 'system' | 'agent_state_override' | 'agent_step' | 'chat_message' | 'tool_result' | 'tool_start' | 'tool_end' | 'error' | 'status' | 'pause_state' | 'analysis_complete';
  timestamp: string;
  content: any;
}

export interface WsContextType {
  isConnected: boolean;
  logs: LogMessage[];
  session: string | null;
  connect: (sessionId: string) => void;
  sendCommand: (cmd: 'pause' | 'resume' | 'toggle_pause') => void;
  disconnect: () => void;
  clearLogs: () => void;
}

const WsContext = createContext<WsContextType | undefined>(undefined);

export const WsProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [session, setSession] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [logs, setLogs] = useState<LogMessage[]>([]);
  const ws = useRef<WebSocket | null>(null);

  const connect = (sessionId: string) => {
    if (ws.current) ws.current.close();
    setSession(sessionId);
    setLogs([]); // Reset tracking for a fresh mount
    
    // Connect locally to the orchestrator stream endpoint built in Epic 6
    const socket = new WebSocket(`ws://localhost:9000/sessions/${sessionId}/ws`);
    ws.current = socket;

    socket.onopen = () => setIsConnected(true);
    socket.onclose = () => setIsConnected(false);
    
    socket.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        setLogs(prev => [...prev, {
          id: crypto.randomUUID(),
          type: msg.type || 'system',
          timestamp: new Date().toLocaleTimeString(),
          content: msg
        }]);
      } catch (err) {
        console.error("Failed to parse Ws payload", e.data);
      }
    };
  };

  const disconnect = () => {
    if (ws.current) {
      ws.current.close();
      ws.current = null;
    }
    setSession(null);
    setLogs([]);
  };

  const clearLogs = () => setLogs([]);

  const sendCommand = (cmd: 'pause' | 'resume') => {
    if (ws.current && isConnected) {
      ws.current.send(JSON.stringify({ command: cmd }));
    }
  };

  return (
    <WsContext.Provider value={{ isConnected, logs, session, connect, sendCommand, disconnect, clearLogs }}>
      {children}
    </WsContext.Provider>
  );
};

export const useWs = () => {
  const ctx = useContext(WsContext);
  if (!ctx) throw new Error("useWs must be wrapped in WsProvider");
  return ctx;
};

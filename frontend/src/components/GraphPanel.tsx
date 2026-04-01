import React, { useEffect, useState, useCallback } from 'react';
import { Database, ChevronDown, ChevronRight } from 'lucide-react';

const API = 'http://localhost:9000';

interface KGNode {
  id: string;
  node_type: string;
  address: string | null;
  name: string | null;
  data: Record<string, any>;
  created_by_agent: string;
  created_at: string;
}

interface GraphPanelProps {
  sessionId: string | null;
  isActive: boolean;
}

const TYPE_CONFIG: Record<string, { color: string; icon: string }> = {
  function: { color: '#3b82f6', icon: 'ƒ' },
  string: { color: '#f59e0b', icon: '"' },
  import: { color: '#8b5cf6', icon: '↓' },
  section: { color: '#6366f1', icon: '§' },
  header: { color: '#06b6d4', icon: 'H' },
  behavior: { color: '#f97316', icon: '⚡' },
  vulnerability: { color: '#ef4444', icon: '⚠' },
  flag: { color: '#22c55e', icon: '🚩' },
  other: { color: '#64748b', icon: '•' },
};

export const GraphPanel: React.FC<GraphPanelProps> = ({ sessionId, isActive }) => {
  const [nodes, setNodes] = useState<KGNode[]>([]);
  const [expandedTypes, setExpandedTypes] = useState<Set<string>>(new Set());
  const [newNodeIds, setNewNodeIds] = useState<Set<string>>(new Set());

  const fetchGraph = useCallback(async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API}/sessions/${sessionId}/graph`);
      if (!res.ok) return;
      const data = await res.json();
      const incoming: KGNode[] = data.nodes || [];

      setNodes(prev => {
        // Detect new nodes
        const prevIds = new Set(prev.map(n => n.id));
        const justAdded = incoming.filter(n => !prevIds.has(n.id)).map(n => n.id);
        if (justAdded.length > 0) {
          setNewNodeIds(new Set(justAdded));
          // Clear "new" highlight after 5s
          setTimeout(() => setNewNodeIds(new Set()), 5000);
        }
        return incoming;
      });
    } catch {
      // Silently handle network errors
    }
  }, [sessionId]);

  // Poll every 3s while the session is active
  useEffect(() => {
    if (!sessionId) return;
    fetchGraph();
    if (isActive) {
      const interval = setInterval(fetchGraph, 3000);
      return () => clearInterval(interval);
    }
  }, [sessionId, isActive, fetchGraph]);

  // Group nodes by type
  const groups = nodes.reduce<Record<string, KGNode[]>>((acc, node) => {
    const t = node.node_type || 'other';
    (acc[t] = acc[t] || []).push(node);
    return acc;
  }, {});

  const toggleType = (type: string) => {
    setExpandedTypes(prev => {
      const next = new Set(prev);
      next.has(type) ? next.delete(type) : next.add(type);
      return next;
    });
  };

  return (
    <div className="glass-panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div className="panel-header">
        <Database size={16} color="var(--success)" />
        <span className="panel-title">Knowledge Graph</span>
        <span className="kg-count">{nodes.length}</span>
      </div>

      {/* Content */}
      <div className="kg-content">
        {nodes.length === 0 ? (
          <div className="kg-empty">
            <Database size={24} style={{ opacity: 0.3 }} />
            <span>No findings yet</span>
            <span className="kg-empty-hint">Findings will appear here as agents analyze the binary.</span>
          </div>
        ) : (
          Object.entries(groups)
            .sort(([, a], [, b]) => b.length - a.length)
            .map(([type, typeNodes]) => {
              const config = TYPE_CONFIG[type] || TYPE_CONFIG.other;
              const isExpanded = expandedTypes.has(type);

              return (
                <div key={type} className="kg-group">
                  <button className="kg-group-header" onClick={() => toggleType(type)}>
                    {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <span className="kg-type-badge" style={{ background: config.color + '22', color: config.color, border: `1px solid ${config.color}44` }}>
                      {config.icon} {type}
                    </span>
                    <span className="kg-type-count">{typeNodes.length}</span>
                  </button>

                  {isExpanded && (
                    <div className="kg-node-list">
                      {typeNodes.map(node => (
                        <div
                          key={node.id}
                          className={`kg-node ${newNodeIds.has(node.id) ? 'kg-node-new' : ''}`}
                          style={{ borderLeftColor: config.color }}
                        >
                          <div className="kg-node-header">
                            {node.name && <span className="kg-node-name">{node.name}</span>}
                            {node.address && <code className="kg-node-addr">{node.address}</code>}
                          </div>
                          <div className="kg-node-desc">
                            {node.data?.description || '—'}
                          </div>
                          <div className="kg-node-meta">
                            <span>{node.created_by_agent}</span>
                            {node.data?.confidence && (
                              <span className={`kg-confidence kg-confidence-${node.data.confidence}`}>
                                {node.data.confidence}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })
        )}
      </div>
    </div>
  );
};

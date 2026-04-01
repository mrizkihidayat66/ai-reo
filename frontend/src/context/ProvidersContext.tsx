import React, { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';

const API = 'http://localhost:9000';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProviderConfig {
  /** Client-side generated UUID (mirrors backend id) */
  id: string;
  display_name: string;
  provider_type: string;
  api_key: string;
  base_url: string;
  models: string[];
  selected_model: string;
  enabled: boolean;
  /** Set to true after a successful test ping */
  tested: boolean;
}

export interface TestResult {
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
}

interface ProvidersCtx {
  providers: ProviderConfig[];
  addProvider: (cfg: Omit<ProviderConfig, 'id' | 'tested'>) => Promise<ProviderConfig>;
  updateProvider: (id: string, updates: Partial<ProviderConfig>) => Promise<void>;
  removeProvider: (id: string) => Promise<void>;
  testProvider: (id: string) => Promise<TestResult>;
  hasReadyProvider: boolean;
}

const ProvidersContext = createContext<ProvidersCtx | undefined>(undefined);
const LS_KEY = 'ai_reo_providers';

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export const ProvidersProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [providers, setProviders] = useState<ProviderConfig[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(LS_KEY) ?? '[]');
    } catch {
      return [];
    }
  });

  // Persist to localStorage on every change
  useEffect(() => {
    localStorage.setItem(LS_KEY, JSON.stringify(providers));
  }, [providers]);

  // Sync all stored providers to backend on mount (backend restarts lose in-memory state)
  useEffect(() => {
    providers.forEach(async (p) => {
      try {
        await fetch(`${API}/providers/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: p.id,
            display_name: p.display_name,
            provider_type: p.provider_type,
            api_key: p.api_key || null,
            base_url: p.base_url || null,
            models: p.models,
            selected_model: p.selected_model,
            enabled: p.enabled,
          }),
        });
      } catch { /* backend may be unavailable, ok */ }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addProvider = async (cfg: Omit<ProviderConfig, 'id' | 'tested'>): Promise<ProviderConfig> => {
    const res = await fetch(`${API}/providers/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: cfg.display_name,
        provider_type: cfg.provider_type,
        api_key: cfg.api_key || null,
        base_url: cfg.base_url || null,
        models: cfg.models,
        selected_model: cfg.selected_model,
        enabled: cfg.enabled,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to create provider');

    // The backend server assigns its own id — store that as our canonical id
    const full: ProviderConfig = { ...cfg, id: data.id, tested: data.tested };
    setProviders(prev => [...prev, full]);
    return full;
  };

  const updateProvider = async (id: string, updates: Partial<ProviderConfig>): Promise<void> => {
    await fetch(`${API}/providers/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    setProviders(prev =>
      prev.map(p => p.id === id ? { ...p, ...updates } : p)
    );
  };

  const removeProvider = async (id: string): Promise<void> => {
    await fetch(`${API}/providers/${id}`, { method: 'DELETE' });
    setProviders(prev => prev.filter(p => p.id !== id));
  };

  const testProvider = async (id: string): Promise<TestResult> => {
    const runTest = async (): Promise<TestResult> => {
      const res = await fetch(`${API}/providers/${id}/test`, { method: 'POST' });
      return await res.json();
    };

    let result: TestResult = await runTest();
    if (!result.ok && result.error?.includes('not found')) {
      const provider = providers.find(p => p.id === id);
      if (provider) {
        await fetch(`${API}/providers/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: provider.id,
            display_name: provider.display_name,
            provider_type: provider.provider_type,
            api_key: provider.api_key || null,
            base_url: provider.base_url || null,
            models: provider.models,
            selected_model: provider.selected_model,
            enabled: provider.enabled,
          }),
        });
        result = await runTest();
      }
    }

    if (result.ok) {
      setProviders(prev => prev.map(p => p.id === id ? { ...p, tested: true } : p));
    }
    return result;
  };

  const hasReadyProvider = providers.some(p => p.enabled && p.tested);

  return (
    <ProvidersContext.Provider value={{ providers, addProvider, updateProvider, removeProvider, testProvider, hasReadyProvider }}>
      {children}
    </ProvidersContext.Provider>
  );
};

export const useProviders = () => {
  const ctx = useContext(ProvidersContext);
  if (!ctx) throw new Error('useProviders must be inside ProvidersProvider');
  return ctx;
};

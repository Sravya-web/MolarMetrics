import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { DatasetMeta, SessionState } from "../api/types";

interface SessionValue {
  state: SessionState | null;
  loading: boolean;
  error: string | null;
  active: DatasetMeta | null;
  /** A short message to announce on the next screen (e.g. after an import). */
  notice: string | null;
  setNotice: (notice: string | null) => void;
  refresh: () => Promise<SessionState | null>;
  activate: (datasetId: string) => Promise<void>;
  activateSample: () => Promise<void>;
  remove: (datasetId: string) => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await api.session();
      setState(next);
      setError(null);
      return next;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activate = useCallback(async (datasetId: string) => {
    setState(await api.activate(datasetId));
  }, []);

  const activateSample = useCallback(async () => {
    await api.activateSample();
    await refresh();
  }, [refresh]);

  const remove = useCallback(async (datasetId: string) => {
    setState(await api.removeDataset(datasetId));
  }, []);

  const value = useMemo<SessionValue>(() => {
    const active = state?.datasets.find((d) => d.id === state.active_dataset_id) ?? null;
    return { state, loading, error, active, notice, setNotice, refresh, activate, activateSample, remove };
  }, [state, loading, error, notice, refresh, activate, activateSample, remove]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession outside SessionProvider");
  return value;
}

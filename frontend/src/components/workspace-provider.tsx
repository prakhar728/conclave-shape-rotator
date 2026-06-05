/**
 * Workspace selection context.
 *
 * Fetches the user's workspaces once, restores the last selection from
 * localStorage (validated against the fetched list — a stale id falls
 * back to the first workspace), and exposes a setter + create helper.
 *
 * Pages read `workspace` from here instead of `me.workspace`, so
 * switching re-keys their fetch effects (workspace.id is already a
 * dependency in every page's useEffect).
 */
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { workspaces as workspacesApi, type Workspace } from "@/lib/api";

const STORAGE_KEY = "conclave.workspace_id";

type WorkspaceContextValue = {
  /** All workspaces the user belongs to (null while loading). */
  workspaces: Workspace[] | null;
  /** The selected workspace (null while loading or if the user has none). */
  workspace: Workspace | null;
  selectWorkspace: (id: string) => void;
  createWorkspace: (name: string) => Promise<Workspace>;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [list, setList] = useState<Workspace[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    workspacesApi
      .list()
      .then((r) => {
        if (cancelled) return;
        setList(r.workspaces);
        const stored =
          typeof window !== "undefined"
            ? window.localStorage.getItem(STORAGE_KEY)
            : null;
        const valid = r.workspaces.find((w) => w.id === stored);
        setSelectedId(valid?.id ?? r.workspaces[0]?.id ?? null);
      })
      .catch(() => {
        // Auth failures are handled by the pages' own auth.me() flows;
        // the provider just stays empty.
        if (!cancelled) setList([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectWorkspace = useCallback((id: string) => {
    setSelectedId(id);
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      // Private mode / quota — selection still works for the session.
    }
  }, []);

  const createWorkspace = useCallback(
    async (name: string) => {
      const r = await workspacesApi.create(name);
      setList((prev) => [...(prev ?? []), r.workspace]);
      selectWorkspace(r.workspace.id);
      return r.workspace;
    },
    [selectWorkspace],
  );

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces: list,
      workspace: list?.find((w) => w.id === selectedId) ?? null,
      selectWorkspace,
      createWorkspace,
    }),
    [list, selectedId, selectWorkspace, createWorkspace],
  );

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) {
    throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  }
  return ctx;
}

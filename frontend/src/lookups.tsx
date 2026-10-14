import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Client, Domain, Lookup, Project } from "./types";

interface Lookups {
  families: Lookup[];
  domains: Domain[];
  taskTypes: Lookup[];
  clients: Client[];
  projects: Project[];
  reload: () => Promise<void>;
}

const LookupsContext = createContext<Lookups | null>(null);

/** רשימות שכל העמודים צריכים (לבחירה בטפסים ולהצגת שמות) */
export function LookupsProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Omit<Lookups, "reload">>({
    families: [],
    domains: [],
    taskTypes: [],
    clients: [],
    projects: [],
  });

  const reload = useCallback(async () => {
    const [families, domains, taskTypes, clients, projects] = await Promise.all([
      api<Lookup[]>("/client-families"),
      api<Domain[]>("/domains"),
      api<Lookup[]>("/task-types"),
      api<Client[]>("/clients"),
      api<Project[]>("/projects"),
    ]);
    setState({ families, domains, taskTypes, clients, projects });
  }, []);

  useEffect(() => {
    reload().catch(() => undefined);
  }, [reload]);

  return <LookupsContext.Provider value={{ ...state, reload }}>{children}</LookupsContext.Provider>;
}

export function useLookups(): Lookups {
  const ctx = useContext(LookupsContext);
  if (!ctx) throw new Error("useLookups מחוץ ל-LookupsProvider");
  return ctx;
}

export function nameOf(items: { id: number; name: string }[], id: number | null): string {
  if (id === null) return "";
  return items.find((i) => i.id === id)?.name ?? "";
}

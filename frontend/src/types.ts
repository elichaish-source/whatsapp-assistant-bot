export interface Lookup {
  id: number;
  name: string;
  sort_order: number;
}

export interface Domain extends Lookup {
  requires_client: boolean;
}

export interface Client {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  tax_id: string | null;
  address: string | null;
  notes: string | null;
  is_active: boolean;
  families: Lookup[];
  open_tasks: number;
}

export interface Project {
  id: number;
  name: string;
  domain_id: number;
  client_id: number | null;
  description: string | null;
  due_date: string | null;
  status: "active" | "done";
  open_tasks: number;
}

export type Priority = "low" | "normal" | "high";

export interface Task {
  id: number;
  title: string;
  status: "open" | "done";
  done_at: string | null;
  domain_id: number;
  task_type_id: number | null;
  client_id: number | null;
  project_id: number | null;
  due_date: string | null;
  reminder_at: string | null;
  priority: Priority;
  notes: string | null;
}

export const PRIORITY_LABELS: Record<Priority, string> = {
  high: "גבוהה",
  normal: "רגילה",
  low: "נמוכה",
};

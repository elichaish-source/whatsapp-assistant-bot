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

export type Priority = "today" | "week" | "later";

export interface Task {
  id: number;
  title: string;
  status: "open" | "done";
  done_at: string | null;
  domain_id: number | null;
  task_type_id: number | null;
  client_id: number | null;
  project_id: number | null;
  due_date: string | null;
  reminder_at: string | null;
  priority: Priority;
  notes: string | null;
}

export const PRIORITY_LABELS: Record<Priority, string> = {
  today: "היום",
  week: "השבוע",
  later: "בהמשך",
};

export interface MemoryFact {
  id: number;
  dimension: number;
  content: string;
  client_id: number | null;
  project_id: number | null;
  source: "bot" | "dashboard";
  created_at: string;
  updated_at: string;
}

export interface MemoryDimension {
  id: number;
  name: string;
  // האם עובדות בממד הזה נשלחות לבוט בשלב הנוכחי
  in_prompt: boolean;
}

export type RepeatUnit = "week" | "month" | "year";

export interface Recurrence {
  id: number;
  title: string;
  interval_unit: RepeatUnit;
  interval_count: number;
  start_date: string;
  cycle: number;
  lead_days: number;
  domain_id: number | null;
  task_type_id: number | null;
  client_id: number | null;
  project_id: number | null;
  priority: Priority;
  notes: string | null;
  active: boolean;
  from_bot: boolean;
  // מחושבים בשרת: התאריך הבא, תיאור התדירות, והמשימה הפתוחה של המחזור הנוכחי
  next_due: string | null;
  every: string;
  open_task_id: number | null;
}

export const REPEAT_LABELS: Record<RepeatUnit, string> = {
  week: "שבועות",
  month: "חודשים",
  year: "שנים",
};

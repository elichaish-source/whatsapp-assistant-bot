import { useCallback, useEffect, useState } from "react";
import { api, query } from "../api";
import { formatDate, formatDateTime, isOverdue } from "../format";
import { nameOf, useLookups } from "../lookups";
import { PRIORITY_LABELS, type Priority, type Task } from "../types";
import Modal from "./Modal";
import TaskForm, { type TaskDefaults } from "./TaskForm";

type Filters = {
  status: string;
  domain_id: string;
  client_id: string;
  project_id: string;
  task_type_id: string;
  priority: string;
  q: string;
};

/** רשימת משימות עם סינון, הוספה ועריכה. `fixed` נועל סינון (למשל בעמוד של לקוח). */
export default function TaskList({ fixed = {}, onChange }: { fixed?: TaskDefaults; onChange?: () => void }) {
  const { domains, taskTypes, clients, projects, reload } = useLookups();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [filters, setFilters] = useState<Filters>({
    status: "open",
    domain_id: "",
    client_id: "",
    project_id: "",
    task_type_id: "",
    priority: "",
    q: "",
  });
  const [editing, setEditing] = useState<Task | "new" | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setTasks(await api<Task[]>(`/tasks${query({ ...filters, ...fixed })}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [filters, fixed.client_id, fixed.project_id, fixed.domain_id]);

  useEffect(() => {
    load();
  }, [load]);

  const changed = () => {
    load();
    reload();
    onChange?.();
  };

  const toggle = async (task: Task) => {
    await api(`/tasks/${task.id}/status`, { method: "PATCH", body: { status: task.status === "open" ? "done" : "open" } });
    changed();
  };

  const remove = async (task: Task) => {
    if (!confirm(`למחוק את המשימה "${task.title}"?`)) return;
    await api(`/tasks/${task.id}`, { method: "DELETE" });
    setEditing(null);
    changed();
  };

  const setFilter = (key: keyof Filters, value: string) => setFilters((f) => ({ ...f, [key]: value }));

  const select = (key: keyof Filters, label: string, items: { id: number; name: string }[]) => (
    <select value={filters[key]} onChange={(e) => setFilter(key, e.target.value)} aria-label={label}>
      <option value="">{label}: הכול</option>
      {items.map((i) => (
        <option key={i.id} value={i.id}>
          {i.name}
        </option>
      ))}
    </select>
  );

  return (
    <div>
      <div className="toolbar">
        <button className="primary" onClick={() => setEditing("new")}>
          + משימה חדשה
        </button>
        <input placeholder="חיפוש…" value={filters.q} onChange={(e) => setFilter("q", e.target.value)} />
        <select value={filters.status} onChange={(e) => setFilter("status", e.target.value)} aria-label="סטטוס">
          <option value="open">פתוחות</option>
          <option value="done">בוצעו</option>
          <option value="">הכול</option>
        </select>
        {fixed.domain_id === undefined && select("domain_id", "תחום", domains)}
        {fixed.client_id === undefined && select("client_id", "לקוח", clients)}
        {fixed.project_id === undefined && select("project_id", "פרויקט", projects)}
        {select("task_type_id", "סוג", taskTypes)}
        <select value={filters.priority} onChange={(e) => setFilter("priority", e.target.value)} aria-label="עדיפות">
          <option value="">עדיפות: הכול</option>
          {(Object.keys(PRIORITY_LABELS) as Priority[]).map((p) => (
            <option key={p} value={p}>
              {PRIORITY_LABELS[p]}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="error">{error}</p>}
      {tasks.length === 0 ? (
        <div className="card muted">אין משימות להצגה.</div>
      ) : (
        <ul className="task-list">
          {tasks.map((t) => (
            <li key={t.id} className={`card task ${t.status}`}>
              <input type="checkbox" checked={t.status === "done"} onChange={() => toggle(t)} aria-label="בוצעה" />
              <div className="task-body" onClick={() => setEditing(t)}>
                <div className="task-title">
                  {t.priority === "high" && <span className="pill high">!</span>}
                  {t.title}
                </div>
                <div className="task-meta">
                  <span className="pill">{nameOf(domains, t.domain_id)}</span>
                  {t.task_type_id && <span>{nameOf(taskTypes, t.task_type_id)}</span>}
                  {t.client_id && fixed.client_id === undefined && <span>👤 {nameOf(clients, t.client_id)}</span>}
                  {t.project_id && <span>📁 {nameOf(projects, t.project_id)}</span>}
                  {t.due_date && (
                    <span className={t.status === "open" && isOverdue(t.due_date) ? "overdue" : ""}>
                      📅 {formatDate(t.due_date)}
                    </span>
                  )}
                  {t.reminder_at && <span>⏰ {formatDateTime(t.reminder_at)}</span>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <Modal title={editing === "new" ? "משימה חדשה" : "עריכת משימה"} onClose={() => setEditing(null)}>
          <TaskForm
            task={editing === "new" ? undefined : editing}
            defaults={fixed}
            onSaved={() => {
              setEditing(null);
              changed();
            }}
            onCancel={() => setEditing(null)}
          />
          {editing !== "new" && (
            <button className="danger link-btn" onClick={() => remove(editing)}>
              מחיקת משימה
            </button>
          )}
        </Modal>
      )}
    </div>
  );
}

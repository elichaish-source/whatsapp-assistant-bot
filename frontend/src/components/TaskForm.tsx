import { useState, type FormEvent } from "react";
import { api } from "../api";
import { fromLocalInput, toLocalInput } from "../format";
import { useLookups } from "../lookups";
import { PRIORITY_LABELS, type Priority, type Task } from "../types";

export interface TaskDefaults {
  client_id?: number | null;
  project_id?: number | null;
  domain_id?: number | null;
}

const toId = (v: string) => (v ? Number(v) : null);

export default function TaskForm({
  task,
  defaults,
  onSaved,
  onCancel,
}: {
  task?: Task;
  defaults?: TaskDefaults;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { domains, taskTypes, clients, projects } = useLookups();
  // משימה חדשה בתוך פרויקט מקבלת את התחום והלקוח שלו
  const defaultProject = projects.find((p) => p.id === defaults?.project_id);
  const [form, setForm] = useState({
    title: task?.title ?? "",
    status: task?.status ?? "open",
    domain_id: task?.domain_id ?? defaults?.domain_id ?? defaultProject?.domain_id ?? null,
    task_type_id: task?.task_type_id ?? null,
    client_id: task?.client_id ?? defaults?.client_id ?? defaultProject?.client_id ?? null,
    project_id: task?.project_id ?? defaults?.project_id ?? null,
    due_date: task?.due_date ?? "",
    reminder_at: toLocalInput(task?.reminder_at ?? null),
    priority: (task?.priority ?? "normal") as Priority,
    notes: task?.notes ?? "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((f) => ({ ...f, [key]: value }));

  const project = projects.find((p) => p.id === form.project_id);
  const domain = domains.find((d) => d.id === form.domain_id);
  const clientLocked = project?.client_id != null;

  const chooseProject = (projectId: number | null) => {
    const p = projects.find((x) => x.id === projectId);
    setForm((f) => {
      const prev = projects.find((x) => x.id === f.project_id);
      // התחום מתעדכן לתחום הפרויקט, אלא אם נבחר ידנית תחום אחר
      const domainFollows = f.domain_id === null || f.domain_id === prev?.domain_id;
      return {
        ...f,
        project_id: projectId,
        domain_id: p && domainFollows ? p.domain_id : f.domain_id,
        client_id: p?.client_id ?? f.client_id,
      };
    });
  };

  const visibleProjects = projects.filter(
    (p) => p.id === form.project_id || (p.status === "active" && (form.client_id === null || p.client_id === null || p.client_id === form.client_id)),
  );

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (domain?.requires_client && form.client_id === null) {
      setError(`בתחום "${domain.name}" חובה לבחור לקוח`);
      return;
    }
    setBusy(true);
    setError("");
    const body = {
      ...form,
      due_date: form.due_date || null,
      reminder_at: fromLocalInput(form.reminder_at),
    };
    try {
      await api(task ? `/tasks/${task.id}` : "/tasks", { method: task ? "PUT" : "POST", body });
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="form-grid">
      <label className="full">
        כותרת *
        <input value={form.title} onChange={(e) => set("title", e.target.value)} required autoFocus />
      </label>
      <label>
        פרויקט
        <select value={form.project_id ?? ""} onChange={(e) => chooseProject(toId(e.target.value))}>
          <option value="">ללא</option>
          {visibleProjects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        תחום *
        <select value={form.domain_id ?? ""} onChange={(e) => set("domain_id", toId(e.target.value))} required>
          <option value="">בחר…</option>
          {domains.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        לקוח {domain?.requires_client && "*"}
        <select
          value={form.client_id ?? ""}
          onChange={(e) => set("client_id", toId(e.target.value))}
          disabled={clientLocked}
        >
          <option value="">ללא</option>
          {clients
            .filter((c) => c.is_active || c.id === form.client_id)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
        </select>
      </label>
      <label>
        סוג
        <select value={form.task_type_id ?? ""} onChange={(e) => set("task_type_id", toId(e.target.value))}>
          <option value="">ללא</option>
          {taskTypes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        תאריך יעד
        <input type="date" value={form.due_date} onChange={(e) => set("due_date", e.target.value)} />
      </label>
      <label>
        תזכורת
        <input type="datetime-local" value={form.reminder_at} onChange={(e) => set("reminder_at", e.target.value)} />
      </label>
      <label>
        עדיפות
        <select value={form.priority} onChange={(e) => set("priority", e.target.value as Priority)}>
          {(Object.keys(PRIORITY_LABELS) as Priority[]).map((p) => (
            <option key={p} value={p}>
              {PRIORITY_LABELS[p]}
            </option>
          ))}
        </select>
      </label>
      {task && (
        <label>
          סטטוס
          <select value={form.status} onChange={(e) => set("status", e.target.value as "open" | "done")}>
            <option value="open">פתוחה</option>
            <option value="done">בוצעה</option>
          </select>
        </label>
      )}
      <label className="full">
        הערות
        <textarea rows={3} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
      </label>
      {error && <p className="error full">{error}</p>}
      <div className="actions full">
        <button className="primary" disabled={busy}>
          שמירה
        </button>
        <button type="button" onClick={onCancel}>
          ביטול
        </button>
      </div>
    </form>
  );
}

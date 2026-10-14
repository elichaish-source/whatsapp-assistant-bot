import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useLookups } from "../lookups";
import type { Project } from "../types";

const toId = (v: string) => (v ? Number(v) : null);

export default function ProjectForm({
  project,
  defaultClientId,
  onSaved,
  onCancel,
}: {
  project?: Project;
  defaultClientId?: number | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { domains, clients } = useLookups();
  const [form, setForm] = useState({
    name: project?.name ?? "",
    domain_id: project?.domain_id ?? null,
    client_id: project?.client_id ?? defaultClientId ?? null,
    description: project?.description ?? "",
    due_date: project?.due_date ?? "",
    status: project?.status ?? "active",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(project ? `/projects/${project.id}` : "/projects", {
        method: project ? "PUT" : "POST",
        body: { ...form, due_date: form.due_date || null },
      });
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
        שם *
        <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required autoFocus />
      </label>
      <label>
        תחום *
        <select value={form.domain_id ?? ""} onChange={(e) => setForm({ ...form, domain_id: toId(e.target.value) })} required>
          <option value="">בחר…</option>
          {domains.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        לקוח
        <select value={form.client_id ?? ""} onChange={(e) => setForm({ ...form, client_id: toId(e.target.value) })}>
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
        תאריך יעד
        <input type="date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
      </label>
      <label>
        סטטוס
        <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as "active" | "done" })}>
          <option value="active">פעיל</option>
          <option value="done">הסתיים</option>
        </select>
      </label>
      <label className="full">
        תיאור
        <textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
      </label>
      {project?.client_id != null && form.client_id !== project.client_id && form.client_id !== null && (
        <p className="muted full">כל המשימות בפרויקט יעברו ללקוח החדש.</p>
      )}
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

import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useLookups } from "../lookups";
import { PRIORITY_LABELS, REPEAT_LABELS, type Priority, type Recurrence, type RepeatUnit } from "../types";

const toId = (v: string) => (v ? Number(v) : null);

export default function RecurrenceForm({
  recurrence,
  onSaved,
  onCancel,
}: {
  recurrence?: Recurrence;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { domains, taskTypes, clients, projects } = useLookups();
  const [form, setForm] = useState({
    title: recurrence?.title ?? "",
    interval_unit: (recurrence?.interval_unit ?? "month") as RepeatUnit,
    interval_count: recurrence?.interval_count ?? 1,
    start_date: recurrence?.start_date ?? "",
    lead_days: recurrence?.lead_days ?? 0,
    domain_id: recurrence?.domain_id ?? null,
    task_type_id: recurrence?.task_type_id ?? null,
    client_id: recurrence?.client_id ?? null,
    project_id: recurrence?.project_id ?? null,
    priority: (recurrence?.priority ?? "week") as Priority,
    notes: recurrence?.notes ?? "",
    active: recurrence?.active ?? true,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const domain = domains.find((d) => d.id === form.domain_id);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (domain?.requires_client && form.client_id === null) {
      setError(`בתחום "${domain.name}" חובה לבחור לקוח`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(recurrence ? `/recurrences/${recurrence.id}` : "/recurrences", {
        method: recurrence ? "PUT" : "POST",
        body: form,
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
        מה צריך לעשות *
        <input
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder="דוח מע״מ"
          required
          autoFocus
        />
      </label>
      <label>
        כל כמה *
        <input
          type="number"
          min={1}
          max={60}
          value={form.interval_count}
          onChange={(e) => set("interval_count", Number(e.target.value))}
          required
        />
      </label>
      <label>
        יחידה *
        <select
          value={form.interval_unit}
          onChange={(e) => set("interval_unit", e.target.value as RepeatUnit)}
        >
          {(Object.keys(REPEAT_LABELS) as RepeatUnit[]).map((unit) => (
            <option key={unit} value={unit}>
              {REPEAT_LABELS[unit]}
            </option>
          ))}
        </select>
      </label>
      <label>
        הפעם הראשונה *
        <input
          type="date"
          value={form.start_date}
          onChange={(e) => set("start_date", e.target.value)}
          required
        />
      </label>
      <label>
        להזכיר כמה ימים לפני
        <input
          type="number"
          min={0}
          max={365}
          value={form.lead_days}
          onChange={(e) => set("lead_days", Number(e.target.value))}
        />
      </label>
      <label>
        תחום
        <select value={form.domain_id ?? ""} onChange={(e) => set("domain_id", toId(e.target.value))}>
          <option value="">ללא תחום</option>
          {domains.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        לקוח {domain?.requires_client && "*"}
        <select value={form.client_id ?? ""} onChange={(e) => set("client_id", toId(e.target.value))}>
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
        פרויקט
        <select value={form.project_id ?? ""} onChange={(e) => set("project_id", toId(e.target.value))}>
          <option value="">ללא</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        סוג
        <select
          value={form.task_type_id ?? ""}
          onChange={(e) => set("task_type_id", toId(e.target.value))}
        >
          <option value="">ללא</option>
          {taskTypes.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
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
      <label>
        פעילה
        <select value={form.active ? "1" : "0"} onChange={(e) => set("active", e.target.value === "1")}>
          <option value="1">כן — ממשיכה לייצר משימות</option>
          <option value="0">לא — מושהית</option>
        </select>
      </label>
      <label className="full">
        הערות
        <textarea rows={2} value={form.notes} onChange={(e) => set("notes", e.target.value)} />
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

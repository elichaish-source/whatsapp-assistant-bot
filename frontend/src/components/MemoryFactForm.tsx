import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useLookups } from "../lookups";
import type { MemoryDimension, MemoryFact } from "../types";

const toId = (v: string) => (v ? Number(v) : null);

export default function MemoryFactForm({
  fact,
  dimensions,
  onSaved,
  onCancel,
}: {
  fact?: MemoryFact;
  dimensions: MemoryDimension[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { clients, projects } = useLookups();
  const [form, setForm] = useState({
    dimension: fact?.dimension ?? 1,
    content: fact?.content ?? "",
    client_id: fact?.client_id ?? null,
    project_id: fact?.project_id ?? null,
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(fact ? `/memory/facts/${fact.id}` : "/memory/facts", {
        method: fact ? "PUT" : "POST",
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
        העובדה *
        <textarea
          rows={2}
          value={form.content}
          onChange={(e) => set("content", e.target.value)}
          placeholder="משפט אחד, כפי שהוא יישלח לבוט"
          required
          autoFocus
        />
      </label>
      <label>
        סוג המידע
        <select value={form.dimension} onChange={(e) => set("dimension", Number(e.target.value))}>
          {dimensions.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
              {d.in_prompt ? "" : " (נשמר לעתיד)"}
            </option>
          ))}
        </select>
      </label>
      <label>
        על לקוח
        <select value={form.client_id ?? ""} onChange={(e) => set("client_id", toId(e.target.value))}>
          <option value="">עליי</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        על פרויקט
        <select value={form.project_id ?? ""} onChange={(e) => set("project_id", toId(e.target.value))}>
          <option value="">ללא</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
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

import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useLookups } from "../lookups";
import type { Client } from "../types";

export default function ClientForm({
  client,
  onSaved,
  onCancel,
}: {
  client?: Client;
  onSaved: (client: Client) => void;
  onCancel: () => void;
}) {
  const { families } = useLookups();
  const [form, setForm] = useState({
    name: client?.name ?? "",
    phone: client?.phone ?? "",
    email: client?.email ?? "",
    notes: client?.notes ?? "",
    is_active: client?.is_active ?? true,
    family_ids: client?.families.map((f) => f.id) ?? [],
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const toggleFamily = (id: number) =>
    setForm((f) => ({
      ...f,
      family_ids: f.family_ids.includes(id) ? f.family_ids.filter((x) => x !== id) : [...f.family_ids, id],
    }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const saved = await api<Client>(client ? `/clients/${client.id}` : "/clients", {
        method: client ? "PUT" : "POST",
        body: form,
      });
      onSaved(saved);
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
        טלפון וואטסאפ
        <input type="tel" dir="ltr" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
      </label>
      <label>
        מייל
        <input type="email" dir="ltr" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </label>
      <fieldset className="full">
        <legend>משפחות לקוחות</legend>
        {families.map((f) => (
          <label key={f.id} className="check">
            <input type="checkbox" checked={form.family_ids.includes(f.id)} onChange={() => toggleFamily(f.id)} />
            {f.name}
          </label>
        ))}
      </fieldset>
      <label className="check full">
        <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
        לקוח פעיל
      </label>
      <label className="full">
        הערות
        <textarea rows={3} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
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

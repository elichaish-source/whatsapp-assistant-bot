import { useState } from "react";
import { api } from "../api";
import { useLookups } from "../lookups";
import type { Domain, Lookup } from "../types";

interface ListConfig {
  title: string;
  path: string;
  items: (Lookup | Domain)[];
  withRequiresClient?: boolean;
}

function EditableList({ title, path, items, withRequiresClient }: ListConfig) {
  const { reload } = useLookups();
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");

  const run = async (fn: () => Promise<unknown>) => {
    setError("");
    try {
      await fn();
      await reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const save = (item: Lookup | Domain, changes: Partial<Domain>) =>
    run(() => api(`${path}/${item.id}`, { method: "PUT", body: { ...item, ...changes } }));

  const add = () => {
    const name = newName.trim();
    if (!name) return;
    const sort_order = Math.max(0, ...items.map((i) => i.sort_order)) + 1;
    run(async () => {
      await api(path, { method: "POST", body: { name, sort_order } });
      setNewName("");
    });
  };

  const rename = (item: Lookup) => {
    const name = prompt("שם חדש:", item.name)?.trim();
    if (name && name !== item.name) save(item, { name });
  };

  const remove = (item: Lookup) => {
    if (confirm(`למחוק את "${item.name}"?`)) run(() => api(`${path}/${item.id}`, { method: "DELETE" }));
  };

  return (
    <section className="card">
      <h2>{title}</h2>
      <ul className="lookup-list">
        {items.map((item) => (
          <li key={item.id}>
            <span className="grow">{item.name}</span>
            {withRequiresClient && (
              <label className="check small">
                <input
                  type="checkbox"
                  checked={(item as Domain).requires_client}
                  onChange={(e) => save(item, { requires_client: e.target.checked })}
                />
                מחייב לקוח
              </label>
            )}
            <button className="link-btn" onClick={() => rename(item)}>
              שינוי שם
            </button>
            <button className="link-btn danger" onClick={() => remove(item)}>
              מחיקה
            </button>
          </li>
        ))}
      </ul>
      <div className="toolbar">
        <input placeholder="שם חדש…" value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
        <button onClick={add}>הוספה</button>
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

export default function Settings() {
  const { families, domains, taskTypes } = useLookups();
  return (
    <div>
      <h1>הגדרות</h1>
      <div className="settings-grid">
        <EditableList title="משפחות לקוחות" path="/client-families" items={families} />
        <EditableList title="תחומים" path="/domains" items={domains} withRequiresClient />
        <EditableList title="סוגי משימה" path="/task-types" items={taskTypes} />
      </div>
    </div>
  );
}

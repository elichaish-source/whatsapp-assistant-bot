import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, query } from "../api";
import ClientForm from "../components/ClientForm";
import Modal from "../components/Modal";
import { useLookups } from "../lookups";
import type { Client } from "../types";

export default function Clients() {
  const { families, reload } = useLookups();
  const navigate = useNavigate();
  const [clients, setClients] = useState<Client[]>([]);
  const [familyId, setFamilyId] = useState("");
  const [active, setActive] = useState("true");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    api<Client[]>(`/clients${query({ family_id: familyId, is_active: active, q })}`).then(setClients);
  }, [familyId, active, q]);

  return (
    <div>
      <h1>לקוחות</h1>
      <div className="toolbar">
        <button className="primary" onClick={() => setAdding(true)}>
          + לקוח חדש
        </button>
        <input placeholder="חיפוש…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={familyId} onChange={(e) => setFamilyId(e.target.value)} aria-label="משפחה">
          <option value="">כל המשפחות</option>
          {families.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <select value={active} onChange={(e) => setActive(e.target.value)} aria-label="סטטוס">
          <option value="true">פעילים</option>
          <option value="false">לא פעילים</option>
          <option value="">הכול</option>
        </select>
      </div>

      {clients.length === 0 ? (
        <div className="card muted">אין לקוחות להצגה.</div>
      ) : (
        <div className="grid">
          {clients.map((c) => (
            <div key={c.id} className={`card clickable ${c.is_active ? "" : "inactive"}`} onClick={() => navigate(`/clients/${c.id}`)}>
              <div className="card-title">{c.name}</div>
              <div className="task-meta">
                {c.families.map((f) => (
                  <span key={f.id} className="pill">
                    {f.name}
                  </span>
                ))}
                {!c.is_active && <span className="pill">לא פעיל</span>}
              </div>
              <div className="muted">{c.open_tasks} משימות פתוחות</div>
            </div>
          ))}
        </div>
      )}

      {adding && (
        <Modal title="לקוח חדש" onClose={() => setAdding(false)}>
          <ClientForm
            onSaved={(c) => {
              reload();
              navigate(`/clients/${c.id}`);
            }}
            onCancel={() => setAdding(false)}
          />
        </Modal>
      )}
    </div>
  );
}

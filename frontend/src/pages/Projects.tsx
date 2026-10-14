import { useCallback, useEffect, useMemo, useState } from "react";
import { api, query } from "../api";
import Modal from "../components/Modal";
import ProjectForm from "../components/ProjectForm";
import TaskList from "../components/TaskList";
import { formatDate } from "../format";
import { nameOf, useLookups } from "../lookups";
import type { Project } from "../types";

export default function Projects() {
  const { domains, clients, reload } = useLookups();
  const [projects, setProjects] = useState<Project[]>([]);
  const [status, setStatus] = useState("active");
  const [domainId, setDomainId] = useState("");
  const [clientId, setClientId] = useState("");
  const [editing, setEditing] = useState<Project | "new" | null>(null);
  const [selected, setSelected] = useState<Project | null>(null);
  const fixed = useMemo(() => ({ project_id: selected?.id }), [selected]);

  const load = useCallback(async () => {
    setProjects(await api<Project[]>(`/projects${query({ status, domain_id: domainId, client_id: clientId })}`));
  }, [status, domainId, clientId]);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async (p: Project) => {
    if (!confirm(`למחוק את הפרויקט "${p.name}"?`)) return;
    try {
      await api(`/projects/${p.id}`, { method: "DELETE" });
      setEditing(null);
      load();
      reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  return (
    <div>
      <h1>פרויקטים</h1>
      <div className="toolbar">
        <button className="primary" onClick={() => setEditing("new")}>
          + פרויקט חדש
        </button>
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="סטטוס">
          <option value="active">פעילים</option>
          <option value="done">הסתיימו</option>
          <option value="">הכול</option>
        </select>
        <select value={domainId} onChange={(e) => setDomainId(e.target.value)} aria-label="תחום">
          <option value="">תחום: הכול</option>
          {domains.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <select value={clientId} onChange={(e) => setClientId(e.target.value)} aria-label="לקוח">
          <option value="">לקוח: הכול</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {projects.length === 0 ? (
        <div className="card muted">אין פרויקטים להצגה.</div>
      ) : (
        <div className="grid">
          {projects.map((p) => (
            <div
              key={p.id}
              className={`card clickable ${p.status === "done" ? "inactive" : ""} ${selected?.id === p.id ? "selected" : ""}`}
              onClick={() => setSelected(selected?.id === p.id ? null : p)}
            >
              <div className="page-head">
                <div className="card-title">{p.name}</div>
                <button
                  className="link-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditing(p);
                  }}
                >
                  עריכה
                </button>
              </div>
              <div className="task-meta">
                <span className="pill">{nameOf(domains, p.domain_id)}</span>
                {p.client_id && <span>👤 {nameOf(clients, p.client_id)}</span>}
                {p.status === "done" && <span className="pill">הסתיים</span>}
                {p.due_date && <span>📅 {formatDate(p.due_date)}</span>}
              </div>
              {p.description && <div className="muted clamp">{p.description}</div>}
              <div className="muted">{p.open_tasks} משימות פתוחות</div>
            </div>
          ))}
        </div>
      )}

      {selected && (
        <>
          <h2>משימות בפרויקט: {selected.name}</h2>
          <TaskList fixed={fixed} onChange={load} />
        </>
      )}

      {editing && (
        <Modal title={editing === "new" ? "פרויקט חדש" : "עריכת פרויקט"} onClose={() => setEditing(null)}>
          <ProjectForm
            project={editing === "new" ? undefined : editing}
            onSaved={() => {
              setEditing(null);
              load();
              reload();
            }}
            onCancel={() => setEditing(null)}
          />
          {editing !== "new" && (
            <button className="danger link-btn" onClick={() => remove(editing)}>
              מחיקת פרויקט
            </button>
          )}
        </Modal>
      )}
    </div>
  );
}

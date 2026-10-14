import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, query } from "../api";
import ClientForm from "../components/ClientForm";
import Modal from "../components/Modal";
import ProjectForm from "../components/ProjectForm";
import TaskList from "../components/TaskList";
import { formatDate } from "../format";
import { nameOf, useLookups } from "../lookups";
import type { Client, Project } from "../types";

export default function ClientDetail() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { domains, reload } = useLookups();
  const [client, setClient] = useState<Client | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [editing, setEditing] = useState(false);
  const [projectModal, setProjectModal] = useState<Project | "new" | null>(null);
  const [error, setError] = useState("");
  const fixed = useMemo(() => ({ client_id: id }), [id]);

  const load = useCallback(async () => {
    try {
      const [c, p] = await Promise.all([api<Client>(`/clients/${id}`), api<Project[]>(`/projects${query({ client_id: id })}`)]);
      setClient(c);
      setProjects(p);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async () => {
    if (!client || !confirm(`למחוק את הלקוח "${client.name}"?`)) return;
    try {
      await api(`/clients/${id}`, { method: "DELETE" });
      reload();
      navigate("/clients");
    } catch (e) {
      alert((e as Error).message);
    }
  };

  if (error) return <p className="error">{error}</p>;
  if (!client) return <div className="muted">טוען…</div>;

  return (
    <div>
      <Link to="/clients" className="muted">
        → כל הלקוחות
      </Link>
      <div className="page-head">
        <h1>{client.name}</h1>
        <button onClick={() => setEditing(true)}>עריכה</button>
      </div>

      <div className="card details">
        <div className="task-meta">
          {client.families.map((f) => (
            <span key={f.id} className="pill">
              {f.name}
            </span>
          ))}
          {!client.is_active && <span className="pill">לא פעיל</span>}
        </div>
        {client.phone && (
          <div>
            טלפון: <span dir="ltr">{client.phone}</span>
          </div>
        )}
        {client.email && (
          <div>
            מייל: <span dir="ltr">{client.email}</span>
          </div>
        )}
        {client.notes && <div className="notes">{client.notes}</div>}
      </div>

      <div className="page-head">
        <h2>פרויקטים</h2>
        <button onClick={() => setProjectModal("new")}>+ פרויקט</button>
      </div>
      {projects.length === 0 ? (
        <div className="card muted">אין פרויקטים.</div>
      ) : (
        <div className="grid">
          {projects.map((p) => (
            <div key={p.id} className={`card clickable ${p.status === "done" ? "inactive" : ""}`} onClick={() => setProjectModal(p)}>
              <div className="card-title">{p.name}</div>
              <div className="task-meta">
                <span className="pill">{nameOf(domains, p.domain_id)}</span>
                {p.status === "done" && <span className="pill">הסתיים</span>}
                {p.due_date && <span>📅 {formatDate(p.due_date)}</span>}
              </div>
              <div className="muted">{p.open_tasks} משימות פתוחות</div>
            </div>
          ))}
        </div>
      )}

      <h2>משימות</h2>
      <TaskList fixed={fixed} onChange={load} />

      {editing && (
        <Modal title="עריכת לקוח" onClose={() => setEditing(false)}>
          <ClientForm
            client={client}
            onSaved={() => {
              setEditing(false);
              load();
              reload();
            }}
            onCancel={() => setEditing(false)}
          />
          <button className="danger link-btn" onClick={remove}>
            מחיקת לקוח
          </button>
        </Modal>
      )}
      {projectModal && (
        <Modal title={projectModal === "new" ? "פרויקט חדש" : "עריכת פרויקט"} onClose={() => setProjectModal(null)}>
          <ProjectForm
            project={projectModal === "new" ? undefined : projectModal}
            defaultClientId={id}
            onSaved={() => {
              setProjectModal(null);
              load();
              reload();
            }}
            onCancel={() => setProjectModal(null)}
          />
        </Modal>
      )}
    </div>
  );
}

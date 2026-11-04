import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import Modal from "../components/Modal";
import RecurrenceForm from "../components/RecurrenceForm";
import { formatDate } from "../format";
import { nameOf, useLookups } from "../lookups";
import type { Recurrence } from "../types";

export default function Recurring() {
  const { clients, projects } = useLookups();
  const [items, setItems] = useState<Recurrence[]>([]);
  const [editing, setEditing] = useState<Recurrence | "new" | null>(null);

  const load = useCallback(async () => {
    setItems(await api<Recurrence[]>("/recurrences"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async (rec: Recurrence) => {
    if (!confirm(`למחוק את "${rec.title}"? המשימות שנוצרו ממנה יישארו.`)) return;
    try {
      await api(`/recurrences/${rec.id}`, { method: "DELETE" });
      setEditing(null);
      load();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const subject = (rec: Recurrence) => {
    if (rec.client_id) return `👤 ${nameOf(clients, rec.client_id)}`;
    if (rec.project_id) return `📁 ${nameOf(projects, rec.project_id)}`;
    return null;
  };

  return (
    <div>
      <h1>התחייבויות חוזרות</h1>
      <p className="muted">
        נרשמות פעם אחת, ומייצרות משימה אמיתית בכל מחזור. מחזור אחד פתוח בכל פעם: הבא נוצר רק אחרי
        שסימנת את הנוכחי כבוצע. כל עוד לא סימנת, התזכורת חוזרת כל יום — עד שבעה ימים מהתאריך.
      </p>

      <div className="toolbar">
        <button className="primary" onClick={() => setEditing("new")}>
          + התחייבות חוזרת
        </button>
      </div>

      {items.length === 0 ? (
        <div className="card muted">
          אין עדיין התחייבויות חוזרות. אפשר להוסיף כאן, או לכתוב לבוט "כל חודשיים ב-15 דוח מע״מ".
        </div>
      ) : (
        <div className="grid">
          {items.map((rec) => (
            <div key={rec.id} className={`card ${rec.active ? "" : "muted"}`}>
              <div className="page-head">
                <div>
                  <strong>{rec.title}</strong>
                  {!rec.active && <span className="badge">מושהית</span>}
                </div>
                <button className="link-btn" onClick={() => setEditing(rec)}>
                  עריכה
                </button>
              </div>
              <div className="task-meta">
                <span className="pill">{rec.every}</span>
                {rec.open_task_id ? (
                  <span>המחזור הנוכחי פתוח · הבא {formatDate(rec.next_due)}</span>
                ) : (
                  <span>הפעם הבאה {formatDate(rec.next_due)}</span>
                )}
                {rec.lead_days > 0 && <span>התראה {rec.lead_days} ימים לפני</span>}
                {subject(rec)}
                {rec.priority === "high" && <span>דחוף</span>}
                {rec.from_bot && <span className="pill">מוואטסאפ</span>}
              </div>
              {rec.notes && <div className="muted">{rec.notes}</div>}
            </div>
          ))}
        </div>
      )}

      {editing && (
        <Modal
          title={editing === "new" ? "התחייבות חוזרת" : "עריכת התחייבות"}
          onClose={() => setEditing(null)}
        >
          <RecurrenceForm
            recurrence={editing === "new" ? undefined : editing}
            onSaved={() => {
              setEditing(null);
              load();
            }}
            onCancel={() => setEditing(null)}
          />
          {editing !== "new" && (
            <button className="danger link-btn" onClick={() => remove(editing)}>
              מחיקת ההתחייבות
            </button>
          )}
        </Modal>
      )}
    </div>
  );
}

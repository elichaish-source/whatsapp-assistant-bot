import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import MemoryFactForm from "../components/MemoryFactForm";
import Modal from "../components/Modal";
import { nameOf, useLookups } from "../lookups";
import type { MemoryDimension, MemoryFact } from "../types";

export default function Memory() {
  const { clients, projects } = useLookups();
  const [dimensions, setDimensions] = useState<MemoryDimension[]>([]);
  const [facts, setFacts] = useState<MemoryFact[]>([]);
  const [block, setBlock] = useState("");
  const [showBlock, setShowBlock] = useState(false);
  const [editing, setEditing] = useState<MemoryFact | "new" | null>(null);

  const load = useCallback(async () => {
    const [dims, items, raw] = await Promise.all([
      api<MemoryDimension[]>("/memory/dimensions"),
      api<MemoryFact[]>("/memory/facts"),
      api<{ block: string }>("/memory/block"),
    ]);
    setDimensions(dims);
    setFacts(items);
    setBlock(raw.block);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const remove = async (fact: MemoryFact) => {
    if (!confirm(`למחוק מהזיכרון: "${fact.content}"?`)) return;
    try {
      await api(`/memory/facts/${fact.id}`, { method: "DELETE" });
      setEditing(null);
      load();
    } catch (e) {
      alert((e as Error).message);
    }
  };

  const subject = (fact: MemoryFact) => {
    if (fact.client_id) return `👤 ${nameOf(clients, fact.client_id)}`;
    if (fact.project_id) return `📁 ${nameOf(projects, fact.project_id)}`;
    return null;
  };

  return (
    <div>
      <h1>מה הוא יודע עליי</h1>
      <p className="muted">
        כל מה שכאן נכנס רק בשתי דרכים: אמרת לבוט "תזכור ש…", או הקלדת כאן. הוא לא מסיק שום דבר
        בעצמו. מה שמסומן "נשלח לבוט" מגיע אליו בכל הודעה.
      </p>

      <div className="toolbar">
        <button className="primary" onClick={() => setEditing("new")}>
          + עובדה חדשה
        </button>
        <button className="link-btn" onClick={() => setShowBlock(!showBlock)}>
          {showBlock ? "הסתר" : "מה בדיוק נשלח לבוט"}
        </button>
      </div>

      {showBlock && (
        <div className="card">
          <div className="card-title">הטקסט שהבוט מקבל בכל הודעה</div>
          {block ? <pre className="muted">{block}</pre> : <div className="muted">כרגע כלום.</div>}
        </div>
      )}

      {facts.length === 0 ? (
        <div className="card muted">הזיכרון ריק. אפשר לכתוב לבוט "תזכור ש…" או להוסיף כאן.</div>
      ) : (
        dimensions
          .map((dim) => ({ dim, items: facts.filter((f) => f.dimension === dim.id) }))
          .filter(({ items }) => items.length > 0)
          .map(({ dim, items }) => (
            <section key={dim.id}>
              <h2>
                {dim.name}
                <span className="badge">{dim.in_prompt ? "נשלח לבוט" : "נשמר לעתיד"}</span>
              </h2>
              <div className="grid">
                {items.map((fact) => (
                  <div key={fact.id} className="card">
                    <div className="page-head">
                      <div>{fact.content}</div>
                      <button className="link-btn" onClick={() => setEditing(fact)}>
                        עריכה
                      </button>
                    </div>
                    <div className="task-meta">
                      {subject(fact)}
                      <span className="pill">{fact.source === "bot" ? "מוואטסאפ" : "מהדשבורד"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))
      )}

      {editing && (
        <Modal
          title={editing === "new" ? "עובדה חדשה" : "עריכת עובדה"}
          onClose={() => setEditing(null)}
        >
          <MemoryFactForm
            fact={editing === "new" ? undefined : editing}
            dimensions={dimensions}
            onSaved={() => {
              setEditing(null);
              load();
            }}
            onCancel={() => setEditing(null)}
          />
          {editing !== "new" && (
            <button className="danger link-btn" onClick={() => remove(editing)}>
              מחיקה מהזיכרון
            </button>
          )}
        </Modal>
      )}
    </div>
  );
}

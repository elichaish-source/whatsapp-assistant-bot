import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, query } from "../api";
import MailRow from "../components/MailRow";
import Modal from "../components/Modal";
import TaskForm from "../components/TaskForm";
import { formatWhen } from "../format";
import { linkify } from "../linkify";
import {
  MAIL_SCOPE_LABELS,
  type MailBody,
  type MailItem,
  type MailList,
  type MailScope,
  type TaskDraft,
} from "../types";

/** לשוניות הסינון. פותחים על "חשוב" — זה הסינון שהמשתמש ביקש לראות ראשון */
type Tab = "important" | "other" | "all";

export default function Mail() {
  const [scope, setScope] = useState<MailScope>("week");
  const [tab, setTab] = useState<Tab>("important");
  const [list, setList] = useState<MailList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 503 = צריך לחבר את גוגל בהגדרות. 502 = תקלה, אפשר לנסות שוב
  const [needsConnection, setNeedsConnection] = useState(false);
  const [open, setOpen] = useState<MailBody | null>(null);
  const [opening, setOpening] = useState<MailItem | null>(null);
  const [openError, setOpenError] = useState("");
  // מה שהרגע אורכב, לכפתור הביטול: השורות להחזרה, והמזהים שהוצאו
  // בפועל. ⚠️ נשמר בזיכרון המסך בלבד — רענון מאבד את הביטול, והמיילים
  // נשארים בארכיון ולא נמחקים
  const [undo, setUndo] = useState<{ rows: MailItem[]; ids: string[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  // הטיוטה שממתינה לאישור בטופס. ⚠️ עד "שמור" לא נוצר כלום
  const [drafting, setDrafting] = useState<{ item: MailItem; draft: TaskDraft } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setNeedsConnection(false);
    try {
      setList(await api<MailList>(`/emails${query({ scope })}`));
    } catch (e) {
      setList(null);
      setNeedsConnection(e instanceof ApiError && e.status === 503);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  /** פתיחת מייל לקריאה. הגוף נשלף מגוגל רק עכשיו, ולא נשלף לרשימה בכלל */
  const read = async (item: MailItem) => {
    setOpening(item);
    setOpenError("");
    setOpen(null);
    try {
      setOpen(await api<MailBody>(`/emails/${encodeURIComponent(item.id)}`));
    } catch (e) {
      setOpenError((e as Error).message);
    }
  };

  const closeRead = () => {
    setOpening(null);
    setOpen(null);
    setOpenError("");
  };

  /** מסיר שורה מהתצוגה ומתקן את המונים, בלי לפנות שוב לגוגל */
  const drop = (item: MailItem, removed: boolean) =>
    setList((current) => {
      if (!current) return current;
      const items = removed
        ? current.items.filter((row) => row.id !== item.id)
        : [...current.items, item].sort((a, b) => b.received_at.localeCompare(a.received_at));
      const step = removed ? -1 : 1;
      return {
        ...current,
        items,
        important: current.important + (item.important ? step : 0),
        other: current.other + (item.important ? 0 : step),
      };
    });

  /**
   * ארכוב. ⚠️ אינו מוחק: המייל יוצא מהדואר הנכנס, נשאר בתיבה, ונמצא
   * בחיפוש. לכן אין כאן שאלת אישור — יש כפתור ביטול.
   */
  const archive = async (rows: MailItem[]) => {
    if (rows.length === 0) return;
    // ⚠️⚠️ כל ההודעות של כל שרשור, ולא ה-id של השורה. ארכוב ההודעה
    // האחרונה בלבד השאיר את הישנה בדואר הנכנס, והשורה חזרה ברענון
    const ids = rows.flatMap((row) => (row.thread_ids.length ? row.thread_ids : [row.id]));
    setBusy(rows[0].id);
    setError("");
    rows.forEach((row) => drop(row, true));
    closeRead();
    try {
      const done = await api<{ ids: string[] }>("/emails/archive", { method: "POST", body: { ids } });
      // ⚠️ נשמר בדיוק מה שהוצא, כדי שהביטול לא יחזיר הודעה שהייתה
      // מארוכבת עוד קודם
      setUndo({ rows, ids: done.ids });
    } catch (e) {
      // נכשל — השורות חוזרות, אחרת המסך היה משקר על מה שבתיבה
      rows.forEach((row) => drop(row, false));
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const undoArchive = async () => {
    if (!undo) return;
    const { rows, ids } = undo;
    setUndo(null);
    setBusy(rows[0].id);
    try {
      await api("/emails/unarchive", { method: "POST", body: { ids } });
      rows.forEach((row) => drop(row, false));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  /**
   * "הפוך למשימה": שואל מהשרת הצעה, ופותח את טופס המשימה הקיים מלא
   * מראש. ⚠️ **לא נוצר כלום עד שלוחצים "שמור"** — הפיכת מייל למשימה
   * כמעט תמיד דורשת עריכה, וזה היתרון של המסך על הבוט.
   */
  const toTask = async (item: MailItem) => {
    setBusy(item.id);
    setError("");
    try {
      const d = await api<TaskDraft>(`/emails/${encodeURIComponent(item.id)}/task-draft`);
      setDrafting({ item, draft: d });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  /** ארכוב של כל הלא-חשובים. ⚠️ שואל, כי אצווה גדולה מלחיצה אחת */
  const archiveAllOther = async () => {
    const rows = (list?.items ?? []).filter((row) => !row.important);
    if (rows.length === 0) return;
    if (!confirm(`לארכב ${rows.length} מיילים שסומנו "לא חשוב"? הם לא יימחקו, ואפשר לבטל.`)) return;
    await archive(rows);
  };

  const items = (list?.items ?? []).filter(
    (item) => tab === "all" || (tab === "important" ? item.important : !item.important),
  );

  const counts: Record<Tab, number> = {
    important: list?.important ?? 0,
    other: list?.other ?? 0,
    all: (list?.important ?? 0) + (list?.other ?? 0),
  };
  const TAB_LABELS: Record<Tab, string> = { important: "חשוב", other: "לא חשוב", all: "הכול" };

  return (
    <div>
      <h1>מיילים</h1>
      <p className="muted">
        כל הדואר הנכנס בטווח הזמן — גם מה שנקרא וגם כל הלשוניות — מסודר לפי חשוב ולא חשוב, שורה
        לכל שרשור. הסיווג נעשה על הכותרות בלבד, ואפשר לפתוח כל מייל לקריאה. ⚠️ שום תוכן מייל אינו
        נשמר: הוא נקרא מגוגל ברגע שאתה מבקש אותו.
      </p>

      {/* חלון הזמן. נפרד מלשוניות הסינון, כי הוא מה שנשלף מגוגל ולא מה שמסונן */}
      <div className="toolbar">
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as MailScope)}
          aria-label="חלון זמן"
        >
          {(Object.keys(MAIL_SCOPE_LABELS) as MailScope[]).map((s) => (
            <option key={s} value={s}>
              {MAIL_SCOPE_LABELS[s]}
            </option>
          ))}
        </select>
        <button className="link-btn" onClick={load} disabled={loading}>
          רענון
        </button>
        {/* רק בלשונית "לא חשוב": ארכוב קבוצתי של מה שמוצג בה */}
        {tab === "other" && counts.other > 0 && (
          <button onClick={archiveAllOther} disabled={busy !== null}>
            ארכב את כל {counts.other} הלא-חשובים
          </button>
        )}
      </div>

      {/* הסינון עצמו. הרשימה כבר ביד, ולכן מעבר בין לשוניות אינו פונה לגוגל */}
      <div className="when-tabs" role="tablist" aria-label="סינון">
        {(["important", "other", "all"] as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "on" : ""}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
            {list && <span className="badge">{counts[t]}</span>}
          </button>
        ))}
      </div>

      {/* הביטול יושב מעל הרשימה ולא נעלם מעצמו: מי שארכב בטעות צריך
          למצוא אותו, ולא להספיק ללחוץ בתוך חמש שניות */}
      {undo && (
        <div className="card mail-undo">
          <span>
            {undo.rows.length === 1
              ? `«${undo.rows[0].subject}» הועבר לארכיון.`
              : `${undo.rows.length} מיילים הועברו לארכיון.`}{" "}
            הם לא נמחקו — נשארים בתיבה ונמצאים בחיפוש.
          </span>
          <button onClick={undoArchive} disabled={busy === undo.rows[0].id}>
            ביטול
          </button>
          <button className="link-btn" onClick={() => setUndo(null)}>
            סגור
          </button>
        </div>
      )}

      {needsConnection ? (
        <div className="card">
          <div className="card-title">חשבון הגוגל לא מחובר</div>
          <p className="muted">{error}</p>
          <Link to="/settings">למסך ההגדרות</Link>
        </div>
      ) : error ? (
        <div className="card">
          <p className="error">{error}</p>
          <button onClick={load}>נסה שוב</button>
        </div>
      ) : loading && !list ? (
        <div className="card muted">טוען מיילים…</div>
      ) : items.length === 0 ? (
        <div className="card muted">
          {counts.all === 0
            ? `אין מיילים בדואר הנכנס ב${MAIL_SCOPE_LABELS[scope]}.`
            : `אין כאן מיילים. יש ${counts.all} בסך הכול — אפשר לעבור ללשונית אחרת.`}
        </div>
      ) : (
        <>
          {list?.truncated && (
            <p className="muted">
              מוצגים {counts.all} המיילים האחרונים. ייתכן שיש עוד בטווח הזמן שנבחר.
            </p>
          )}
          <ul className="task-list">
            {items.map((item) => (
              <MailRow
                key={item.id}
                item={item}
                busy={busy === item.id}
                onOpen={() => read(item)}
                onArchive={() => archive([item])}
              />
            ))}
          </ul>
        </>
      )}

      {opening && (
        <Modal title={opening.subject} onClose={closeRead}>
          <div className="task-meta">
            <span>{opening.sender}</span>
            {opening.sender_email && <span>{opening.sender_email}</span>}
            <span>{formatWhen(opening.received_at)}</span>
            {/* נפתחת ההודעה האחרונה בשרשור. בלי זה אפשר לקרוא אחת ולהחמיץ
                את הקודמות, בלי לדעת בכלל שהן קיימות */}
            {opening.thread_count > 1 && (
              <span>ההודעה האחרונה מתוך {opening.thread_count} בשרשור</span>
            )}
          </div>
          {openError ? (
            <p className="error">{openError}</p>
          ) : !open ? (
            <p className="muted">טוען את המייל…</p>
          ) : (
            <div className="details">
              {open.attachments.length > 0 && (
                <div className="muted">
                  📎 {open.attachments.join(" · ")}
                </div>
              )}
              {/* ⚠️ טקסט, לא HTML. מייל הוא מה שאדם אחר כתב, ו-dangerouslySetInnerHTML
                  כאן היה מריץ את ה-HTML שלו בדשבורד. ההמרה לטקסט נעשית בשרת */}
              <pre>{linkify(open.body)}</pre>
              {open.quoted_removed && (
                <p className="muted">
                  ההיסטוריה המצוטטת בסוף המייל הושמטה. היא נמצאת בג׳ימייל.
                </p>
              )}
              <div className="actions">
                <button disabled={busy === opening.id} onClick={() => archive([opening])}>
                  ארכוב
                </button>
                <button disabled={busy === opening.id} onClick={() => toTask(opening)}>
                  {busy === opening.id ? "מכין…" : "הפוך למשימה"}
                </button>
              </div>
            </div>
          )}
        </Modal>
      )}

      {/* טופס המשימה הקיים, מלא מראש מהמייל. ⚠️ עד "שמור" לא נוצר כלום */}
      {drafting && (
        <Modal title="משימה מהמייל" onClose={() => setDrafting(null)}>
          <TaskForm
            defaults={{
              title: drafting.draft.title,
              due_date: drafting.draft.due_date,
              notes: drafting.draft.notes,
              client_id: drafting.draft.client_id,
              email_message_id: drafting.draft.email_message_id,
            }}
            onSaved={async () => {
              const item = drafting.item;
              setDrafting(null);
              // ⚠️ הארכוב אחרי השמירה, ורק אחריה. אם הוא ייכשל המשימה
              // כבר קיימת ונשארת — למחוק משימה בגלל תקלת רשת גרוע בהרבה
              await archive([item]);
            }}
            onCancel={() => setDrafting(null)}
          />
        </Modal>
      )}
    </div>
  );
}

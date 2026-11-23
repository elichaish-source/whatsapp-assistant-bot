import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, query } from "../api";
import Modal from "../components/Modal";
import { formatWhen } from "../format";
import { MAIL_SCOPE_LABELS, type MailBody, type MailItem, type MailList, type MailScope } from "../types";

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
        כל הדואר הנכנס בטווח הזמן — גם מה שנקרא וגם כל הלשוניות — מסודר לפי חשוב ולא חשוב. הסיווג
        נעשה על הכותרות בלבד, ואפשר לפתוח כל מייל לקריאה. ⚠️ שום תוכן מייל אינו נשמר: הוא נקרא
        מגוגל ברגע שאתה מבקש אותו.
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
              <li
                key={item.id}
                className={`card clickable mail ${item.unread ? "unread" : ""}`}
                onClick={() => read(item)}
              >
                <div className="mail-head">
                  <span className="mail-sender">
                    {item.unread && (
                      <>
                        <span className="mail-dot" aria-hidden="true">
                          ●
                        </span>
                        <span className="sr-only">לא נקרא</span>
                      </>
                    )}
                    {item.sender}
                    {item.is_client && (
                      <span className="pill" title="כתובת רשומה בכרטיס לקוח">
                        לקוח
                      </span>
                    )}
                  </span>
                  <span className="muted mail-when">
                    {item.has_attachments && (
                      <>
                        <span title="יש קובץ מצורף" aria-hidden="true">
                          📎
                        </span>
                        <span className="sr-only">יש קובץ מצורף</span>
                      </>
                    )}
                    {formatWhen(item.received_at)}
                  </span>
                </div>
                <div className="mail-subject">{item.subject}</div>
                {item.line && <div className="muted clamp">{item.line}</div>}
              </li>
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
              <pre>{open.body}</pre>
              {open.quoted_removed && (
                <p className="muted">
                  ההיסטוריה המצוטטת בסוף המייל הושמטה. היא נמצאת בג׳ימייל.
                </p>
              )}
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}

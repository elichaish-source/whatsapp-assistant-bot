import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { formatWhen } from "../format";
import { linkify } from "../linkify";
import type { BotHistory, BotMessage, BotPending, BotStatus } from "../types";

/**
 * מסך הוואטסאפ — הבוט בדשבורד.
 *
 * ⚠️⚠️ **זהו «הבוט הפנימי»**: שיקוף הבוט אינו מסך נוסף אלא המסך הזה.
 * שני מסכים לדבר אחד הם בדיוק מה שהעיקרון המנחה בא למנוע.
 *
 * ⚠️ **מוח אחד, ערוץ עשיר יותר.** מה שנוסף כאן הוא רינדור — כפתורים
 * במקום מספרים, רשימה שלמה בלי פיצול ל-4096 תווים, וקישור למסך
 * המיילים — ולא יכולת שקיימת רק כאן.
 *
 * ⚠️ **הודעה שנכתבת כאן אינה יוצאת בוואטסאפ**, והודעה שהמערכת יוזמת
 * יוצאת שם ומופיעה גם כאן.
 */
type Tab = "chat" | "alerts" | "unclear" | "pending";

const TAB_LABELS: Record<Tab, string> = {
  chat: "שיחה",
  alerts: "התראות",
  unclear: "לא הבין",
  pending: "לא אושרו",
};

/** צבע ומילה למצב החיבור. ⚠️ «לא הצלחתי להגיע» שונה מ«נותקנו» */
const STATE_LABELS: Record<string, string> = {
  connected: "מחובר",
  scan: "ממתין לסריקה",
  starting: "עולה",
  failed: "מנותק",
  unreachable: "אין קשר ל-WAHA",
  unknown: "לא ידוע",
};

export default function WhatsApp() {
  const [tab, setTab] = useState<Tab>("chat");
  const [history, setHistory] = useState<BotHistory | null>(null);
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [alerts, setAlerts] = useState<BotMessage[]>([]);
  const [unclear, setUnclear] = useState<BotMessage[]>([]);
  const [pending, setPending] = useState<BotPending[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const bottom = useRef<HTMLDivElement | null>(null);

  const loadChat = useCallback(async () => {
    setHistory(await api<BotHistory>("/whatsapp/messages"));
  }, []);

  const loadSide = useCallback(async () => {
    const [a, u, p] = await Promise.all([
      api<BotMessage[]>("/whatsapp/alerts"),
      api<BotMessage[]>("/whatsapp/unclear"),
      api<BotPending[]>("/whatsapp/pending"),
    ]);
    setAlerts(a);
    setUnclear(u);
    setPending(p);
  }, []);

  const loadAll = useCallback(async () => {
    setError("");
    try {
      await Promise.all([
        loadChat(),
        loadSide(),
        api<BotStatus>("/whatsapp/status").then(setStatus),
      ]);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [loadChat, loadSide]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // ההודעה האחרונה למטה, כמו בצ'אט
  useEffect(() => {
    if (tab === "chat") bottom.current?.scrollIntoView({ block: "end" });
  }, [history, tab]);

  const older = async () => {
    const first = history?.messages[0];
    if (!first) return;
    const more = await api<BotHistory>(`/whatsapp/messages?before=${first.id}`);
    setHistory((current) =>
      current ? { messages: [...more.messages, ...current.messages], more: more.more } : more,
    );
  };

  /** ⚠️ התשובה חוזרת למסך בלבד — היא אינה יוצאת בוואטסאפ */
  const send = async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setError("");
    try {
      const row = await api<BotMessage>("/whatsapp/messages", {
        method: "POST",
        body: { body: text },
      });
      setDraft("");
      setHistory((current) =>
        current ? { ...current, messages: [...current.messages, row] } : null,
      );
      loadSide();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  };

  /**
   * כפתור במקום מספר: סוגר את המשימה שהבוט הציג.
   * ⚠️ עובר דרך נתיב המשימות הקיים ולא דרך המודל — זה הנתון שכבר
   * נשמר (`listed_task_ids`), ואין כאן ניחוש של מי הכוונה.
   */
  const complete = async (messageId: number, taskId: number) => {
    setBusy(taskId);
    setError("");
    try {
      await api(`/tasks/${taskId}/status`, { method: "PATCH", body: { status: "done" } });
      setHistory((current) =>
        current
          ? {
              ...current,
              messages: current.messages.map((m) =>
                m.id === messageId
                  ? {
                      ...m,
                      tasks: m.tasks.map((t) => (t.id === taskId ? { ...t, status: "done" } : t)),
                    }
                  : m,
              ),
            }
          : current,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const handled = async (id: number) => {
    setBusy(id);
    try {
      await api(`/whatsapp/messages/${id}/handled`, { method: "POST" });
      setAlerts((rows) => rows.filter((r) => r.id !== id));
      setUnclear((rows) => rows.filter((r) => r.id !== id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  /** ⚠️ מה שמבוצע נקרא בשרת מהשורה עצמה, ולא ממה שהמסך שולח */
  const confirmPending = async (item: BotPending) => {
    if (!confirm(`${item.summary}\n\nלבצע עכשיו?`)) return;
    setBusy(item.id);
    setError("");
    try {
      await api(`/whatsapp/pending/${item.id}/confirm`, { method: "POST" });
      setPending((rows) => rows.filter((r) => r.id !== item.id));
      loadChat();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const dismissPending = async (item: BotPending) => {
    setBusy(item.id);
    try {
      await api(`/whatsapp/pending/${item.id}/dismiss`, { method: "POST" });
      setPending((rows) => rows.filter((r) => r.id !== item.id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const reuse = (text: string) => {
    setDraft(text);
    setTab("chat");
  };

  const counts: Record<Tab, number> = {
    chat: 0,
    alerts: alerts.length,
    unclear: unclear.length,
    pending: pending.length,
  };

  return (
    <div>
      <h1>וואטסאפ</h1>
      <p className="muted">
        הבוט בדשבורד. אותו מוח ואותן פעולות בדיוק — מה שנוסף כאן הוא כפתורים במקום מספרים
        ורשימה שלמה בלי חיתוך. ⚠️ הודעה שנכתבת כאן נענית כאן בלבד ואינה יוצאת בוואטסאפ; תזכורת
        או התראה שהמערכת שולחת יוצאות בוואטסאפ ומופיעות גם כאן.
      </p>

      {/* מצב החיבור, קריאה בלבד. ⚠️ היכולת שחסרה הכי: כשוואטסאפ מנתקת
          את השרת, היום שום דבר אינו אומר זאת והתזכורות פשוט נפסקות */}
      <div className={`card wa-status ${status?.state ?? ""}`}>
        <div>
          <span className="card-title">
            {status ? (STATE_LABELS[status.state] ?? status.state) : "בודק…"}
          </span>
          {status?.phone && <span className="muted"> · {status.phone}</span>}
          {status?.raw && <span className="muted"> · {status.raw}</span>}
        </div>
        {status?.message && <p className="muted">{status.message}</p>}
        <button className="link-btn" onClick={loadAll}>
          רענון
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="when-tabs" role="tablist" aria-label="לשוניות">
        {(["chat", "alerts", "unclear", "pending"] as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "on" : ""}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
            {counts[t] > 0 && <span className="badge">{counts[t]}</span>}
          </button>
        ))}
      </div>

      {tab === "chat" && (
        <>
          {history?.more && (
            <button className="link-btn" onClick={older}>
              הודעות קודמות
            </button>
          )}
          <div className="wa-chat">
            {!history ? (
              <div className="card muted">טוען…</div>
            ) : history.messages.length === 0 ? (
              <div className="card muted">
                אין עדיין שיחה. אפשר לכתוב כאן בדיוק כמו בוואטסאפ — «תזכיר לי מחר להתקשר לדני».
              </div>
            ) : (
              history.messages.map((m) => (
                <Bubble
                  key={m.id}
                  message={m}
                  busy={busy}
                  onComplete={(taskId) => complete(m.id, taskId)}
                />
              ))
            )}
            <div ref={bottom} />
          </div>

          <div className="wa-compose">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                // Enter שולח, Shift+Enter יורד שורה
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="מה לכתוב לבוט?"
              rows={2}
              aria-label="הודעה לבוט"
            />
            <button className="primary" onClick={send} disabled={sending || !draft.trim()}>
              {sending ? "חושב…" : "שלח"}
            </button>
          </div>
        </>
      )}

      {tab === "alerts" && (
        <Side
          rows={alerts}
          busy={busy}
          empty="אין התראות פתוחות. כל מה שהמערכת שלחה סומן כטופל."
          onHandled={handled}
        />
      )}

      {tab === "unclear" && (
        <Side
          rows={unclear}
          busy={busy}
          empty="הבוט הבין את כל מה שנכתב לו בחודש האחרון."
          onHandled={handled}
          onReuse={reuse}
        />
      )}

      {tab === "pending" && (
        <ul className="task-list">
          {pending.length === 0 ? (
            <li className="card muted">אין פעולות שממתינות. כל מה שהבוט שאל נענה בזמן.</li>
          ) : (
            pending.map((item) => (
              <li key={item.id} className="card">
                <div className="card-title">{item.summary}</div>
                <div className="task-meta">
                  <span>{formatWhen(item.created_at)}</span>
                  <span>{item.channel === "screen" ? "נכתב במסך" : "נכתב בוואטסאפ"}</span>
                </div>
                {/* ⚠️ מה שהבוט שאל, כפי שנשלח. זה מה שמזהים */}
                {item.question && <p className="muted pre-line">{item.question}</p>}
                <div className="actions">
                  {item.executable ? (
                    <button
                      className="primary"
                      disabled={busy === item.id}
                      onClick={() => confirmPending(item)}
                    >
                      בצע עכשיו
                    </button>
                  ) : (
                    <span className="muted">כבר אי אפשר לבצע את זה.</span>
                  )}
                  <button disabled={busy === item.id} onClick={() => dismissPending(item)}>
                    הסר
                  </button>
                </div>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

/** שורה אחת בשיחה. ⚠️ הערוץ מסומן תמיד */
function Bubble({
  message,
  busy,
  onComplete,
}: {
  message: BotMessage;
  busy: number | null;
  onComplete: (taskId: number) => void;
}) {
  const from = message.initiated
    ? "הבוט יזם"
    : message.channel === "screen"
      ? "נכתב במסך"
      : "נכתב בוואטסאפ";
  return (
    <div className={`wa-turn ${message.channel}`}>
      {message.body && (
        <div className="wa-bubble mine">
          <div className="pre-line">{message.body}</div>
          <div className="wa-meta">
            {from} · {formatWhen(message.created_at)}
          </div>
        </div>
      )}
      {message.reply && (
        <div className={`wa-bubble bot ${message.initiated ? "initiated" : ""}`}>
          <div className="pre-line">{linkify(message.reply)}</div>

          {/* כפתורים במקום מספרים. ⚠️ הנתון הוא `listed_task_ids`,
              בדיוק מה ש"סיימתי 2" נפתר מולו בוואטסאפ */}
          {message.tasks.length > 0 && (
            <ul className="wa-items">
              {message.tasks.map((task) => (
                <li key={task.id}>
                  <span className="muted">{task.number}.</span> {task.title}
                  {task.status === "done" ? (
                    <span className="badge">בוצעה</span>
                  ) : (
                    <button
                      className="link-btn"
                      disabled={busy === task.id}
                      onClick={() => onComplete(task.id)}
                    >
                      סיימתי
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {/* ⚠️ מייל אינו נפתח כאן: במסך המיילים כבר יש ארכוב, מענה
              והפוך למשימה, ושכפולם כאן היה מכפיל קוד */}
          {message.emails.length > 0 && (
            <div className="chips">
              <Link className="chip" to="/mail">
                {message.emails.length === 1
                  ? "פתח במסך המיילים"
                  : `${message.emails.length} מיילים — למסך המיילים`}
              </Link>
            </div>
          )}

          <div className="wa-meta">
            {message.initiated ? "הודעה יוזמת · יצאה גם בוואטסאפ" : from} ·{" "}
            {formatWhen(message.created_at)}
            {message.intent && ` · ${message.intent}`}
          </div>
        </div>
      )}
    </div>
  );
}

/** לשונית שהיא רשימת שורות עם כפתור "טופל" */
function Side({
  rows,
  busy,
  empty,
  onHandled,
  onReuse,
}: {
  rows: BotMessage[];
  busy: number | null;
  empty: string;
  onHandled: (id: number) => void;
  onReuse?: (text: string) => void;
}) {
  if (rows.length === 0) return <div className="card muted">{empty}</div>;
  return (
    <ul className="task-list">
      {rows.map((row) => (
        <li key={row.id} className="card">
          <div className="pre-line">{row.body || row.reply}</div>
          {row.body && row.reply && <p className="muted pre-line">{row.reply}</p>}
          <div className="task-meta">
            <span>{formatWhen(row.created_at)}</span>
            <span>{row.channel === "screen" ? "במסך" : "בוואטסאפ"}</span>
            {row.intent && <span>{row.intent}</span>}
          </div>
          <div className="actions">
            {onReuse && row.body && (
              <button className="primary" onClick={() => onReuse(row.body as string)}>
                נסח מחדש
              </button>
            )}
            <button disabled={busy === row.id} onClick={() => onHandled(row.id)}>
              טופל
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}

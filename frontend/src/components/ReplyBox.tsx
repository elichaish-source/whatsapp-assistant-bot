import { useState } from "react";
import { api } from "../api";
import type { ReplyDraft, ReplySent } from "../types";

/**
 * כתיבת תשובה למייל ושליחתה.
 *
 * ⚠️⚠️ **השליחה היא הפעולה היחידה במסך שאי אפשר לבטל**, ולכן היא
 * הכפתור היחיד ששואל לפני. האישור מציג את הנמען ואת הטקסט המלא —
 * בדיוק מה שייצא — ורק אחריו נשלח.
 *
 * ⚠️ **הנמען מגיע מהשרת ואינו ניתן לעריכה כאן.** הוא נגזר מהמייל
 * המקורי, אחרת היה אפשר לגרום למסך לשלוח לכל כתובת.
 */
export default function ReplyBox({
  messageId,
  draft,
  onSent,
  onCancel,
}: {
  messageId: string;
  draft: ReplyDraft;
  onSent: (sent: ReplySent) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const send = async () => {
    setBusy(true);
    setError("");
    try {
      const sent = await api<ReplySent>(`/emails/${encodeURIComponent(messageId)}/reply`, {
        method: "POST",
        body: { body: text },
      });
      onSent(sent);
    } catch (e) {
      setError((e as Error).message);
      setConfirming(false);
    } finally {
      setBusy(false);
    }
  };

  if (confirming) {
    return (
      <div className="reply">
        <div className="card reply-confirm">
          <div className="card-title">לשלוח את התשובה?</div>
          <div className="task-meta">
            <span>אל: {draft.to}</span>
            <span>{draft.subject}</span>
          </div>
          {/* הטקסט המלא, ולא תקציר: זה מה שייצא */}
          <pre>{text}</pre>
          <p className="muted">⚠️ אחרי השליחה אי אפשר לבטל. המייל יעבור גם לארכיון.</p>
          {error && <p className="error">{error}</p>}
          <div className="actions">
            <button className="primary" onClick={send} disabled={busy}>
              {busy ? "שולח…" : "שלח"}
            </button>
            <button onClick={() => setConfirming(false)} disabled={busy}>
              חזרה לעריכה
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="reply">
      <div className="task-meta">
        <span>אל: {draft.to}</span>
        <span>{draft.subject}</span>
      </div>

      {draft.options.length > 0 ? (
        <div className="reply-options">
          {draft.options.map((option, index) => (
            <button key={index} className="reply-option" onClick={() => setText(option.text)}>
              <strong>{option.label || `אפשרות ${index + 1}`}</strong>
              <span className="muted clamp">{option.text}</span>
            </button>
          ))}
        </div>
      ) : (
        // ⚠️ הצעות הן נוחות ולא תנאי: בלי הן פשוט כותבים
        <p className="muted">לא הוכנו הצעות הפעם. אפשר לכתוב תשובה כאן.</p>
      )}

      <textarea
        className="reply-text"
        rows={8}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="התשובה שתישלח…"
        aria-label="גוף התשובה"
      />
      {error && <p className="error">{error}</p>}
      <div className="actions">
        <button className="primary" disabled={!text.trim()} onClick={() => setConfirming(true)}>
          המשך לשליחה
        </button>
        <button onClick={onCancel}>ביטול</button>
      </div>
    </div>
  );
}

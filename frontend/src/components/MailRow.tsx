import { formatWhen } from "../format";
import type { MailItem } from "../types";
import { useSwipe } from "../useSwipe";

/**
 * שורה אחת ברשימת המיילים.
 *
 * ⚠️ **רכיב בפני עצמו ולא JSX בתוך `map`**, כי `useSwipe` הוא hook
 * ואסור לקרוא לו בלולאה.
 *
 * ⚠️ **כפתור הארכוב בלבד מוסתר במסך מגע**, כי שם מארכבים בהחלקה
 * ימינה כמו בג׳ימייל. "למשימה" ו"מענה" נשארים בכל מכשיר — אין להם
 * תנועה מקבילה, והמשתמש ביקש אותם על המסך ולא בתוך המייל.
 */
export default function MailRow({
  item,
  busy,
  onOpen,
  onArchive,
  onTask,
  onReply,
}: {
  item: MailItem;
  busy: boolean;
  onOpen: () => void;
  onArchive: () => void;
  onTask: () => void;
  onReply: () => void;
}) {
  const swipe = useSwipe(onArchive);

  return (
    <li className="mail-slot">
      {/* הרקע שמתגלה מתחת לשורה בזמן ההחלקה */}
      <div className={`mail-swipe ${swipe.armed ? "armed" : ""}`} aria-hidden="true">
        <span>↩ ארכוב</span>
      </div>
      <div
        className={`card clickable mail ${item.unread ? "unread" : ""}`}
        style={{
          transform: swipe.dx ? `translateX(${swipe.dx}px)` : undefined,
          // בלי מעבר בזמן הגרירה, אחרת השורה נגררת אחרי האצבע
          transition: swipe.dx ? "none" : undefined,
        }}
        onClick={() => {
          if (swipe.consumedClick()) return;
          onOpen();
        }}
        {...swipe.handlers}
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
            {/* שורה אחת לכל שרשור. המונה מראה שלא נעלמה הודעה */}
            {item.thread_count > 1 && (
              <span className="pill" title={`${item.thread_count} הודעות בשרשור הזה`}>
                {item.thread_count}
              </span>
            )}
            {item.is_client && (
              <span className="pill" title="כתובת רשומה בכרטיס לקוח">
                לקוח
              </span>
            )}
            {/* ⚠️ מחכה לתשובה בכתב, ולא סתם חשוב */}
            {item.needs_reply && (
              <span className="pill needs-reply" title="מחכה לתשובה בכתב">
                דורש מענה
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
        {/* מחוץ לאזור הלחיצה שפותח את המייל, אחרת ארכוב היה פותח אותו
            באותה לחיצה */}
        {/* ⚠️ מחוץ לאזור הלחיצה שפותח את המייל, אחרת כל כפתור היה גם
            פותח אותו באותה לחיצה */}
        <div className="mail-actions" onClick={(e) => e.stopPropagation()}>
          {/* ⚠️ הארכוב בלבד מוסתר במסך מגע, כי שם מארכבים בהחלקה.
              המענה וההפיכה למשימה נשארים — אין להם תנועה מקבילה */}
          <button className="link-btn mail-archive-btn" disabled={busy} onClick={onArchive}>
            ארכוב
          </button>
          <button className="link-btn" disabled={busy} onClick={onTask}>
            {busy ? "מכין…" : "למשימה"}
          </button>
          <button className="link-btn" disabled={busy} onClick={onReply}>
            {busy ? "מכין…" : "מענה"}
          </button>
        </div>
      </div>
    </li>
  );
}

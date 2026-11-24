import { formatWhen } from "../format";
import type { MailItem } from "../types";
import { useSwipe } from "../useSwipe";

/**
 * שורה אחת ברשימת המיילים.
 *
 * ⚠️ **רכיב בפני עצמו ולא JSX בתוך `map`**, כי `useSwipe` הוא hook
 * ואסור לקרוא לו בלולאה.
 *
 * ⚠️ **כפתור הארכוב מוצג רק במכשירים עם עכבר** (`@media (hover: hover)`
 * ב-`styles.css`). בנייד מארכבים בהחלקה ימינה, כמו בג'ימייל.
 */
export default function MailRow({
  item,
  busy,
  onOpen,
  onArchive,
}: {
  item: MailItem;
  busy: boolean;
  onOpen: () => void;
  onArchive: () => void;
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
        <div className="mail-actions" onClick={(e) => e.stopPropagation()}>
          <button className="link-btn" disabled={busy} onClick={onArchive}>
            ארכוב
          </button>
        </div>
      </div>
    </li>
  );
}

import { useRef, useState } from "react";

/** מעבר לסף — משחררים ומארכבים. 35% מהרוחב, ולא פחות מ-80 פיקסלים */
const PART = 0.35;
const MIN = 80;
/** מתחת לזה זו עוד לא החלקה אלא רעידה של האצבע */
const SLOP = 8;

/**
 * החלקה ימינה על שורה, כמו בג'ימייל.
 *
 * ⚠️ **נעילת ציר:** התנועה נחשבת החלקה רק אם היא אופקית יותר מאנכית.
 * בלי זה גלילה אנכית ברשימה הייתה מארכבת מיילים בטעות.
 *
 * ⚠️ **`translateX` הוא פיזי ולא לוגי**, גם ב-RTL: "ימינה" הוא ערך
 * חיובי, בלי היפוך.
 *
 * ⚠️ **אחרי החלקה הלחיצה נחסמת**, אחרת אותה תנועה גם מארכבת וגם פותחת
 * את המייל.
 */
export function useSwipe(onSwipe: () => void) {
  const [dx, setDx] = useState(0);
  const start = useRef<{ x: number; y: number } | null>(null);
  const axis = useRef<"none" | "x" | "y">("none");
  const swiped = useRef(false);

  const reset = () => {
    start.current = null;
    axis.current = "none";
    setDx(0);
  };

  return {
    /** הזזה בפיקסלים, להנפשה של השורה */
    dx,
    /** האם חצינו את הסף — לשינוי הרקע שמתגלה מתחת */
    armed: dx >= MIN,
    /** נקרא ב-onClick של השורה: true פירושו שהלחיצה אינה אמיתית */
    consumedClick: () => {
      if (!swiped.current) return false;
      swiped.current = false;
      return true;
    },
    handlers: {
      onTouchStart: (e: React.TouchEvent) => {
        const touch = e.touches[0];
        start.current = { x: touch.clientX, y: touch.clientY };
        axis.current = "none";
      },
      onTouchMove: (e: React.TouchEvent) => {
        if (!start.current) return;
        const touch = e.touches[0];
        const moveX = touch.clientX - start.current.x;
        const moveY = touch.clientY - start.current.y;

        if (axis.current === "none") {
          if (Math.abs(moveX) < SLOP && Math.abs(moveY) < SLOP) return;
          axis.current = Math.abs(moveX) > Math.abs(moveY) ? "x" : "y";
        }
        // גלילה אנכית — לא נוגעים בה
        if (axis.current === "y") return;
        // רק ימינה. שמאלה אין פעולה, ולכן השורה לא זזה
        setDx(Math.max(0, moveX));
      },
      onTouchEnd: (e: React.TouchEvent) => {
        const width = (e.currentTarget as HTMLElement).offsetWidth || 1;
        const enough = dx >= Math.max(MIN, width * PART);
        if (axis.current === "x" && dx > SLOP) swiped.current = true;
        reset();
        if (enough) onSwipe();
      },
      onTouchCancel: reset,
    },
  };
}

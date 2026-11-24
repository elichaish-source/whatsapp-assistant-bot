import type { ReactNode } from "react";

/**
 * כתובת http/https בתוך טקסט.
 *
 * ⚠️ סוגריים ומרכאות אינם חלק מהכתובת: השרת כותב קישור כ-`טקסט (כתובת)`,
 * ובלי החרגה של `)` הסוגר היה נבלע לתוך הקישור.
 */
const URL_RE = /https?:\/\/[^\s<>"'`()[\]{}]+/gi;

/** פיסוק שנגרר בסוף משפט ואינו חלק מהכתובת: "ראה https://x.com/a." */
const TRAILING = /[.,;:!?״"'׳)\]}]+$/;

/**
 * הופך כתובות בתוך טקסט לקישורים לחיצים.
 *
 * ⚠️⚠️ **מחזיר רכיבי React ולא מחרוזת HTML.** ההבטחה שמייל מוצג כטקסט
 * ולא כ-HTML נשארת במלואה — אין כאן `dangerouslySetInnerHTML`, ותוכן
 * המייל לעולם אינו מתפרש כסימון. את הטקסט הזה כתב אדם אחר.
 *
 * ⚠️ **רק `http` ו-`https`.** הביטוי עצמו מתאים רק להם, וגם אם מישהו
 * ירחיב אותו, `safe()` חוסם `javascript:` ו-`data:`.
 */
export function linkify(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;

  URL_RE.lastIndex = 0;
  while ((match = URL_RE.exec(text)) !== null) {
    let url = match[0];
    const trailing = url.match(TRAILING)?.[0] ?? "";
    if (trailing) url = url.slice(0, -trailing.length);
    if (!url || !safe(url)) continue;

    if (match.index > last) out.push(text.slice(last, match.index));
    out.push(
      // ⚠️ dir="ltr" ובידוד כיווניות: כתובת בתוך טקסט עברי מתערבבת
      // ומוצגת הפוך בלי זה
      <a
        key={`${match.index}-${url}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        dir="ltr"
        className="mail-link"
      >
        {url}
      </a>,
    );
    out.push(trailing);
    last = match.index + match[0].length;
  }

  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** חוסם כל סכימה שאינה http/https, גם אם הביטוי יורחב בעתיד. */
function safe(url: string): boolean {
  try {
    const scheme = new URL(url).protocol;
    return scheme === "http:" || scheme === "https:";
  } catch {
    return false;
  }
}

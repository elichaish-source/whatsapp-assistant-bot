const TZ = "Asia/Jerusalem";

export function formatDate(value: string | null): string {
  if (!value) return "";
  const [y, m, d] = value.split("-");
  return `${d}/${m}/${y}`;
}

export function formatDateTime(value: string | null): string {
  if (!value) return "";
  return new Date(value).toLocaleString("he-IL", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** ממיר זמן מהשרת לערך של שדה datetime-local */
export function toLocalInput(value: string | null): string {
  if (!value) return "";
  const d = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** ממיר ערך של שדה datetime-local לזמן מלא עם אזור זמן */
export function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

export function isOverdue(date: string | null): boolean {
  if (!date) return false;
  const today = new Date().toLocaleDateString("en-CA", { timeZone: TZ });
  return date < today;
}

/**
 * שעה למייל של היום, ותאריך ושעה לכל השאר.
 *
 * ⚠️ בלי התאריך, רשימה שבועית מציגה "20:36" ו-"12:29" זה מתחת לזה כאילו
 * הם מאותו יום. זה היה באג אמיתי בסיכום של הבוט, ותוקן ב-19.11.2026.
 */
export function formatWhen(value: string): string {
  if (!value) return "";
  const when = new Date(value);
  const day = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: TZ });
  const time = when.toLocaleTimeString("he-IL", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
  });
  if (day(when) === day(new Date())) return time;
  const date = when.toLocaleDateString("he-IL", { timeZone: TZ, day: "2-digit", month: "2-digit" });
  return `${date} ${time}`;
}

/* --- היומן (4ב-4) --- */

/**
 * שמות הימים בעברית, לפי `getDay()` (0 = ראשון).
 * ⚠️ כתובים ביד ולא נגזרים מ-`Intl`, בדיוק כמו ב-`bot/events.py`: כך
 * אותו שם יוצא בבוט ובמסך, ואין תלות בטבלאות השפה של הדפדפן.
 */
const DAY_NAMES = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];

export function dayName(value: Date): string {
  return DAY_NAMES[value.getDay()];
}

/**
 * תאריך כ-"YYYY-MM-DD" **בשעון ישראל**.
 *
 * ⚠️⚠️ זה מה שקובע לאיזו עמודה בלוח האירוע שייך, ולכן הוא חייב להיות
 * בשעון של היומן ולא בשעון של הדפדפן. פגישה ב-00:30 תשב ביום הלא נכון
 * בכל דפדפן שאינו בישראל — וזאת שגיאה שקטה שאי אפשר לראות מהמשרד.
 * אותו דפוס של `isOverdue` ו-`formatWhen` כאן למעלה.
 */
export function dayKey(value: Date): string {
  return value.toLocaleDateString("en-CA", { timeZone: TZ });
}

/** דקות מתחילת היום, בשעון ישראל. זה המיקום האנכי של אירוע בלוח */
export function minutesOfDay(value: Date): number {
  const [h, m] = value
    .toLocaleTimeString("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false })
    .split(":");
  return Number(h) * 60 + Number(m);
}

/** "14:30", בשעון ישראל */
export function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString("he-IL", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** יום ראשון של השבוע שבו התאריך נמצא. בישראל השבוע מתחיל בראשון */
export function weekStart(value: Date): Date {
  const first = new Date(value);
  first.setDate(first.getDate() - first.getDay());
  return first;
}

/**
 * תאריך כ-"YYYY-MM-DD" מתוך `Date` מקומי, בלי מעבר ל-UTC.
 * ⚠️ `toISOString()` היה מזיז את התאריך ביום שלם בחצי הכהה של היממה,
 * כי הוא ממיר ל-UTC: 01/12 בחצות בישראל הוא 30/11 ב-UTC.
 */
export function toDateValue(value: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

/** "YYYY-MM-DD" ל-`Date` מקומי. ⚠️ `new Date("2026-11-25")` הוא UTC */
export function fromDateValue(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

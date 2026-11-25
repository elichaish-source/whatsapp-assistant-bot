export interface Lookup {
  id: number;
  name: string;
  sort_order: number;
}

export interface Domain extends Lookup {
  requires_client: boolean;
}

export interface Client {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  tax_id: string | null;
  address: string | null;
  notes: string | null;
  is_active: boolean;
  families: Lookup[];
  open_tasks: number;
}

export interface Project {
  id: number;
  name: string;
  domain_id: number;
  client_id: number | null;
  description: string | null;
  due_date: string | null;
  status: "active" | "done";
  open_tasks: number;
}

export type Priority = "today" | "tomorrow" | "week" | "later";

// מאיפה המשימה הגיעה. email ו-claude שמורים לאינטגרציות הבאות
export type TaskSource = "whatsapp" | "dashboard" | "email" | "claude";

export interface Task {
  id: number;
  title: string;
  status: "open" | "done";
  done_at: string | null;
  domain_id: number | null;
  task_type_id: number | null;
  client_id: number | null;
  project_id: number | null;
  due_date: string | null;
  reminder_at: string | null;
  priority: Priority;
  notes: string | null;
  source: TaskSource;
}

// הסדר כאן הוא סדר הכפתורים במסך, ולכן "מחר" יושב בין היום לשבוע
export const PRIORITY_LABELS: Record<Priority, string> = {
  today: "היום",
  tomorrow: "מחר",
  week: "השבוע",
  later: "בהמשך",
};

// אייקון בלבד בשורת המשימה. השם המלא יושב ב-title, ונקרא במרחף ובקורא מסך
export const SOURCE_ICONS: Record<TaskSource, string> = {
  whatsapp: "💬",
  dashboard: "🖥️",
  email: "✉️",
  claude: "✨",
};

export const SOURCE_LABELS: Record<TaskSource, string> = {
  whatsapp: "מוואטסאפ",
  dashboard: "נוצרה מהמערכת",
  email: "מהמייל",
  claude: "מקלוד",
};

export interface MemoryFact {
  id: number;
  dimension: number;
  content: string;
  client_id: number | null;
  project_id: number | null;
  source: "bot" | "dashboard";
  created_at: string;
  updated_at: string;
}

export interface MemoryDimension {
  id: number;
  name: string;
  // האם עובדות בממד הזה נשלחות לבוט בשלב הנוכחי
  in_prompt: boolean;
}

export type RepeatUnit = "week" | "month" | "year";

export interface Recurrence {
  id: number;
  title: string;
  interval_unit: RepeatUnit;
  interval_count: number;
  start_date: string;
  cycle: number;
  lead_days: number;
  domain_id: number | null;
  task_type_id: number | null;
  client_id: number | null;
  project_id: number | null;
  priority: Priority;
  notes: string | null;
  active: boolean;
  from_bot: boolean;
  // מחושבים בשרת: התאריך הבא, תיאור התדירות, והמשימה הפתוחה של המחזור הנוכחי
  next_due: string | null;
  every: string;
  open_task_id: number | null;
}

export const REPEAT_LABELS: Record<RepeatUnit, string> = {
  week: "שבועות",
  month: "חודשים",
  year: "שנים",
};

export interface GoogleStatus {
  // האם שלושת המפתחות קיימים ב-.env בשרת. בלעדיהם אין מה ללחוץ
  configured: boolean;
  connected: boolean;
  email: string;
  status: string;
  last_error: string;
  connected_at: string | null;
  last_checked_at: string | null;
  // הרשאות שביקשנו והמשתמש לא אישר במסך של גוגל
  missing_scopes: string[];
}

/** הקודים שכתובת החזרה של גוגל מחזירה ב-?google= */
export const GOOGLE_RESULTS: Record<string, string> = {
  ok: "גוגל חוברה.",
  partial: "גוגל חוברה, אבל לא כל ההרשאות אושרו.",
  denied: "החיבור בוטל במסך של גוגל.",
  state: "הבקשה לא הגיעה מהדשבורד, או שעברו יותר מ-15 דקות. נסה שוב.",
  exchange: "גוגל לא השלימה את החיבור. נסה שוב.",
  auth: "פג תוקף הכניסה לדשבורד באמצע החיבור. התחבר ונסה שוב.",
  config: "חיבור גוגל לא מוגדר בשרת.",
};

/** חלון הזמן במסך המיילים. השרת מקבל בדיוק את שלושת הערכים האלה */
export type MailScope = "today" | "week" | "month";

export const MAIL_SCOPE_LABELS: Record<MailScope, string> = {
  today: "היום",
  week: "השבוע",
  month: "החודש",
};

/**
 * מייל אחד בשורת הרשימה.
 * ⚠️ אינו נשמר בשום מקום: נקרא מגוגל ברגע הבקשה, מוצג, ונזרק.
 * ‏`line` הוא תיאור של משפט שהמודל הזול כתב, ולא טקסט מהמייל.
 */
export interface MailItem {
  id: string;
  thread_id: string;
  sender: string;
  sender_email: string;
  subject: string;
  line: string;
  received_at: string;
  important: boolean;
  // סומן חשוב בקוד ולא במודל, כי הכתובת רשומה בכרטיס לקוח
  is_client: boolean;
  unread: boolean;
  has_attachments: boolean;
  // כמה הודעות בשרשור שהשורה מייצגת. 1 = מייל בודד
  thread_count: number;
  // ⚠️ מחכה לתשובה בכתב. שונה מ-important: חשבונית חשובה, אבל עונים
  // עליה בתשלום ולא במילים
  needs_reply: boolean;
  // ⚠️ כל ההודעות של השרשור שבדואר הנכנס. זה מה שנשלח לארכוב,
  // ולא id לבדו — אחרת הודעה ישנה נשארת והשורה חוזרת ברענון
  thread_ids: string[];
}

export interface MailList {
  scope: MailScope;
  items: MailItem[];
  important: number;
  other: number;
  // נגענו בתקרת השליפה, וייתכן שיש עוד מיילים בטווח
  truncated: boolean;
}

/** המייל המלא לקריאה. ⚠️ `body` הוא טקסט ולא HTML, ומוצג כטקסט */
export interface MailBody {
  id: string;
  thread_id: string;
  sender: string;
  sender_email: string;
  to: string;
  subject: string;
  received_at: string;
  body: string;
  attachments: string[];
  // האם נחתכה היסטוריה מצוטטת. נאמר למשתמש, כדי שידע שיש עוד
  quoted_removed: boolean;
}

/**
 * הצעה למשימה מתוך מייל (שלב 4-5).
 * ⚠️ אינה נשמרת: הטופס נפתח מלא מראש, והמשימה נוצרת רק בלחיצה על "שמור".
 */
export interface TaskDraft {
  title: string;
  due_date: string | null;
  // לפי כתובת השולח מול כרטיסי הלקוחות. נקבע בשרת ולא במודל
  client_id: number | null;
  notes: string;
  email_message_id: string;
}

/** הצעת ניסוח לתשובה. ⚠️ אינה נשלחת — המשתמש עורך, מאשר ושולח */
export interface ReplyOption {
  label: string;
  text: string;
}

export interface ReplyDraft {
  // ⚠️ נגזר בשרת מהמייל המקורי, ואינו ניתן לעריכה במסך
  to: string;
  subject: string;
  options: ReplyOption[];
  // מתי ההצעות הוכנו, כשהוכנו מראש. null = נוסחו עכשיו
  prepared_at: string | null;
}

export interface ReplySent {
  to: string;
  subject: string;
  // ⚠️ השליחה הצליחה גם אם זה false. את המייל אי אפשר להחזיר
  archived: boolean;
}

/* --- מסך היומן (4ב-4). ⚠️ קריאה בלבד: אין כאן טיפוס קלט אחד --- */

/**
 * התצוגות שהמסך מציע, כמו ביומן גוגל.
 * ⚠️ אינן נשלחות לשרת — השרת מקבל `start` ו-`days`, והמרת התצוגה לטווח
 * נעשית כאן. שבוע שאינו השבוע הזה אינו "scope", ולכן אין מה לשלוח.
 */
export type CalendarView = "day" | "week" | "schedule";

export const CALENDAR_VIEW_LABELS: Record<CalendarView, string> = {
  day: "יום",
  week: "שבוע",
  schedule: "לוח זמנים",
};

/** יומן אחד שנקרא, למקרא ולצביעה. ⚠️ הצבע נקבע לפי `id` ולא לפי השם */
export interface CalendarRef {
  id: string;
  name: string;
  primary: boolean;
}

/**
 * אירוע אחד בלוח.
 * ⚠️ אינו נשמר בשום מקום: נקרא מגוגל ברגע הבקשה, מוצג, ונזרק.
 * ⚠️ אין כאן שום שדה שמודל כתב — שעה וכותרת הן עובדות מהיומן.
 */
export interface CalendarEvent {
  id: string;
  title: string;
  calendar: string;
  calendar_id: string;
  // ⚠️ שם היומן מוצג רק כשזה false. אירוע משפחתי או חג שנראה כמו
  // פגישת עבודה מרוקן את ההכרעה לקרוא גם אותם
  from_primary: boolean;
  // ⚠️ אירוע של כל היום אין לו שעה: `day` מלא ו-`start` ריק
  all_day: boolean;
  start: string | null;
  end: string | null;
  day: string | null;
  location: string;
  attendees: string[];
}

export interface CalendarData {
  start: string;
  days: number;
  // ⚠️ נקבע בשרת, בשעון ישראל. דפדפן באזור זמן אחר היה מדגיש את
  // העמודה הלא נכונה
  today: string;
  calendars: CalendarRef[];
  events: CalendarEvent[];
}

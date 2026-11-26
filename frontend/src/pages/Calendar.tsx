import { type CSSProperties, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, query } from "../api";
import EventForm from "../components/EventForm";
import Modal from "../components/Modal";
import {
  dayKey,
  dayName,
  formatTime,
  fromDateValue,
  minutesOfDay,
  toDateValue,
  weekStart,
} from "../format";
import {
  CALENDAR_VIEW_LABELS,
  type CalendarData,
  type CalendarEvent,
  type CalendarPerson,
  type CalendarView,
  type EventDraft,
} from "../types";

/**
 * מסך היומן — קריאה בלבד (שלב 4ב-4).
 *
 * ⚠️ **אין כאן שום פעולה.** לא קביעה, לא עריכה ולא מחיקה: ההכרעה
 * מ-25.11.2026 היא קריאה בלבד, ו-`gcal.py` אוסר PATCH ו-PUT מתוך
 * שיקול — שינוי אירוע שהמערכת לא יצרה עלול לדרוס פגישה. קביעת פגישה
 * נעשית בבוט (4ב-2).
 *
 * ⚠️ **המסך אינו מחליף את הבוט אלא מוסיף לו.** "מה יש לי מחר" נשאר
 * התשובה הנוחה; מה שהבוט אינו יכול לתת הוא תמונת שבוע שרואים בבת אחת,
 * עם החורים בין הפגישות — וזאת הסיבה שהתצוגה הראשית היא לוח ולא רשימה.
 */

/** כמה ימים כל תצוגה שולפת. ⚠️ השרת מקבל `start`+`days` ולא שם תצוגה */
const SPAN: Record<CalendarView, number> = { day: 1, week: 7, schedule: 14 };

/**
 * גובה שעה בפיקסלים בלוח. ⚠️ פגישה של חצי שעה חייבת להישאר קריאה,
 * ולכן לא פחות מזה — 48 פיקסלים לשעה נותנים 24 לחצי שעה.
 */
const HOUR_PX = 48;

/**
 * גבולות ברירת המחדל של הלוח.
 * ⚠️ **הם מינימום ולא תקרה:** פגישה ב-06:30 או ב-22:00 מרחיבה את הלוח
 * ואינה נחתכת ממנו. לוח שמתחיל בחצות הוא שתי שעות ריקות בראש המסך,
 * ולוח שנגמר ב-19:00 מעלים פגישת ערב — והשני הוא הכשל היחיד שאסור.
 */
const FROM_HOUR = 7;
const TO_HOUR = 21;

/** מתחת לזה הלוח צר מדי וגוגל עצמה עוברת לרשימה */
const NARROW = 720;

/** כמה דקות אירוע תופס בלוח גם כשהוא קצר יותר, כדי שיישאר נקרא */
const MIN_SLOT = 25;

/** לאיזה רבע שעה גרירה ולחיצה על משבצת ריקה מתיישרות */
const SNAP = 15;

/** אורך ברירת מחדל לפגישה חדשה. ⚠️ נמדד ביומן האמיתי: 11 מתוך 17 בנות שעה */
const DEFAULT_MINUTES = 60;

/** כמה פיקסלים צריך לזוז כדי שזאת תהיה גרירה ולא לחיצה */
const DRAG_START = 5;

/** "HH:MM" מדקות מתחילת היום, לשדה `type="time"` */
function clock(minutes: number): string {
  const whole = Math.max(0, Math.min(24 * 60 - 1, Math.round(minutes)));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

type Placed = { event: CalendarEvent; lane: number; lanes: number };

/**
 * מסדר אירועים שחופפים זה לזה זה ליד זה.
 *
 * ⚠️ **בלי זה שתי פגישות באותה שעה מצטיירות אחת על השנייה**, והעליונה
 * מסתירה את התחתונה לגמרי — כלומר פגישה נעלמת מהמסך בשקט, וזה הכשל
 * היחיד שאסור. הפתרון: אשכול של אירועים חופפים מתחלק למסלולים, וכל
 * אירוע מקבל את הרוחב של 1/מספר המסלולים באשכול שלו.
 */
function place(events: CalendarEvent[]): Placed[] {
  const out: Placed[] = [];
  let cluster: { event: CalendarEvent; lane: number; ends: number }[] = [];
  let clusterEnds = 0;

  const flush = () => {
    if (!cluster.length) return;
    const lanes = cluster.reduce((most, item) => Math.max(most, item.lane + 1), 1);
    for (const item of cluster) out.push({ event: item.event, lane: item.lane, lanes });
    cluster = [];
    clusterEnds = 0;
  };

  const sorted = [...events].sort((a, b) => (a.start ?? "").localeCompare(b.start ?? ""));
  for (const event of sorted) {
    if (!event.start) continue;
    const begins = new Date(event.start).getTime();
    // ⚠️ אירוע בלי שעת סיום, ואירוע קצר מאוד, מקבלים אורך מינימלי —
    // אחרת הם קו דק שאי אפשר ללחוץ עליו ואי אפשר לקרוא
    const ends = Math.max(
      event.end ? new Date(event.end).getTime() : begins,
      begins + MIN_SLOT * 60000,
    );
    // האשכול נגמר כשאירוע מתחיל אחרי שכל מה שלפניו נגמר
    if (cluster.length && begins >= clusterEnds) flush();
    const busy = new Set(cluster.filter((item) => item.ends > begins).map((item) => item.lane));
    let lane = 0;
    while (busy.has(lane)) lane += 1;
    cluster.push({ event, lane, ends });
    clusterEnds = Math.max(clusterEnds, ends);
  }
  flush();
  return out;
}

export default function Calendar() {
  // ⚠️ בנייד פותחים על "לוח זמנים", בדיוק כמו יומן גוגל: טור ברוחב 14%
  // חותך כל כותרת. הכפתורים נשארים, ולכן זאת ברירת מחדל ולא נעילה
  const [view, setView] = useState<CalendarView>(() =>
    typeof window !== "undefined" && window.innerWidth <= NARROW ? "schedule" : "week",
  );
  // היום שהתצוגה מתייחסת אליו. הדפדוף מזיז אותו, והשרת מקבל טווח
  const [anchor, setAnchor] = useState(() => toDateValue(new Date()));
  const [data, setData] = useState<CalendarData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 503 = צריך לחבר את גוגל בהגדרות. 502 = תקלה, אפשר לנסות שוב
  const [needsConnection, setNeedsConnection] = useState(false);
  const [open, setOpen] = useState<CalendarEvent | null>(null);
  // טופס פגישה: `id` ריק = חדשה, מלא = שינוי של קיימת
  const [form, setForm] = useState<EventDraft | null>(null);
  const [people, setPeople] = useState<CalendarPerson[]>([]);
  const [toast, setToast] = useState("");
  // פגישה שממתינה לאישור מחיקה, והאם למחוק את כל הסדרה
  const [removing, setRemoving] = useState<CalendarEvent | null>(null);
  const [removeSeries, setRemoveSeries] = useState(false);
  const [working, setWorking] = useState(false);
  // האירוע שנגרר כרגע, והאפשרות להחזיר את הגרירה האחרונה
  const [dragging, setDragging] = useState("");
  const [undo, setUndo] = useState<{
    event: CalendarEvent;
    body: { day: string; start_time: string; end_time: string };
  } | null>(null);
  const dragged = useRef(false);

  const days = SPAN[view];
  // בתצוגת שבוע הטווח מתחיל ביום ראשון ולא ביום שנבחר, אחרת הלוח היה
  // מתחיל ביום רביעי וקשה לקרוא אותו
  const start = useMemo(
    () => (view === "week" ? toDateValue(weekStart(fromDateValue(anchor))) : anchor),
    [view, anchor],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    setNeedsConnection(false);
    try {
      setData(await api<CalendarData>(`/calendar${query({ start, days })}`));
    } catch (e) {
      setData(null);
      setNeedsConnection(e instanceof ApiError && e.status === 503);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [start, days]);

  useEffect(() => {
    load();
  }, [load]);

  const move = (step: number) => {
    const next = fromDateValue(anchor);
    next.setDate(next.getDate() + step * days);
    setAnchor(toDateValue(next));
  };

  // ⚠️ הלקוחות נטענים פעם אחת ולא בכל דפדוף: הם אינם תלויים בטווח,
  // ובורר המשתתפים צריך אותם רק כשנפתח טופס
  useEffect(() => {
    api<CalendarPerson[]>("/calendar/people")
      .then(setPeople)
      // ⚠️ כישלון כאן אינו מפיל את המסך: אפשר להקליד כתובת ביד
      .catch(() => setPeople([]));
  }, []);

  /** האם מותר לכתוב ליומן שהאירוע יושב בו */
  const editable = useCallback(
    (event: CalendarEvent) =>
      (data?.calendars ?? []).some((cal) => cal.id === event.calendar_id && cal.writable),
    [data],
  );

  const firstWritable = () =>
    (data?.calendars ?? []).find((cal) => cal.primary && cal.writable)?.id ??
    (data?.calendars ?? []).find((cal) => cal.writable)?.id ??
    "";

  /** טיוטה מאירוע קיים, לפתיחת טופס השינוי */
  const draftOf = (event: CalendarEvent): EventDraft => {
    const begins = new Date(event.start!);
    const minutes = minutesOfDay(begins);
    const ends = event.end ? minutesOfDay(new Date(event.end)) : minutes + DEFAULT_MINUTES;
    return {
      id: event.id,
      title: event.title,
      day: dayKey(begins),
      from: clock(minutes),
      to: clock(ends > minutes ? ends : minutes + DEFAULT_MINUTES),
      calendar_id: event.calendar_id,
      location: event.location,
      description: event.description,
      // ⚠️ `attendees` הם שמות אחרי שכרטיס הלקוח החליף בהם כתובת, ולכן
      // רק מה שנראה ככתובת חוזר לטופס — שם לא היה מזהה אף אחד בגוגל
      attendees: event.attendees.filter((one) => one.includes("@")),
      recurring: event.recurring,
      etag: event.etag,
    };
  };

  /** טיוטה ריקה ליום ולשעה שנלחצו */
  const blankDraft = (dayValue: string, minutes: number): EventDraft => ({
    id: "",
    title: "",
    day: dayValue,
    from: clock(minutes),
    to: clock(minutes + DEFAULT_MINUTES),
    calendar_id: firstWritable(),
    location: "",
    description: "",
    attendees: [],
    recurring: false,
    etag: "",
  });

  const saved = (message: string) => {
    setForm(null);
    setOpen(null);
    setToast(message);
    load();
  };

  /**
   * גרירת פגישה לשעה או ליום אחרים.
   *
   * ⚠️ **היעד נקרא מהעמודה שמתחת לסמן** (`data-day`), ולא מחישוב של
   * רוחב עמודה — בממשק מימין לשמאל חישוב כזה מתהפך, והפגישה הייתה
   * נוחתת ביום המשוקף.
   *
   * ⚠️⚠️ **גרירה שולחת `force`, והטופס לא.** חפיפה ביומן היא מצב
   * לגיטימי — המסך עצמו מצייר פגישות חופפות זו לצד זו — ומי שגורר
   * לשעה תפוסה רואה בדיוק לאן הוא גורר. בטופס, לעומת זאת, השעה
   * מוקלדת והמשתמש אינו רואה מה כבר שם, ולכן שם נשאלת שאלה.
   *
   * ⚠️ **מופע בודד בלבד.** גרירה של פגישה חוזרת מזיזה את המופע הזה,
   * וההודעה אומרת זאת — להזיז סדרה שלמה בגרירה אחת זה בדיוק סוג
   * הפעולה שאי אפשר לשים לב שעשית.
   */
  const startDrag = (e: React.PointerEvent, event: CalendarEvent) => {
    if (!editable(event) || !event.start || event.all_day) return;
    const column = (e.currentTarget as HTMLElement).closest(".cal-col") as HTMLElement | null;
    if (!column) return;
    const began = minutesOfDay(new Date(event.start));
    const ended = event.end ? minutesOfDay(new Date(event.end)) : began + DEFAULT_MINUTES;
    const length = ended > began ? ended - began : DEFAULT_MINUTES;
    const minuteAt = (y: number, box: DOMRect) =>
      fromHour * 60 + ((y - box.top) / box.height) * gridMinutes;
    const grab = minuteAt(e.clientY, column.getBoundingClientRect()) - began;
    let moved = false;

    const onMove = (m: PointerEvent) => {
      if (Math.abs(m.clientY - e.clientY) > DRAG_START || Math.abs(m.clientX - e.clientX) > DRAG_START) {
        moved = true;
        setDragging(event.id);
      }
    };
    const onUp = async (u: PointerEvent) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      setDragging("");
      if (!moved) return;
      // ⚠️ הלחיצה מגיעה אחרי ה-pointerup, ובלי הדגל הזה כל גרירה
      // הייתה גם פותחת את חלון הפרטים
      dragged.current = true;
      const under = (document.elementFromPoint(u.clientX, u.clientY) as HTMLElement | null)
        ?.closest(".cal-col") as HTMLElement | null;
      const landed = under ?? column;
      const dayValue = landed.dataset.day ?? dayKey(new Date(event.start!));
      const raw = minuteAt(u.clientY, landed.getBoundingClientRect()) - grab;
      const from = Math.max(0, Math.round(raw / SNAP) * SNAP);
      if (dayValue === dayKey(new Date(event.start!)) && from === began) return;
      const was = {
        day: dayKey(new Date(event.start!)),
        start_time: clock(began),
        end_time: clock(began + length),
      };
      const now = { day: dayValue, start_time: clock(from), end_time: clock(from + length) };
      try {
        await api(`/calendar/events/${encodeURIComponent(event.id)}`, {
          method: "PATCH",
          body: { ...now, calendar_id: event.calendar_id, etag: event.etag, force: true },
        });
        setUndo({ event, body: was });
        setToast(
          event.recurring
            ? `הפגישה הזאת הוזזה ל-${now.start_time} (רק המופע הזה)`
            : `הפגישה הוזזה ל-${now.start_time}`,
        );
        load();
      } catch (err) {
        setToast((err as Error).message);
        load();
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  /** מחזיר פגישה שנגררה למקום שממנו באה */
  const undoDrag = async () => {
    if (!undo) return;
    const { event, body } = undo;
    setUndo(null);
    try {
      await api(`/calendar/events/${encodeURIComponent(event.id)}`, {
        method: "PATCH",
        body: { ...body, calendar_id: event.calendar_id, force: true },
      });
      setToast("הוחזר");
    } catch (e) {
      setToast((e as Error).message);
    }
    load();
  };

  const remove = async () => {
    if (!removing) return;
    setWorking(true);
    try {
      await api(
        `/calendar/events/${encodeURIComponent(removing.id)}${query({
          calendar_id: removing.calendar_id,
          whole_series: removeSeries,
          // ⚠️ הודעת ביטול יוצאת רק כשהיו משתתפים. ההזמנה שכבר נשלחה
          // אינה נמחקת מהתיבה שלהם, אבל היא מסומנת כמבוטלת
          notify: removing.attendees.length > 0,
        })}`,
        { method: "DELETE" },
      );
      setRemoving(null);
      saved(removeSeries ? "כל הסדרה בוטלה" : "הפגישה בוטלה");
    } catch (e) {
      setRemoving(null);
      setToast((e as Error).message);
    } finally {
      setWorking(false);
    }
  };

  /**
   * הימים שהתצוגה מציגה.
   *
   * ⚠️⚠️ **אלה תאריכים ולא נקודות זמן, וזה ההבדל שקובע איזו עמודה
   * תתאים לאיזה אירוע.** עמודה מזוהה ב-`toDateValue` (אותו תאריך שבנינו
   * ממנה, בלי להמיר אזור זמן), ואילו אירוע מזוהה ב-`dayKey` (נקודת זמן
   * ← התאריך שלה בשעון ישראל). להחליף ביניהם היה מזיז את כל הלוח ביום
   * שלם בכל דפדפן שממזרח לישראל — ובמשרד זה נראה תקין לגמרי.
   */
  const dates = useMemo(() => {
    const first = fromDateValue(start);
    return Array.from({ length: days }, (_, index) => {
      const day = new Date(first);
      day.setDate(day.getDate() + index);
      return day;
    });
  }, [start, days]);

  const events = data?.events ?? [];
  const today = data?.today ?? "";

  // ⚠️ אירוע מתוייק לפי היום **בשעון ישראל** ולא לפי שעון הדפדפן.
  // פגישה ב-00:30 הייתה יושבת ביום הלא נכון בכל דפדפן אחר
  const byDay = useMemo(() => {
    const map = new Map<string, { timed: CalendarEvent[]; allDay: CalendarEvent[] }>();
    const slot = (key: string) => {
      if (!map.has(key)) map.set(key, { timed: [], allDay: [] });
      return map.get(key)!;
    };
    for (const event of events) {
      if (event.all_day) {
        if (event.day) slot(event.day).allDay.push(event);
      } else if (event.start) {
        slot(dayKey(new Date(event.start))).timed.push(event);
      }
    }
    return map;
  }, [events]);

  // ⚠️ הגבולות נגזרים מהאירועים ולא קבועים: פגישה ב-06:30 מרחיבה את
  // הלוח, ואינה נחתכת ממנו
  const [fromHour, toHour] = useMemo(() => {
    let first = FROM_HOUR;
    let last = TO_HOUR;
    for (const event of events) {
      if (event.all_day || !event.start) continue;
      first = Math.min(first, Math.floor(minutesOfDay(new Date(event.start)) / 60));
      const ends = event.end ? minutesOfDay(new Date(event.end)) : 0;
      // אירוע שנגמר אחרי חצות חוזר לדקה קטנה, ולכן הוא אינו מרחיב
      if (ends > 0) last = Math.max(last, Math.ceil(ends / 60));
    }
    return [Math.max(0, first), Math.min(24, Math.max(last, first + 1))];
  }, [events]);

  const gridMinutes = (toHour - fromHour) * 60;
  const hours = Array.from({ length: toHour - fromHour }, (_, index) => fromHour + index);

  /** המיקום של אירוע בעמודה, באחוזים. מקוצץ לגבולות הלוח */
  const box = (event: CalendarEvent) => {
    const begins = minutesOfDay(new Date(event.start!));
    const raw = event.end ? minutesOfDay(new Date(event.end)) : begins + MIN_SLOT;
    // ⚠️ אירוע שעובר חצות חוזר למספר קטן, ולכן הוא נמתח עד סוף הלוח
    const ends = raw > begins ? raw : toHour * 60;
    const top = ((begins - fromHour * 60) / gridMinutes) * 100;
    const height = ((Math.max(ends, begins + MIN_SLOT) - begins) / gridMinutes) * 100;
    return {
      top: `${Math.max(0, top)}%`,
      height: `${Math.min(100 - Math.max(0, top), height)}%`,
    };
  };

  /**
   * צבע לפי היומן. ⚠️ **לפי המזהה ולא לפי השם**: שם יומן הוא טקסט
   * שאפשר לשנות בגוגל, והסדר שהשרת מחזיר קבוע (הראשי קודם, ואז לפי שם)
   * ולכן אותו יומן מקבל אותו צבע בכל טעינה.
   */
  const tone = (event: CalendarEvent) => {
    const index = (data?.calendars ?? []).findIndex((cal) => cal.id === event.calendar_id);
    return `c${(index < 0 ? 0 : index) % 6}`;
  };

  const heading = (day: Date) => {
    const key = toDateValue(day);
    if (key === today) return "היום";
    return `יום ${dayName(day)}`;
  };

  const label = (day: Date) => `${String(day.getDate()).padStart(2, "0")}/${String(day.getMonth() + 1).padStart(2, "0")}`;

  const range = () => {
    if (view === "day") return `יום ${dayName(dates[0])}, ${label(dates[0])}`;
    return `${label(dates[0])} – ${label(dates[dates.length - 1])}`;
  };

  /** קו "עכשיו", רק כשהיום מוצג ורק בתוך גבולות הלוח */
  const nowTop = () => {
    if (!today || !dates.some((day) => toDateValue(day) === today)) return null;
    const minutes = minutesOfDay(new Date());
    if (minutes < fromHour * 60 || minutes > toHour * 60) return null;
    return `${((minutes - fromHour * 60) / gridMinutes) * 100}%`;
  };

  const chip = (event: CalendarEvent) => (
    <button
      key={event.id}
      className={`cal-chip ${tone(event)}`}
      onClick={() => setOpen(event)}
      title={event.title}
    >
      {event.title}
    </button>
  );

  const anyAllDay = dates.some((day) => (byDay.get(toDateValue(day))?.allDay.length ?? 0) > 0);

  // התאריך של האירוע שפתוח בחלון, לקישור ליומן גוגל
  const openDay =
    open && (open.all_day && open.day ? fromDateValue(open.day) : new Date(open.start!));

  return (
    <div>
      <h1>יומן</h1>
      <p className="muted">
        הפגישות מהיומן הראשי, מהיומן המשפחתי, מחדר הישיבות ומהחגים. אפשר לקבוע פגישה, לגרור
        אותה לשעה אחרת, לשנות ולמחוק — ⚠️ חוץ מחדר הישיבות והחגים, שהם לקריאה בלבד. ⚠️ שום
        תוכן יומן אינו נשמר — הוא נקרא מגוגל ברגע שאתה פותח את המסך.
      </p>

      <div className="toolbar">
        {/* ⚠️ מילים ולא חצים: בממשק מימין לשמאל חץ "קדימה" מצביע לכיוון
            ההפוך ממה שמצפים, וטעות כזאת מבלבלת בכל לחיצה */}
        <button onClick={() => move(-1)} disabled={loading}>
          הקודם
        </button>
        <button onClick={() => setAnchor(toDateValue(new Date()))} disabled={loading}>
          היום
        </button>
        <button onClick={() => move(1)} disabled={loading}>
          הבא
        </button>
        <span className="cal-range">{range()}</span>
        {/* ⚠️ הכפתור מופיע רק כשיש יומן שמותר לכתוב אליו. חדר הישיבות
            והחגים הם reader, ולחיצה עליהם הייתה מחזירה 403 מגוגל */}
        {firstWritable() && (
          <button
            className="primary"
            onClick={() => setForm(blankDraft(today || toDateValue(new Date()), 9 * 60))}
          >
            פגישה חדשה
          </button>
        )}
        <button className="link-btn" onClick={load} disabled={loading}>
          רענון
        </button>
      </div>

      {/* הודעה אחרי פעולה, עם החזרה של הגרירה האחרונה */}
      {toast && (
        <div className="card cal-toast">
          <span>{toast}</span>
          {undo && (
            <button className="link-btn" onClick={undoDrag}>
              ביטול
            </button>
          )}
          <button className="link-btn" onClick={() => { setToast(""); setUndo(null); }}>
            סגירה
          </button>
        </div>
      )}

      {/* התצוגות. ⚠️ החלפה אינה פונה לגוגל כשהטווח לא השתנה */}
      <div className="when-tabs" role="tablist" aria-label="תצוגה">
        {(Object.keys(CALENDAR_VIEW_LABELS) as CalendarView[]).map((option) => (
          <button
            key={option}
            role="tab"
            aria-selected={view === option}
            className={view === option ? "on" : ""}
            onClick={() => setView(option)}
          >
            {CALENDAR_VIEW_LABELS[option]}
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
      ) : loading && !data ? (
        <div className="card muted">טוען את היומן…</div>
      ) : view === "schedule" ? (
        /* --- לוח זמנים: רשימה מקובצת לפי יום, כמו בנייד של גוגל --- */
        <>
          {events.length === 0 ? (
            <div className="card muted">
              אין כלום ביומן מ-{label(dates[0])} עד {label(dates[dates.length - 1])}.
            </div>
          ) : (
            <div className="cal-agenda">
              {dates.map((day) => {
                const key = toDateValue(day);
                const slot = byDay.get(key);
                const all = [...(slot?.allDay ?? []), ...(slot?.timed ?? [])];
                // ⚠️ יום ריק אינו מוצג. בשבועיים יש בדרך כלל חמישה
                // ימים ריקים, והם היו דוחקים את מה שכן יש מחוץ למסך
                if (all.length === 0) return null;
                return (
                  <div key={key} className="cal-day">
                    <h2 className={key === today ? "cal-day-head on" : "cal-day-head"}>
                      {heading(day)}, {label(day)}
                    </h2>
                    <ul className="task-list">
                      {all.map((event) => (
                        <li key={event.id}>
                          <div className="card clickable cal-row" onClick={() => setOpen(event)}>
                            <span className={`cal-dot ${tone(event)}`} aria-hidden="true" />
                            <span className="cal-time">
                              {event.all_day
                                ? "כל היום"
                                : event.end
                                  ? `${formatTime(event.start!)}–${formatTime(event.end)}`
                                  : formatTime(event.start!)}
                            </span>
                            <span className="cal-title">{event.title}</span>
                            <span className="task-meta cal-extra">
                              {/* ⚠️ שם היומן רק כשאינו הראשי: אירוע
                                  משפחתי או חג שנראה כמו פגישת עבודה
                                  מרוקן את ההכרעה לקרוא גם אותם */}
                              {!event.from_primary && <span className="pill">{event.calendar}</span>}
                              {event.location && <span>{event.location}</span>}
                              {event.attendees.length === 1 && <span>עם {event.attendees[0]}</span>}
                              {event.attendees.length > 1 && (
                                <span>{event.attendees.length} משתתפים</span>
                              )}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}
        </>
      ) : (
        /* --- לוח: עמודה לכל יום, אירועים ממוקמים לפי השעה --- */
        <div className="cal-grid-wrap">
          {/* ⚠️ כמחרוזת ולא כמספר: `repeat(7, …)` ב-CSS, ולא `repeat(7px, …)` */}
          <div className="cal-grid" style={{ "--cal-days": String(days) } as CSSProperties}>
            <div className="cal-corner" />
            {dates.map((day) => (
              <div
                key={`head-${toDateValue(day)}`}
                className={toDateValue(day) === today ? "cal-head on" : "cal-head"}
              >
                <span className="cal-head-name">{dayName(day)}</span>
                <span className="cal-head-date">{label(day)}</span>
              </div>
            ))}

            {/* ⚠️ אירוע של כל היום בפס נפרד מעל הלוח, ולא בשעה 00:00.
                חג בראש העמודה נראה אחרת כמו פגישה בחצות */}
            {anyAllDay && (
              <>
                <div className="cal-gutter cal-allday-label">כל היום</div>
                {dates.map((day) => (
                  <div key={`all-${toDateValue(day)}`} className="cal-allday">
                    {(byDay.get(toDateValue(day))?.allDay ?? []).map(chip)}
                  </div>
                ))}
              </>
            )}

            {/* ⚠️ ``HOUR_PX`` הוא המקור היחיד לגובה: גם הסרגל וגם
                העמודות מקבלים ממנו את הגובה, אחרת מספר בקוד ומספר
                ב-CSS היו נפרדים בשקט והשעות היו מצביעות על המקום הלא
                נכון */}
            <div
              className="cal-gutter cal-hours"
              style={{ height: `${hours.length * HOUR_PX}px` }}
            >
              {hours.map((hour) => (
                <div key={hour} className="cal-hour">
                  <span>{String(hour).padStart(2, "0")}:00</span>
                </div>
              ))}
            </div>

            {dates.map((day) => {
              const key = toDateValue(day);
              const placed = place(byDay.get(key)?.timed ?? []);
              const line = key === today ? nowTop() : null;
              return (
                <div
                  key={`col-${key}`}
                  data-day={key}
                  className={key === today ? "cal-col on" : "cal-col"}
                  style={{ height: `${hours.length * HOUR_PX}px` }}
                  /* ⚠️ רק לחיצה על משבצת ריקה פותחת פגישה חדשה: לחיצה
                     על אירוע מגיעה לכאן בבועה, ובלי הבדיקה כל פתיחה של
                     פגישה קיימת הייתה גם פותחת טופס חדש מתחתיה */
                  onClick={(e) => {
                    const slot = e.target as HTMLElement;
                    if (!slot.classList.contains("cal-slot") || !firstWritable()) return;
                    const box = e.currentTarget.getBoundingClientRect();
                    const at = fromHour * 60 + ((e.clientY - box.top) / box.height) * gridMinutes;
                    setForm(blankDraft(key, Math.round(at / SNAP) * SNAP));
                  }}
                >
                  {hours.map((hour) => (
                    <div key={hour} className="cal-slot" />
                  ))}
                  {line && <div className="cal-now" style={{ top: line }} />}
                  {placed.map(({ event, lane, lanes }) => (
                    <button
                      key={event.id}
                      className={`cal-event ${tone(event)}${
                        dragging === event.id ? " dragging" : ""
                      }${editable(event) ? " movable" : ""}`}
                      onPointerDown={(e) => startDrag(e, event)}
                      onClick={() => {
                        if (dragged.current) {
                          dragged.current = false;
                          return;
                        }
                        setOpen(event);
                      }}
                      style={{
                        ...box(event),
                        // ⚠️ מימין לשמאל: ההיסט נמדד מימין, כי העמודה
                        // מתחילה שם — אחרת פגישות חופפות היו נדחסות
                        // לכיוון ההפוך מהכותרת שלהן
                        insetInlineStart: `${(lane / lanes) * 100}%`,
                        width: `${100 / lanes}%`,
                      }}
                    >
                      <span className="cal-event-time">{formatTime(event.start!)}</span>
                      <span className="cal-event-title">{event.title}</span>
                    </button>
                  ))}
                </div>
              );
            })}
          </div>
          {events.length === 0 && (
            <p className="muted">אין כלום ביומן ב{view === "day" ? "יום הזה" : "שבוע הזה"}.</p>
          )}
        </div>
      )}

      {/* מקרא היומנים. ⚠️ בלעדיו הצבעים הם קוד שאין לו מפתח */}
      {data && data.calendars.length > 1 && (
        <div className="cal-legend">
          {data.calendars.map((cal, index) => (
            <span key={cal.id} className="cal-legend-item">
              <span className={`cal-dot c${index % 6}`} aria-hidden="true" />
              {cal.name}
            </span>
          ))}
        </div>
      )}

      {open && (
        <Modal title={open.title} onClose={() => setOpen(null)}>
          <div className="details">
            <div className="task-meta">
              <span>
                {open.all_day
                  ? "כל היום"
                  : open.end
                    ? `${formatTime(open.start!)}–${formatTime(open.end)}`
                    : formatTime(open.start!)}
              </span>
              <span>{openDay && `יום ${dayName(openDay)}, ${label(openDay)}`}</span>
              {/* ⚠️ שם היומן רק כשאינו הראשי, בדיוק כמו בלוח וברשימה.
                  על היומן הראשי התווית הייתה כתובת המייל של המשתמש —
                  כלומר רעש שנראה כמו מידע, ונתפס באימות של 26.11.2026 */}
              {!open.from_primary && <span className="pill">{open.calendar}</span>}
            </div>
            {open.location && (
              <p>
                <strong>מקום:</strong> {open.location}
              </p>
            )}
            {open.attendees.length > 0 && (
              <p>
                <strong>משתתפים:</strong> {open.attendees.join(" · ")}
              </p>
            )}
            {/* ⚠️ קישור ליום ביומן גוגל ולא לאירוע עצמו: כתובת של אירוע
                בודד בנויה מקידוד של המזהה ושל היומן ונשברת בלי להודיע,
                וכתובת של יום עובדת תמיד */}
            {open.description && <p className="pre-line">{open.description}</p>}

            {/* ⚠️ כפתורי השינוי רק על יומן שמותר לכתוב אליו. חדר
                הישיבות והחגים הם reader, והשרת גם הוא פוסל אותם — זה
                אינו נשען על כך שהכפתור הוסתר */}
            {editable(open) && !open.all_day && (
              <div className="row">
                <button className="primary" onClick={() => setForm(draftOf(open))}>
                  שינוי
                </button>
                <button
                  className="danger"
                  onClick={() => {
                    setRemoveSeries(false);
                    setRemoving(open);
                  }}
                >
                  מחיקה
                </button>
              </div>
            )}

            <p className="muted">
              אפשר גם{" "}
              <a
                href={
                  openDay
                    ? `https://calendar.google.com/calendar/r/day/${openDay.getFullYear()}/${openDay.getMonth() + 1}/${openDay.getDate()}`
                    : "https://calendar.google.com/calendar/r"
                }
                target="_blank"
                rel="noreferrer"
              >
                לפתוח את היום ביומן גוגל
              </a>
              .
            </p>
          </div>
        </Modal>
      )}

      {form && (
        <EventForm
          draft={form}
          calendars={data?.calendars ?? []}
          people={people}
          onClose={() => setForm(null)}
          onSaved={saved}
        />
      )}

      {removing && (
        <Modal title="לבטל את הפגישה?" onClose={() => setRemoving(null)}>
          <div className="details">
            <p>
              <strong>{removing.title}</strong>
              {removing.start && ` · ${formatTime(removing.start)}`}
            </p>
            {/* ⚠️⚠️ אותה שאלה כמו בשינוי, ומאותה סיבה: כמעט כל הפגישות
                ביומן האמיתי חוזרות, ומחיקת סדרה נוגעת גם בפגישות שלא
                נראו על המסך */}
            {removing.recurring && (
              <fieldset className="scope">
                <legend>הפגישה הזאת חוזרת. מה למחוק?</legend>
                <label className="inline">
                  <input
                    type="radio"
                    checked={!removeSeries}
                    onChange={() => setRemoveSeries(false)}
                  />
                  רק הפגישה הזאת
                </label>
                <label className="inline">
                  <input
                    type="radio"
                    checked={removeSeries}
                    onChange={() => setRemoveSeries(true)}
                  />
                  כל הסדרה
                </label>
              </fieldset>
            )}
            {removing.attendees.length > 0 && (
              <p className="warn">
                ⚠️ למשתתפים תישלח הודעת ביטול. ההזמנה שכבר קיבלו אינה נמחקת מהתיבה שלהם.
              </p>
            )}
            <div className="row">
              <button className="danger" onClick={remove} disabled={working}>
                {working ? "מוחק…" : "מחיקה"}
              </button>
              <button onClick={() => setRemoving(null)} disabled={working}>
                חזרה
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

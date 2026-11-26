import { useEffect, useMemo, useState } from "react";
import { ApiError, api } from "../api";
import type { CalendarPerson, CalendarRef, EventDraft } from "../types";
import Modal from "./Modal";

/**
 * טופס פגישה — יצירה ושינוי (נוסף 26.11.2026).
 *
 * ⚠️⚠️ **זימון משתתפים הוא הפעולה היחידה כאן שאי אפשר לבטל.** גוגל
 * שולחת את ההזמנה **בשם המשתמש**, ומחיקת האירוע אינה מוציאה אותה
 * מהתיבה של הנמען. לכן הסימון לבדו אינו מספיק: לחיצה על "שמור" עם
 * משתתפים מציגה **מסך אישור** עם הכתובות המלאות, כמו בשליחת מייל
 * ב-4-4 — ובלי האישור הפגישה נקבעת והמשתתפים מתווספים **בלי שנשלח
 * להם דבר**.
 *
 * ⚠️ **השעה נשלחת כשעת קיר (`day`, `start_time`, `end_time`) ולא
 * כנקודת זמן.** ההרכבה נעשית בשרת, שמחזיק את `Asia/Jerusalem` — אחרת
 * פגישה שנקבעת ממחשב באזור זמן אחר הייתה נשמרת בשעה הלא נכונה בשקט.
 */
export default function EventForm({
  draft,
  calendars,
  people,
  onClose,
  onSaved,
}: {
  draft: EventDraft;
  calendars: CalendarRef[];
  people: CalendarPerson[];
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const editing = Boolean(draft.id);
  const [title, setTitle] = useState(draft.title);
  const [day, setDay] = useState(draft.day);
  const [from, setFrom] = useState(draft.from);
  const [to, setTo] = useState(draft.to);
  const [calendarId, setCalendarId] = useState(draft.calendar_id);
  const [location, setLocation] = useState(draft.location);
  const [description, setDescription] = useState(draft.description);
  const [guests, setGuests] = useState<string[]>(draft.attendees);
  const [typed, setTyped] = useState("");
  const [notify, setNotify] = useState(false);
  // ⚠️ ברירת המחדל היא המופע הבודד — הפחות הרסנית מבין השתיים
  const [series, setSeries] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [saving, setSaving] = useState(false);

  // משתתף שהוסר מבטל את ההזמנה: אין למי לשלוח
  useEffect(() => {
    if (!guests.length && notify) setNotify(false);
  }, [guests, notify]);

  const writable = useMemo(() => calendars.filter((cal) => cal.writable), [calendars]);

  const addGuest = (address: string) => {
    const clean = address.trim().toLowerCase();
    // ⚠️ `.trim()` ולא רק בדיקת אמת: מחרוזת של רווחים היא אמת, והיא
    // הייתה נכנסת לרשימה ומדליקה את ההזמנה
    if (!clean || guests.includes(clean)) return;
    setGuests([...guests, clean]);
    setTyped("");
  };

  const save = async (force: boolean) => {
    setSaving(true);
    setError("");
    setBusy("");
    const shared = {
      title: title.trim(),
      day,
      start_time: from,
      end_time: to,
      location: location.trim(),
      description: description.trim(),
      attendees: guests,
      notify,
      force,
    };
    try {
      if (editing) {
        await api(`/calendar/events/${encodeURIComponent(draft.id)}`, {
          method: "PATCH",
          body: {
            ...shared,
            calendar_id: draft.calendar_id,
            whole_series: series,
            // ⚠️ ה-etag שייך למופע; כששומרים על כל הסדרה הוא אינו נשלח
            etag: series ? "" : draft.etag,
          },
        });
      } else {
        await api("/calendar/events", {
          method: "POST",
          body: { ...shared, calendar_id: calendarId },
        });
      }
      onSaved(
        editing
          ? series
            ? "כל הסדרה עודכנה"
            : "הפגישה עודכנה"
          : notify && guests.length
            ? "הפגישה נקבעה וההזמנה נשלחה"
            : "הפגישה נקבעה",
      );
    } catch (e) {
      setConfirming(false);
      if (e instanceof ApiError && e.status === 409) setBusy(e.message);
      else setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const submit = () => {
    if (!title.trim()) {
      setError("צריך כותרת");
      return;
    }
    if (to <= from) {
      setError("הסיום צריך להיות אחרי ההתחלה");
      return;
    }
    // ⚠️ מסך אישור לפני שליחה, ולא רק סימון: זאת הפעולה היחידה
    // שאינה הפיכה
    if (notify && guests.length) {
      setConfirming(true);
      return;
    }
    save(false);
  };

  if (confirming) {
    return (
      <Modal title="לשלוח הזמנה?" onClose={() => setConfirming(false)}>
        <div className="details">
          <p>
            ההזמנה תישלח <strong>בשמך</strong> אל:
          </p>
          <ul className="plain-list">
            {guests.map((address) => (
              <li key={address}>{address}</li>
            ))}
          </ul>
          <p className="warn">
            ⚠️ אי אפשר לבטל שליחה. גם אם תמחק את הפגישה אחר כך, ההזמנה כבר תהיה בתיבה שלהם
            (הם יקבלו הודעת ביטול).
          </p>
          <div className="row">
            <button className="primary" onClick={() => save(false)} disabled={saving}>
              {saving ? "שולח…" : "שלח וקבע"}
            </button>
            <button onClick={() => setConfirming(false)} disabled={saving}>
              חזרה
            </button>
          </div>
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={editing ? "שינוי פגישה" : "פגישה חדשה"} onClose={onClose}>
      <div className="details form">
        <label>
          כותרת
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
        </label>

        <div className="row">
          <label>
            תאריך
            <input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
          </label>
          <label>
            משעה
            <input type="time" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label>
            עד
            <input type="time" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
        </div>

        {!editing && writable.length > 1 && (
          <label>
            יומן
            <select value={calendarId} onChange={(e) => setCalendarId(e.target.value)}>
              {writable.map((cal) => (
                <option key={cal.id} value={cal.id}>
                  {cal.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {/* ⚠️⚠️ כמעט כל הפגישות ביומן האמיתי חוזרות, ולכן זאת השאלה
            הראשונה ולא מקרה קצה */}
        {editing && draft.recurring && (
          <fieldset className="scope">
            <legend>הפגישה הזאת חוזרת. מה לשנות?</legend>
            <label className="inline">
              <input type="radio" checked={!series} onChange={() => setSeries(false)} />
              רק הפגישה הזאת
            </label>
            <label className="inline">
              <input type="radio" checked={series} onChange={() => setSeries(true)} />
              כל הסדרה
            </label>
          </fieldset>
        )}

        <label>
          מקום
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>

        <label>
          הערות
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <div className="guests">
          <span className="field-label">משתתפים</span>
          {guests.length > 0 && (
            <div className="chips">
              {guests.map((address) => (
                <button
                  key={address}
                  className="chip"
                  onClick={() => setGuests(guests.filter((one) => one !== address))}
                  title="הסרה"
                >
                  {address} ✕
                </button>
              ))}
            </div>
          )}
          <div className="row">
            {/* ⚠️ אלה הלקוחות מהמסד ולא אנשי הקשר של גוגל: אוטוקומפליט
                אמיתי דורש הרשאה חדשה ומסך אישור נוסף */}
            {people.length > 0 && (
              <select value="" onChange={(e) => e.target.value && addGuest(e.target.value)}>
                <option value="">מהלקוחות…</option>
                {people.map((person) => (
                  <option key={person.email} value={person.email}>
                    {person.name}
                  </option>
                ))}
              </select>
            )}
            <input
              placeholder="או כתובת מייל"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addGuest(typed);
                }
              }}
            />
            <button onClick={() => addGuest(typed)} disabled={!typed.trim()}>
              הוספה
            </button>
          </div>
          {guests.length > 0 && (
            <label className="inline">
              <input
                type="checkbox"
                checked={notify}
                onChange={(e) => setNotify(e.target.checked)}
              />
              לשלוח להם הזמנה במייל
            </label>
          )}
        </div>

        {busy && (
          <div className="warn">
            {busy}.{" "}
            <button className="link-btn" onClick={() => save(true)} disabled={saving}>
              לקבוע בכל זאת
            </button>
          </div>
        )}
        {error && <p className="error">{error}</p>}

        <div className="row">
          <button className="primary" onClick={submit} disabled={saving}>
            {saving ? "שומר…" : "שמירה"}
          </button>
          <button onClick={onClose} disabled={saving}>
            ביטול
          </button>
        </div>
      </div>
    </Modal>
  );
}

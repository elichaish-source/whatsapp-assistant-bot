import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { formatDateTime } from "../format";
import { GOOGLE_RESULTS, type GoogleStatus } from "../types";

/** ההרשאות המבוקשות, בעברית. לפי הסוף של כתובת ההרשאה */
const SCOPE_LABELS: Record<string, string> = {
  "gmail.modify": "מייל: קריאה, ארכוב ושליחה",
  "calendar.events": "יומן: יצירה ושינוי של אירועים",
  "calendar.readonly": "יומן: קריאה",
};

function scopeLabel(scope: string): string {
  const key = scope.split("/").pop() ?? scope;
  return SCOPE_LABELS[key] ?? key;
}

export default function GoogleConnection() {
  const [status, setStatus] = useState<GoogleStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [params, setParams] = useSearchParams();

  // ההודעה שכתובת החזרה של גוגל השאירה. נקראת פעם אחת ואז יורדת
  // מהכתובת, כדי שרענון של הדף לא יציג אותה שוב
  const result = params.get("google");
  useEffect(() => {
    if (!result) return;
    const next = new URLSearchParams(params);
    next.delete("google");
    setParams(next, { replace: true });
  }, [result]);

  const load = useCallback(async () => {
    try {
      setStatus(await api<GoogleStatus>("/google/status"));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (fn: () => Promise<unknown>) => {
    setError("");
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const connect = () =>
    run(async () => {
      const { url } = await api<{ url: string }>("/google/connect", { method: "POST" });
      // ניווט מלא ולא fetch: מסך האישור של גוגל הוא דף שלם
      window.location.href = url;
    });

  const disconnect = () => {
    if (!confirm("לנתק את גוגל? הבוט יפסיק לראות את המייל עד שתחבר מחדש.")) return;
    run(() => api("/google/disconnect", { method: "POST" }));
  };

  return (
    <section className="card">
      <h2>חיבור לגוגל</h2>

      {result && <p className={result === "ok" ? "muted" : "error"}>{GOOGLE_RESULTS[result] ?? "החיבור לא הושלם."}</p>}

      {!status && !error && <p className="muted">טוען…</p>}

      {status && !status.configured && (
        <p className="error">
          חסרים מפתחות בשרת. צריך להגדיר ב-<code>.env</code> את <code>GOOGLE_CLIENT_ID</code>,{" "}
          <code>GOOGLE_CLIENT_SECRET</code> ו-<code>GOOGLE_TOKEN_KEY</code>.
        </p>
      )}

      {status?.configured && !status.status && (
        <>
          <p className="muted">גוגל לא מחוברת. הבוט לא רואה את המייל ואת היומן.</p>
          <p className="muted">
            במסך של גוגל תופיע אזהרה שהאפליקציה לא אומתה — זה צפוי. לוחצים "מתקדם" ואז "המשך".
          </p>
        </>
      )}

      {status?.status && (
        <ul className="lookup-list">
          <li>
            <span className="grow">מצב</span>
            {status.connected ? "מחובר" : "מנותק"}
          </li>
          {status.email && (
            <li>
              <span className="grow">תיבה</span>
              {status.email}
            </li>
          )}
          {status.connected_at && (
            <li>
              <span className="grow">חובר</span>
              {formatDateTime(status.connected_at)}
            </li>
          )}
          <li>
            <span className="grow">נבדק לאחרונה</span>
            {status.last_checked_at ? formatDateTime(status.last_checked_at) : "עוד לא"}
          </li>
        </ul>
      )}

      {status?.status === "disconnected" && (
        <p className="error">
          החיבור נותק{status.last_error ? `: ${status.last_error}` : ""}. צריך לחבר מחדש.
        </p>
      )}

      {status && status.missing_scopes.length > 0 && (
        <p className="error">
          לא אושרו כל ההרשאות. חסרות: {status.missing_scopes.map(scopeLabel).join(", ")}. חיבור מחדש
          יבקש אותן שוב.
        </p>
      )}

      <div className="toolbar">
        {status?.configured && (
          <button onClick={connect} disabled={busy}>
            {status.status ? "חבר מחדש" : "חבר גוגל"}
          </button>
        )}
        {status?.status && (
          <>
            <button className="link-btn" disabled={busy} onClick={() => run(() => api("/google/check", { method: "POST" }))}>
              בדוק עכשיו
            </button>
            <button className="link-btn danger" disabled={busy} onClick={disconnect}>
              ניתוק
            </button>
          </>
        )}
      </div>

      {error && <p className="error">{error}</p>}
    </section>
  );
}

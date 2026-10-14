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

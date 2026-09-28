/**
 * Every date and time this product shows a human is Bangladesh time.
 *
 * The bare `toLocaleString()` these helpers replace renders in whatever
 * timezone the viewer's browser is set to. For most products that is the
 * right default; for this one it is precisely wrong. Our customers are
 * travellers — the moment they most need to read an eSIM's expiry is the
 * moment their phone has just picked up a foreign timezone. An expiry that
 * silently re-renders in Bangkok time cannot be compared against the
 * purchase receipt, the support reply or anything else we have told them.
 *
 * Asia/Dhaka is UTC+6 with no daylight saving, and matches what the backend
 * puts in emails.
 */

export const DISPLAY_TZ = "Asia/Dhaka";
export const DISPLAY_TZ_SUFFIX = "(GMT+6)";

const LOCALE = "en-GB";

type DateInput = string | number | Date | null | undefined;

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "28 Sep 2026" */
export function formatDate(value: DateInput, fallback = "—"): string {
  const d = toDate(value);
  if (!d) return fallback;
  return new Intl.DateTimeFormat(LOCALE, {
    timeZone: DISPLAY_TZ,
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(d);
}

/** "28 Sep 2026, 16:07" */
export function formatDateTime(value: DateInput, fallback = "—"): string {
  const d = toDate(value);
  if (!d) return fallback;
  return new Intl.DateTimeFormat(LOCALE, {
    timeZone: DISPLAY_TZ,
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

/** "28 Sep 2026, 16:07 (GMT+6)" — for anywhere the zone itself matters. */
export function formatDateTimeZoned(value: DateInput, fallback = "—"): string {
  const d = toDate(value);
  if (!d) return fallback;
  return `${formatDateTime(d)} ${DISPLAY_TZ_SUFFIX}`;
}

/** "16:07" */
export function formatTime(value: DateInput, fallback = "—"): string {
  const d = toDate(value);
  if (!d) return fallback;
  return new Intl.DateTimeFormat(LOCALE, {
    timeZone: DISPLAY_TZ,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
}

/**
 * "Tue, 28 Sep 2026" — for chart axes and report headings built from a plain
 * `YYYY-MM-DD` the backend already grouped in its own terms. Such a string is
 * a calendar date, not an instant, so it is read as UTC midnight and never
 * shifted; doing otherwise would move a day's sales onto the day before.
 */
export function formatDayLabel(
  isoDay: string,
  opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }
): string {
  const d = toDate(`${isoDay}T00:00:00Z`);
  if (!d) return isoDay;
  return new Intl.DateTimeFormat(LOCALE, { ...opts, timeZone: "UTC" }).format(d);
}

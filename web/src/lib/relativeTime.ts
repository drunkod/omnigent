import i18n from "@/i18n";

const MIN_MS = 60_000;
const HOUR_MS = 60 * MIN_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;
const MONTH_MS = 30 * DAY_MS;
const YEAR_MS = 365 * DAY_MS;

// "mo" (not "m") for months disambiguates from minutes.
export function relativeTime(timestampMs: number, nowMs: number = Date.now()): string {
  const diff = Math.max(0, nowMs - timestampMs);
  if (diff < MIN_MS) return i18n.t("time.now");
  if (diff < HOUR_MS) {
    return i18n.t("time.minutesShort", { count: Math.floor(diff / MIN_MS) });
  }
  if (diff < DAY_MS) {
    return i18n.t("time.hoursShort", { count: Math.floor(diff / HOUR_MS) });
  }
  if (diff < WEEK_MS) {
    return i18n.t("time.daysShort", { count: Math.floor(diff / DAY_MS) });
  }
  if (diff < MONTH_MS) {
    return i18n.t("time.weeksShort", { count: Math.floor(diff / WEEK_MS) });
  }
  if (diff < YEAR_MS) {
    return i18n.t("time.monthsShort", { count: Math.floor(diff / MONTH_MS) });
  }
  return i18n.t("time.yearsShort", { count: Math.floor(diff / YEAR_MS) });
}

export function absoluteTime(timestampMs: number): string {
  return new Date(timestampMs).toLocaleString(i18n.language || undefined);
}

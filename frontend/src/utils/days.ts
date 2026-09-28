// Analytics days are counted where the viewer is: their profile's time zone, else UTC. The
// API says which in each response (`timezone`), so "Today" is today there, not in UTC.

/** Today's date as YYYY-MM-DD in `timeZone`; UTC's when it's missing or unknown to this browser. */
export function todayIn(timeZone: string | null | undefined, now: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: timeZone || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
    const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value;
    return `${part('year')}-${part('month')}-${part('day')}`;
  } catch {
    return now.toISOString().slice(0, 10);
  }
}

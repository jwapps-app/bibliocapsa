/** Seconds → compact "Xh Ym" reading-time label (shared by stats + book sessions). */
export const fmtH = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

/** Today's calendar date where the user IS, as YYYY-MM-DD. `toISOString()` is UTC,
 *  so at 8 pm in Chicago it already says tomorrow -- and a book marked read
 *  "today" was dated a day late. */
export const localToday = (d: Date = new Date()) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

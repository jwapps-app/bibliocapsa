/** Seconds → compact "Xh Ym" reading-time label (shared by stats + book sessions). */
export const fmtH = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
};

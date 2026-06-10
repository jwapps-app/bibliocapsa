// Maps a chosen column count (2–8) to a responsive Tailwind grid-cols class.
// The chosen count is the DESKTOP (lg) target; smaller screens step down so a
// dense desktop grid (e.g. 7) stays readable on tablet/phone. Shared by the
// library grid (InfiniteBooks) and the Series / Shelf grids.
// (All class strings are static so Tailwind keeps them in the build.)
export const COLS_CLASS: Record<number, string> = {
  // 2–5 are honored exactly at every breakpoint. 6–8 are dense desktop targets,
  // so they step down on small screens (keeps the default 7 phone-friendly).
  2: "grid-cols-2",
  3: "grid-cols-3",
  4: "grid-cols-4",
  5: "grid-cols-5",
  6: "grid-cols-3 sm:grid-cols-4 lg:grid-cols-6",
  7: "grid-cols-3 sm:grid-cols-5 lg:grid-cols-7",
  8: "grid-cols-3 sm:grid-cols-5 lg:grid-cols-8",
};

export function colsClass(n: number | undefined): string {
  return COLS_CLASS[n ?? 7] ?? COLS_CLASS[7];
}

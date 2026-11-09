export type Trace = { distance_m: number[]; laps: Record<string, any>; provenance: string }

/** Delta time (s) of lap vs reference at each distance; null where either side is unavailable. Positive = slower. */
export function deltaSeries(lapT: (number | null)[], refT: (number | null)[]): (number | null)[] {
  return lapT.map((v, i) => (v == null || refT[i] == null ? null : +(v - (refT[i] as number)).toFixed(4)))
}

export function fmtTime(s: number | null | undefined): string {
  if (s == null || !isFinite(s)) return '–'
  const m = Math.floor(s / 60)
  return `${m}:${(s - m * 60).toFixed(3).padStart(6, '0')}`
}

/** Index of the grid point nearest to a distance (for cursor sync). */
export function nearestIndex(grid: number[], d: number): number {
  let lo = 0, hi = grid.length - 1
  while (lo < hi) { const mid = (lo + hi) >> 1; if (grid[mid] < d) lo = mid + 1; else hi = mid }
  if (lo > 0 && Math.abs(grid[lo - 1] - d) <= Math.abs(grid[lo] - d)) lo--
  return lo
}

const LABELS: Record<string, string> = {
  early_braking: 'Frenata anticipata', late_braking: 'Frenata tardiva', early_brake_release: 'Rilascio freno anticipato',
  brake_peak_higher: 'Picco freno più alto', low_min_speed: 'Velocità minima più bassa',
  late_throttle: 'Accelerazione tardiva', slow_exit: 'Uscita più lenta',
}
export const findingLabel = (t: string) => LABELS[t] ?? t

export function findingText(f: { type: string; evidence: Record<string, number> }): string {
  return Object.entries(f.evidence).map(([k, v]) => `${k}=${v}`).join(' · ')
}

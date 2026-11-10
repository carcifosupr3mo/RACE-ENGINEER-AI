export const fmtDelta = (d: number | null | undefined): string => (d == null || !isFinite(d)) ? '–' : (d > 0 ? '+' : d < 0 ? '−' : '') + Math.abs(d).toFixed(3)
export const deltaClass = (d: number | null | undefined): string => (d == null || !isFinite(d)) ? 'neutral' : d > 0.005 ? 'slow' : d < -0.005 ? 'fast' : 'neutral'
export const fmtTime = (t: number | null | undefined): string => {
  if (t == null || !isFinite(t) || t <= 0) return '–'
  const m = Math.floor(t / 60), s = t - m * 60
  return `${m}:${s.toFixed(3).padStart(6, '0')}`
}
export const gearLabel = (g: number | null | undefined): string => g == null ? '–' : g < 0 ? 'R' : g === 0 ? 'N' : String(g)
export const levelClass = (l: string | undefined): string => l === 'alta' ? 'hi' : l === 'media' ? 'mid' : 'lo'

/** Slice the reference polyline between two lap distances (used to draw braking / release / acceleration zones). */
export function slicePoints(points: number[][], from: number, to: number): number[][] {
  return points.filter(p => p[2] >= from && p[2] <= to)
}
export function bounds(points: number[][]) {
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity
  for (const p of points) { x0 = Math.min(x0, p[0]); x1 = Math.max(x1, p[0]); z0 = Math.min(z0, p[1]); z1 = Math.max(z1, p[1]) }
  return { x0, x1, z0, z1 }
}

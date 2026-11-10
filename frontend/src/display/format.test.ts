import { describe, expect, it } from 'vitest'
import { bounds, deltaClass, fmtDelta, fmtTime, gearLabel, slicePoints } from './format'
import { nextBackoff } from './useEngineerStream'

describe('display formatting', () => {
  it('formats delta with sign and never invents a value', () => {
    expect(fmtDelta(0.1234)).toBe('+0.123'); expect(fmtDelta(-0.5)).toBe('−0.500'); expect(fmtDelta(null)).toBe('–'); expect(fmtDelta(NaN)).toBe('–')
    expect(deltaClass(0.2)).toBe('slow'); expect(deltaClass(-0.2)).toBe('fast'); expect(deltaClass(0.001)).toBe('neutral'); expect(deltaClass(undefined)).toBe('neutral')
  })
  it('formats lap times and gears', () => {
    expect(fmtTime(59.1)).toBe('0:59.100'); expect(fmtTime(null)).toBe('–'); expect(fmtTime(0)).toBe('–')
    expect(gearLabel(-1)).toBe('R'); expect(gearLabel(0)).toBe('N'); expect(gearLabel(4)).toBe('4'); expect(gearLabel(null)).toBe('–')
  })
  it('slices the polyline by lap distance and computes bounds', () => {
    const pts = [[0, 0, 0], [1, 1, 10], [2, 4, 20], [3, 2, 30]]
    expect(slicePoints(pts, 10, 20).length).toBe(2)
    expect(bounds(pts)).toEqual({ x0: 0, x1: 3, z0: 0, z1: 4 })
  })
  it('reconnect back-off grows and is capped', () => {
    let b = 800; for (let i = 0; i < 10; i++) b = nextBackoff(b)
    expect(b).toBe(5000); expect(nextBackoff(800)).toBeGreaterThan(800)
  })
})

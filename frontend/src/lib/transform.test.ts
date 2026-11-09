import { describe, expect, it } from 'vitest'
import { deltaSeries, findingLabel, fmtTime, nearestIndex } from './transform'

describe('transform', () => {
  it('delta keeps nulls (no invented values)', () => {
    expect(deltaSeries([1, null, 3], [0.5, 2, null])).toEqual([0.5, null, null])
  })
  it('formats lap times', () => {
    expect(fmtTime(59.1)).toBe('0:59.100')
    expect(fmtTime(125.0346)).toBe('2:05.035')
    expect(fmtTime(null)).toBe('–')
    expect(fmtTime(NaN)).toBe('–')
  })
  it('nearestIndex', () => {
    const g = [0, 5, 10, 15]
    expect(nearestIndex(g, 6)).toBe(1)
    expect(nearestIndex(g, 8)).toBe(2)
    expect(nearestIndex(g, -3)).toBe(0)
    expect(nearestIndex(g, 99)).toBe(3)
  })
  it('labels known and unknown findings', () => {
    expect(findingLabel('late_throttle')).toBe('Accelerazione tardiva')
    expect(findingLabel('x')).toBe('x')
  })
})

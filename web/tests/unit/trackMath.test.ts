import { describe, expect, it } from 'vitest'
import { fmtElapsed, fmtPace, hourStep, linear, logScale, nearestIndex, niceTicks, paceRange, paceTicks, range, runs } from '../../src/trackMath'

describe('scales', () => {
  it('maps a linear domain to a range, upside down when the range is reversed', () => {
    const y = linear(100, 200, 80, 0); expect(y(100)).toBe(80); expect(y(200)).toBe(0); expect(y(150)).toBe(40); expect(linear(5, 5, 0, 10)(5)).toBe(0)
  })

  it('puts equal ratios of pace the same distance apart on a log scale', () => {
    const y = logScale(3, 24, 0, 300); expect(y(3)).toBeCloseTo(0); expect(y(24)).toBeCloseTo(300); expect(y(6) - y(3)).toBeCloseTo(y(12) - y(6)); expect(y(12) - y(6)).toBeCloseTo(y(24) - y(12))
  })
})

describe('ranges', () => {
  it('uses the data\'s own range with a margin, not zero, and ignores gaps', () => {
    const [lo, hi] = range([300, null, 500, 400]); expect(lo).toBeCloseTo(290); expect(hi).toBeCloseTo(510)
    const [flo, fhi] = range([7, 7]); expect(flo).toBeLessThan(7); expect(fhi).toBeGreaterThan(7)                            // a flat series still gets a range
    expect(range([])).toEqual([0, 1])
  })

  it('keeps the pace range inside the floor and cap and drops extreme slow values', () => {
    const [lo, hi] = paceRange([5.5, 6, 6.2, 7, 6.5, 120, 200, 5.8, 6.1, 6.4]); expect(lo).toBeGreaterThan(4); expect(hi).toBeLessThanOrEqual(36); expect(hi).toBeGreaterThan(7)
    const [a, b] = paceRange([6, 6, 6]); expect(b / a).toBeGreaterThan(1.3)                                  // a flat pace still gets a range
    expect(paceRange([])).toEqual([2.5, 30])
  })
})

describe('ticks and formatting', () => {
  it('gives round ticks inside the range', () => {
    const t = niceTicks(103, 487, 5); expect(t[0]).toBeGreaterThanOrEqual(103); expect(t[t.length - 1]).toBeLessThanOrEqual(487); expect(t.every(v => v % 50 === 0 || v % 100 === 0)).toBe(true); expect(niceTicks(5, 5)).toEqual([5])
    expect(paceTicks(4.2, 12)).toEqual([5, 6, 7, 8, 10, 12]); expect(hourStep(80)).toBe(12); expect(hourStep(6)).toBe(1)
  })

  it('formats pace, durations', () => {
    expect(fmtPace(5.5)).toBe('5:30'); expect(fmtPace(6)).toBe('6:00'); expect(fmtPace(5.999)).toBe('6:00'); expect(fmtPace(12.25)).toBe('12:15'); expect(fmtPace(null)).toBe('–'); expect(fmtElapsed(5400)).toBe('1 h 30 min'); expect(fmtElapsed(900)).toBe('15 min')
  })
})

describe('data helpers', () => {
  it('finds the nearest entry of a sorted array, also at the ends and with gaps', () => {
    const xs = [0, 10, 20, 30]; expect(nearestIndex(xs, 14)).toBe(1); expect(nearestIndex(xs, 16)).toBe(2); expect(nearestIndex(xs, -5)).toBe(0); expect(nearestIndex(xs, 99)).toBe(3); expect(nearestIndex([1], 5)).toBe(0)
  })

  it('splits a line into runs at the gaps', () => {
    expect(runs([0, 1, 2, 3, 4], [5, 6, null, 7, 8])).toEqual([[[0, 5], [1, 6]], [[3, 7], [4, 8]]]); expect(runs([0], [null])).toEqual([])
  })
})

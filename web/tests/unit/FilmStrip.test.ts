import { describe, expect, it } from 'vitest'
import { dragBeats } from '../../src/components/FilmStrip'

describe('dragBeats', () => {
  it('rounds a drag to the nearest whole beat', () => {
    expect(dragBeats(24, 10, [-5, 5])).toBe(2); expect(dragBeats(26, 10, [-5, 5])).toBe(3); expect(dragBeats(-14, 10, [-5, 5])).toBe(-1)
  })
  it('stops at the room the cut has either way', () => {
    expect(dragBeats(400, 10, [-2, 3])).toBe(3); expect(dragBeats(-400, 10, [-2, 3])).toBe(-2); expect(dragBeats(30, 10, [0, 0])).toBe(0)
  })
  it('is no move when the strip has no width yet', () => {
    expect(dragBeats(50, 0, [-5, 5])).toBe(0); expect(dragBeats(-3, 10, [-5, 5])).toBe(0)
  })
})

import { describe, expect, it } from 'vitest'
import { baseLine, baseOf, clipLabel, spansByClip, usedSet, wordState } from '../../src/marks'

describe('marks helpers', () => {
  it('names a clip by its number and a line by clip number and segment', () => {
    expect(clipLabel('CAM_20260222130830_0023_D')).toBe('0023')
    expect(baseLine('CAM_20260222130830_0023_D', 7)).toBe('0023.07')
    expect(baseLine('CAM_20260222130830_0023_D', 27)).toBe('0023.27')
  })

  it('counts any piece of a split line as the whole line', () => {
    expect(baseOf('0023.27.2')).toBe('0023.27')
    expect(baseOf('0023.27')).toBe('0023.27')
    const u = usedSet(['0023.27.1', '0024.00'])
    expect(u.has('0023.27') && u.has('0024.00') && !u.has('0023.28')).toBe(true)
    expect(usedSet(undefined).size).toBe(0)
  })

  it('shows a mark before anything else, then whether the draft plays the line', () => {
    expect(wordState({ m: 'never' }, true)).toBe('never')
    expect(wordState({ m: 'must' }, false)).toBe('must')
    expect(wordState({}, true)).toBe('used')
    expect(wordState({}, false)).toBe('free')
  })

  it('turns selected words into one span per segment per clip', () => {
    const m = spansByClip([
      { clip: 'A', si: 3, i: 4 }, { clip: 'A', si: 3, i: 5 }, { clip: 'A', si: 4, i: 0 }, { clip: 'A', si: 4, i: 1 }, { clip: 'A', si: 4, i: 2 }, { clip: 'B', si: 0, i: 7 },
    ])
    expect(m.get('A')).toEqual([{ seg: 3, from: 4, to: 5 }, { seg: 4, from: 0, to: 2 }])
    expect(m.get('B')).toEqual([{ seg: 0, from: 7, to: 7 }])
  })

  it('handles no words', () => { expect(spansByClip([]).size).toBe(0) })
})
